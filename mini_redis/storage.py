from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable, Iterable, Protocol


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
class HashNode:
    key: bytes
    value: bytes
    expires_at: float | None = None
    next: HashNode | None = None


class Bucket:
    def __init__(self) -> None:
        self.head: HashNode | None = None

    def locate(self, key: bytes) -> tuple[HashNode | None, HashNode | None]:
        previous: HashNode | None = None
        current = self.head
        while current is not None:
            if current.key == key:
                return previous, current
            previous = current
            current = current.next
        return None, None

    def prepend(self, node: HashNode) -> None:
        node.next = self.head
        self.head = node

    def remove(self, previous: HashNode | None, current: HashNode) -> None:
        if previous is None:
            self.head = current.next
        else:
            previous.next = current.next
        current.next = None

    def iter_nodes(self) -> Iterable[HashNode]:
        current = self.head
        while current is not None:
            yield current
            current = current.next


class HashTableStore:
    def __init__(
        self,
        bucket_count: int = 64,
        hash_function: Callable[[bytes], int] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if bucket_count <= 0:
            raise ValueError("bucket_count must be greater than zero")

        self._buckets = [Bucket() for _ in range(bucket_count)]
        self._hash_function = hash_function or hash
        self._clock = clock or time.monotonic
        self._lock = threading.RLock()
        self._size = 0

    def set(self, key: bytes, value: bytes) -> None:
        with self._lock:
            bucket = self._bucket_for(key)
            previous, current = bucket.locate(key)
            if current is not None:
                if self._is_expired(current):
                    bucket.remove(previous, current)
                    self._size -= 1
                else:
                    current.value = value
                    current.expires_at = None
                    return

            bucket.prepend(HashNode(key=key, value=value))
            self._size += 1

    def get(self, key: bytes) -> bytes | None:
        with self._lock:
            bucket = self._bucket_for(key)
            previous, current = bucket.locate(key)
            if current is None:
                return None
            if self._is_expired(current):
                bucket.remove(previous, current)
                self._size -= 1
                return None
            return current.value

    def delete(self, keys: Iterable[bytes]) -> int:
        with self._lock:
            deleted = 0
            for key in keys:
                bucket = self._bucket_for(key)
                previous, current = bucket.locate(key)
                if current is None:
                    continue
                if self._is_expired(current):
                    bucket.remove(previous, current)
                    self._size -= 1
                    continue
                bucket.remove(previous, current)
                self._size -= 1
                deleted += 1
            return deleted

    def expire(self, key: bytes, seconds: int) -> bool:
        with self._lock:
            bucket = self._bucket_for(key)
            previous, current = bucket.locate(key)
            if current is None:
                return False
            if self._is_expired(current):
                bucket.remove(previous, current)
                self._size -= 1
                return False

            current.expires_at = self._clock() + seconds
            if self._is_expired(current):
                bucket.remove(previous, current)
                self._size -= 1
            return True

    def __len__(self) -> int:
        return self._size

    def _bucket_for(self, key: bytes) -> Bucket:
        return self._buckets[self._bucket_index(key)]

    def _bucket_index(self, key: bytes) -> int:
        return self._hash_function(key) % len(self._buckets)

    def _is_expired(self, node: HashNode) -> bool:
        return node.expires_at is not None and node.expires_at <= self._clock()
