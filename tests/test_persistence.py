from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mini_redis.persistence import SnapshotPersistence
from mini_redis.storage import HashTableStore


class FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self.current = start

    def __call__(self) -> float:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += seconds


class SnapshotPersistenceTests(unittest.TestCase):
    def test_snapshot_save_and_load_restores_live_entries(self) -> None:
        source_clock = FakeClock(start=100.0)
        source_store = HashTableStore(clock=source_clock)
        source_store.set(b"persistent", b"always")
        source_store.set(b"session", b"cached")
        self.assertTrue(source_store.expire(b"session", 10))
        source_store.set(b"expired", b"gone")
        self.assertTrue(source_store.expire(b"expired", 1))
        source_clock.advance(2)

        with tempfile.TemporaryDirectory() as temp_dir:
            snapshot_path = Path(temp_dir) / "mini_redis.snapshot"
            persistence = SnapshotPersistence(snapshot_path)

            saved = persistence.save(source_store)
            self.assertEqual(saved, 2)

            restored_clock = FakeClock(start=106.0)
            restored_store = HashTableStore(clock=restored_clock)
            loaded = persistence.load(restored_store)

        self.assertEqual(loaded, 2)
        self.assertEqual(restored_store.get(b"persistent"), b"always")
        self.assertEqual(restored_store.get(b"session"), b"cached")
        self.assertEqual(restored_store.ttl(b"session"), 4)
        self.assertIsNone(restored_store.get(b"expired"))

    def test_invalid_snapshot_entry_raises_value_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            snapshot_path = Path(temp_dir) / "broken.snapshot"
            snapshot_path.write_text('{"key":"bad"}\n', encoding="utf-8")
            persistence = SnapshotPersistence(snapshot_path)

            with self.assertRaises(ValueError):
                persistence.load(HashTableStore())


if __name__ == "__main__":
    unittest.main()
