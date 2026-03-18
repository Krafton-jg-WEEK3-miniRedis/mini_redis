from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable, Iterable, Protocol

HashFunction = Callable[[bytes], int]


class KeyValueStore(Protocol):
    def set(self, key: bytes, value: bytes) -> None:
        ...

    def get(self, key: bytes) -> bytes | None:
        ...

    def delete(self, keys: Iterable[bytes]) -> int:
        ...

    def expire(self, key: bytes, seconds: int) -> bool:
        ...


@dataclass(slots=True)
class HashEntry:
    key: bytes
    value: bytes
    expires_at: float | None = None


@dataclass(frozen=True, slots=True)
class StoreStats:
    size: int
    capacity: int
    load_factor: float
    resize_count: int
    expired_removed_count: int


class HashTableStore:
    def __init__(
        self,
        bucket_count: int = 64,
        load_factor_threshold: float = 0.75,
        hash_function: HashFunction | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if bucket_count <= 0:
            raise ValueError("bucket_count must be greater than zero")
        if load_factor_threshold <= 0:
            raise ValueError("load_factor_threshold must be greater than zero")

        capacity = self._normalize_capacity(bucket_count)
        self._buckets: list[list[HashEntry]] = [[] for _ in range(capacity)]
        self._load_factor_threshold = load_factor_threshold
        self._hash_function = hash_function or hash
        self._clock = clock or time.monotonic
        self._lock = threading.RLock()
        self._size = 0
        self._resize_count = 0
        self._expired_removed_count = 0

    @property
    def capacity(self) -> int:
        with self._lock:
            return len(self._buckets)

    @property
    def load_factor(self) -> float:
        with self._lock:
            return self._current_load_factor()

    @property
    def resize_count(self) -> int:
        with self._lock:
            return self._resize_count

    @property
    def expired_removed_count(self) -> int:
        with self._lock:
            return self._expired_removed_count

    def get_stats(self) -> StoreStats:
        with self._lock:
            capacity = len(self._buckets)
            return StoreStats(
                size=self._size,
                capacity=capacity,
                load_factor=self._size / capacity,
                resize_count=self._resize_count,
                expired_removed_count=self._expired_removed_count,
            )

    def set(self, key: bytes, value: bytes) -> None:
        with self._lock:
            bucket = self._bucket_for(key)
            index, entry = self._locate(bucket, key)
            if entry is not None:
                if self._is_expired(entry):
                    self._remove_from_bucket(bucket, index, expired=True)
                else:
                    entry.value = value
                    entry.expires_at = None
                    return

            bucket.append(HashEntry(key=key, value=value))
            self._size += 1
            while self._current_load_factor() > self._load_factor_threshold:
                self._resize(self.capacity * 2)

    def get(self, key: bytes) -> bytes | None:
        with self._lock:
            bucket = self._bucket_for(key)
            index, entry = self._locate(bucket, key)
            if entry is None:
                return None
            if self._is_expired(entry):
                self._remove_from_bucket(bucket, index, expired=True)
                return None
            return entry.value

    def delete(self, keys: Iterable[bytes]) -> int:
        with self._lock:
            deleted = 0
            for key in keys:
                bucket = self._bucket_for(key)
                index, entry = self._locate(bucket, key)
                if entry is None:
                    continue
                expired = self._is_expired(entry)
                self._remove_from_bucket(bucket, index, expired=expired)
                if not expired:
                    deleted += 1
            return deleted

    def expire(self, key: bytes, seconds: int) -> bool:
        with self._lock:
            bucket = self._bucket_for(key)
            index, entry = self._locate(bucket, key)
            if entry is None:
                return False
            if self._is_expired(entry):
                self._remove_from_bucket(bucket, index, expired=True)
                return False

            entry.expires_at = self._clock() + seconds
            if self._is_expired(entry):
                self._remove_from_bucket(bucket, index, expired=True)
            return True

    def __len__(self) -> int:
        with self._lock:
            return self._size

    def _bucket_for(self, key: bytes) -> list[HashEntry]:
        return self._buckets[self._bucket_index(key)]

    def _bucket_index(self, key: bytes) -> int:
        return self._hash_function(key) & (self.capacity - 1)

    def _locate(self, bucket: list[HashEntry], key: bytes) -> tuple[int, HashEntry | None]:
        for index, entry in enumerate(bucket):
            if entry.key == key:
                return index, entry
        return -1, None

    def _remove_from_bucket(
        self, bucket: list[HashEntry], index: int, *, expired: bool = False
    ) -> HashEntry:
        self._size -= 1
        if expired:
            self._expired_removed_count += 1
        return bucket.pop(index)

    def _resize(self, new_capacity: int) -> None:
        live_entries = []
        for bucket in self._buckets:
            for entry in bucket:
                if not self._is_expired(entry):
                    live_entries.append(entry)
                else:
                    self._expired_removed_count += 1

        self._buckets = [[] for _ in range(self._normalize_capacity(new_capacity))]
        self._size = 0
        self._resize_count += 1
        for entry in live_entries:
            self._bucket_for(entry.key).append(entry)
            self._size += 1

    def _normalize_capacity(self, bucket_count: int) -> int:
        return 1 << (bucket_count - 1).bit_length()

    def _current_load_factor(self) -> float:
        return self._size / len(self._buckets)

    def _is_expired(self, entry: HashEntry) -> bool:
        return entry.expires_at is not None and entry.expires_at <= self._clock()
