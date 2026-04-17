"""Cache implementations for pixiu store."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from diskcache import Cache


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
        cache_path = Path(cache_dir)
        cache_path.mkdir(parents=True, exist_ok=True)
        self._cache = Cache(str(cache_path))

    def get(self, key: str, record: CacheRecord) -> Any | None:
        value = self._cache.get(key, default=None)
        if value is None:
            return None

        try:
            cached_record, cached_value = value
            if cached_record != record:
                self._cache.pop(key, default=None)
                return None
            return cached_value
        except Exception:
            self._cache.pop(key, default=None)
            return None

    def set(self, key: str, record: CacheRecord, value: Any) -> None:
        self._cache.set(key, (record, value))

    def clear(self) -> None:
        self._cache.clear()


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

    def get_memory(self, key: str, record: CacheRecord) -> Any | None:
        return self._memory.get(key, record)

    def set(self, key: str, record: CacheRecord, value: Any) -> None:
        self._memory.set(key, record, value)
        if self._disk is not None:
            self._disk.set(key, record, value)

    def set_memory(self, key: str, record: CacheRecord, value: Any) -> None:
        self._memory.set(key, record, value)

    def clear(self) -> None:
        self._memory.clear()
        if self._disk is not None:
            self._disk.clear()
