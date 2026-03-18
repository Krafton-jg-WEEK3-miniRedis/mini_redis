from __future__ import annotations

import math
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

    def ttl(self, key: bytes) -> int:
        ...

    def persist(self, key: bytes) -> bool:
        ...

    def get_stats(self) -> StoreStats:
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
        active_expiration_writes: int = 16,
        active_expiration_bucket_count: int = 2,
    ) -> None:
        if bucket_count <= 0:
            raise ValueError("bucket_count must be greater than zero")
        if load_factor_threshold <= 0:
            raise ValueError("load_factor_threshold must be greater than zero")
        if active_expiration_writes <= 0:
            raise ValueError("active_expiration_writes must be greater than zero")
        if active_expiration_bucket_count <= 0:
            raise ValueError("active_expiration_bucket_count must be greater than zero")

        capacity = self._normalize_capacity(bucket_count)
        self._buckets: list[list[HashEntry]] = [[] for _ in range(capacity)]
        self._load_factor_threshold = load_factor_threshold
        self._hash_function = hash_function or hash
        self._clock = clock or time.monotonic
        self._lock = threading.RLock()
        self._active_expiration_writes = active_expiration_writes
        self._active_expiration_bucket_count = active_expiration_bucket_count
        self._writes_since_cleanup = 0
        self._active_expiration_cursor = 0
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
                    self._record_write()
                    return

            bucket.append(HashEntry(key=key, value=value))
            self._size += 1
            while self._current_load_factor() > self._load_factor_threshold:
                self._resize(self.capacity * 2)
            self._record_write()

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
            self._record_write()
            return deleted

    def expire(self, key: bytes, seconds: int) -> bool:
        with self._lock:
            bucket = self._bucket_for(key)
            index, entry = self._locate(bucket, key)
            if entry is None:
                self._record_write()
                return False
            if self._is_expired(entry):
                self._remove_from_bucket(bucket, index, expired=True)
                self._record_write()
                return False

            entry.expires_at = self._clock() + seconds
            if self._is_expired(entry):
                self._remove_from_bucket(bucket, index, expired=True)
            self._record_write()
            return True

    def ttl(self, key: bytes) -> int:
        with self._lock:
            bucket = self._bucket_for(key)
            index, entry = self._locate(bucket, key)
            if entry is None:
                return 0
            if self._is_expired(entry):
                self._remove_from_bucket(bucket, index, expired=True)
                return 0
            if entry.expires_at is None:
                return -1

            remaining = entry.expires_at - self._clock()
            if remaining <= 0:
                self._remove_from_bucket(bucket, index, expired=True)
                return 0
            return math.ceil(remaining)

    def persist(self, key: bytes) -> bool:
        with self._lock:
            bucket = self._bucket_for(key)
            index, entry = self._locate(bucket, key)
            if entry is None:
                self._record_write()
                return False
            if self._is_expired(entry):
                self._remove_from_bucket(bucket, index, expired=True)
                self._record_write()
                return False
            if entry.expires_at is None:
                self._record_write()
                return False

            entry.expires_at = None
            self._record_write()
            return True

    def __len__(self) -> int:
        with self._lock:
            return self._size

    def _bucket_for(self, key: bytes) -> list[HashEntry]:
        return self._buckets[self._bucket_index(key)]

    def _bucket_index(self, key: bytes) -> int:
        return self._hash_function(key) & (len(self._buckets) - 1)

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
        now = self._clock()
        for bucket in self._buckets:
            for entry in bucket:
                if not self._is_expired(entry, now=now):
                    live_entries.append(entry)
                else:
                    self._expired_removed_count += 1

        self._buckets = [[] for _ in range(self._normalize_capacity(new_capacity))]
        self._active_expiration_cursor %= len(self._buckets)
        self._size = 0
        self._resize_count += 1
        for entry in live_entries:
            self._bucket_for(entry.key).append(entry)
            self._size += 1

    def _normalize_capacity(self, bucket_count: int) -> int:
        return 1 << (bucket_count - 1).bit_length()

    def _current_load_factor(self) -> float:
        return self._size / len(self._buckets)

    def _record_write(self) -> None:
        self._writes_since_cleanup += 1
        if self._writes_since_cleanup < self._active_expiration_writes:
            return

        self._writes_since_cleanup = 0
        self._cleanup_expired_buckets(self._active_expiration_bucket_count)

    def _cleanup_expired_buckets(self, bucket_count: int) -> None:
        if not self._buckets:
            return

        scans = min(bucket_count, len(self._buckets))
        now = self._clock()
        for _ in range(scans):
            bucket = self._buckets[self._active_expiration_cursor]
            self._remove_expired_entries(bucket, now=now)
            self._active_expiration_cursor = (self._active_expiration_cursor + 1) % len(self._buckets)

    def _remove_expired_entries(self, bucket: list[HashEntry], *, now: float) -> None:
        live_entries = [entry for entry in bucket if not self._is_expired(entry, now=now)]
        removed_count = len(bucket) - len(live_entries)
        if removed_count == 0:
            return

        bucket[:] = live_entries
        self._size -= removed_count
        self._expired_removed_count += removed_count

    def _is_expired(self, entry: HashEntry, *, now: float | None = None) -> bool:
        current_time = self._clock() if now is None else now
        return entry.expires_at is not None and entry.expires_at <= current_time
