"""Cache implementations for pixiu store."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import pickle
from typing import Any


@dataclass(frozen=True)
class CacheRecord:
    etag: str | None
    last_modified: str | None


class InMemoryCache:
    def __init__(self, max_entries: int = 128) -> None:
        self._max_entries = max_entries
        self._values: OrderedDict[str, tuple[CacheRecord, Any]] = OrderedDict()

    def get(self, key: str, record: CacheRecord) -> Any | None:
        value = self._values.get(key)
        if value is None:
            return None

        cached_record, cached_value = value
        if cached_record != record:
            self._values.pop(key, None)
            return None

        self._values.move_to_end(key)
        return cached_value

    def set(self, key: str, record: CacheRecord, value: Any) -> None:
        self._values[key] = (record, value)
        self._values.move_to_end(key)
        while len(self._values) > self._max_entries:
            self._values.popitem(last=False)

    def clear(self) -> None:
        self._values.clear()


class DiskCache:
    def __init__(self, cache_dir: Path | str) -> None:
        self._cache_dir = Path(cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    def get(self, key: str, record: CacheRecord) -> Any | None:
        metadata_path, value_path = self._paths(key)
        if not metadata_path.exists() or not value_path.exists():
            return None

        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            cached_record = CacheRecord(
                etag=metadata.get("etag"),
                last_modified=metadata.get("last_modified"),
            )
            if cached_record != record:
                self._delete(key)
                return None

            with value_path.open("rb") as f:
                return pickle.load(f)
        except (OSError, ValueError, pickle.PickleError):
            self._delete(key)
            return None

    def set(self, key: str, record: CacheRecord, value: Any) -> None:
        metadata_path, value_path = self._paths(key)
        metadata = {"etag": record.etag, "last_modified": record.last_modified}

        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
        with value_path.open("wb") as f:
            pickle.dump(value, f)

    def clear(self) -> None:
        for child in self._cache_dir.glob("*.json"):
            child.unlink(missing_ok=True)
        for child in self._cache_dir.glob("*.pkl"):
            child.unlink(missing_ok=True)

    def _delete(self, key: str) -> None:
        metadata_path, value_path = self._paths(key)
        metadata_path.unlink(missing_ok=True)
        value_path.unlink(missing_ok=True)

    def _paths(self, key: str) -> tuple[Path, Path]:
        digest = sha256(key.encode("utf-8")).hexdigest()
        return (
            self._cache_dir / f"{digest}.json",
            self._cache_dir / f"{digest}.pkl",
        )


class PixiuCache:
    def __init__(
        self,
        max_entries: int = 128,
        disk_cache_dir: Path | str | None = None,
    ) -> None:
        self._memory = InMemoryCache(max_entries=max_entries)
        self._disk = DiskCache(disk_cache_dir) if disk_cache_dir is not None else None

    def get(self, key: str, record: CacheRecord) -> Any | None:
        value = self._memory.get(key, record)
        if value is not None:
            return value

        if self._disk is None:
            return None

        value = self._disk.get(key, record)
        if value is not None:
            self._memory.set(key, record, value)
        return value

    def set(self, key: str, record: CacheRecord, value: Any) -> None:
        self._memory.set(key, record, value)
        if self._disk is not None:
            self._disk.set(key, record, value)

    def clear(self) -> None:
        self._memory.clear()
        if self._disk is not None:
            self._disk.clear()
