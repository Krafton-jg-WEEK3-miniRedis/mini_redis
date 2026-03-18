from __future__ import annotations

import sys
from pathlib import Path
from time import perf_counter

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from mini_redis.storage import HashTableStore


class DictStore:
    def __init__(self) -> None:
        self._data: dict[bytes, bytes] = {}

    def set(self, key: bytes, value: bytes) -> None:
        self._data[key] = value

    def get(self, key: bytes) -> bytes | None:
        return self._data.get(key)

    def delete(self, keys: list[bytes]) -> int:
        deleted = 0
        for key in keys:
            deleted += 1 if self._data.pop(key, None) is not None else 0
        return deleted


def benchmark_store(name: str, store, key_count: int) -> None:
    keys = [f"key:{index}".encode() for index in range(key_count)]
    values = [b"value"] * key_count

    start = perf_counter()
    for key, value in zip(keys, values):
        store.set(key, value)
    set_time = perf_counter() - start

    start = perf_counter()
    for key in keys:
        store.get(key)
    get_time = perf_counter() - start

    start = perf_counter()
    store.delete(keys)
    delete_time = perf_counter() - start

    print(
        f"{name:<16} keys={key_count:<6} "
        f"set={set_time:.6f}s get={get_time:.6f}s del={delete_time:.6f}s"
    )


def main() -> None:
    for key_count in (1_000, 10_000, 50_000):
        benchmark_store("hash_table", HashTableStore(), key_count)
        benchmark_store("dict_adapter", DictStore(), key_count)
        print()


if __name__ == "__main__":
    main()
