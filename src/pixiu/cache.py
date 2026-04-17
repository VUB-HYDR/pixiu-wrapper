"""Cache implementations for pixiu store."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
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
