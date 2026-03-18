import threading
import unittest

from mini_redis.storage import HashTableStore


class FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self.current = start

    def __call__(self) -> float:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += seconds


class HashTableStoreTests(unittest.TestCase):
    def test_handles_collisions_in_same_bucket(self) -> None:
        store = HashTableStore(bucket_count=2, hash_function=lambda _: 0)

        store.set(b"alpha", b"1")
        store.set(b"beta", b"2")

        self.assertEqual(store.get(b"alpha"), b"1")
        self.assertEqual(store.get(b"beta"), b"2")

    def test_overwrite_replaces_existing_value(self) -> None:
        store = HashTableStore()

        store.set(b"key", b"first")
        store.set(b"key", b"second")

        self.assertEqual(store.get(b"key"), b"second")
        self.assertEqual(len(store), 1)

    def test_missing_key_returns_none(self) -> None:
        store = HashTableStore()

        self.assertIsNone(store.get(b"missing"))

    def test_delete_counts_only_existing_keys(self) -> None:
        store = HashTableStore()
        store.set(b"first", b"1")
        store.set(b"second", b"2")

        deleted = store.delete([b"first", b"missing", b"second"])

        self.assertEqual(deleted, 2)
        self.assertIsNone(store.get(b"first"))
        self.assertIsNone(store.get(b"second"))

    def test_expired_key_is_removed_on_access(self) -> None:
        clock = FakeClock()
        store = HashTableStore(clock=clock)
        store.set(b"session", b"token")
        self.assertTrue(store.expire(b"session", 5))

        clock.advance(6)

        self.assertIsNone(store.get(b"session"))
        self.assertEqual(len(store), 0)

    def test_delete_does_not_count_expired_keys(self) -> None:
        clock = FakeClock()
        store = HashTableStore(clock=clock)
        store.set(b"ephemeral", b"value")
        store.set(b"stable", b"value")
        self.assertTrue(store.expire(b"ephemeral", 1))
        clock.advance(2)

        deleted = store.delete([b"ephemeral", b"stable"])

        self.assertEqual(deleted, 1)
        self.assertIsNone(store.get(b"ephemeral"))
        self.assertIsNone(store.get(b"stable"))

    def test_capacity_is_normalized_to_power_of_two(self) -> None:
        store = HashTableStore(bucket_count=3)

        self.assertEqual(store.capacity, 4)

    def test_resize_doubles_capacity_when_load_factor_is_exceeded(self) -> None:
        store = HashTableStore(bucket_count=2, load_factor_threshold=0.5)

        store.set(b"alpha", b"1")
        store.set(b"beta", b"2")

        self.assertEqual(store.capacity, 4)
        self.assertEqual(len(store), 2)

    def test_resize_preserves_existing_values(self) -> None:
        store = HashTableStore(bucket_count=2, load_factor_threshold=0.75)
        expected = {
            b"alpha": b"1",
            b"beta": b"2",
            b"gamma": b"3",
            b"delta": b"4",
        }

        for key, value in expected.items():
            store.set(key, value)

        self.assertEqual(store.capacity, 8)
        for key, value in expected.items():
            self.assertEqual(store.get(key), value)

    def test_resize_discards_expired_entries(self) -> None:
        clock = FakeClock()
        store = HashTableStore(bucket_count=2, load_factor_threshold=1.0, clock=clock)
        store.set(b"stale", b"old")
        self.assertTrue(store.expire(b"stale", 1))
        clock.advance(2)

        store.set(b"fresh-1", b"1")
        store.set(b"fresh-2", b"2")

        self.assertEqual(store.capacity, 4)
        self.assertEqual(len(store), 2)
        self.assertIsNone(store.get(b"stale"))
        self.assertEqual(store.get(b"fresh-1"), b"1")
        self.assertEqual(store.get(b"fresh-2"), b"2")

    def test_load_factor_reflects_current_live_entries(self) -> None:
        store = HashTableStore(bucket_count=4)
        store.set(b"alpha", b"1")
        store.set(b"beta", b"2")

        self.assertEqual(store.load_factor, 0.5)

    def test_persist_removes_existing_expiration(self) -> None:
        clock = FakeClock()
        store = HashTableStore(clock=clock)
        store.set(b"session", b"token")
        self.assertTrue(store.expire(b"session", 5))

        self.assertTrue(store.persist(b"session"))
        clock.advance(10)

        self.assertEqual(store.get(b"session"), b"token")

    def test_persist_returns_false_for_missing_or_non_expiring_key(self) -> None:
        store = HashTableStore()
        store.set(b"session", b"token")

        self.assertFalse(store.persist(b"missing"))
        self.assertFalse(store.persist(b"session"))

    def test_ttl_returns_remaining_seconds_for_expiring_key(self) -> None:
        clock = FakeClock()
        store = HashTableStore(clock=clock)
        store.set(b"session", b"token")
        self.assertTrue(store.expire(b"session", 5))

        self.assertEqual(store.ttl(b"session"), 5)
        clock.advance(2)
        self.assertEqual(store.ttl(b"session"), 3)

    def test_ttl_returns_minus_one_for_persistent_key(self) -> None:
        store = HashTableStore()
        store.set(b"session", b"token")

        self.assertEqual(store.ttl(b"session"), -1)

    def test_ttl_returns_zero_for_missing_or_expired_key(self) -> None:
        clock = FakeClock()
        store = HashTableStore(clock=clock)
        store.set(b"session", b"token")
        self.assertTrue(store.expire(b"session", 1))
        clock.advance(2)

        self.assertEqual(store.ttl(b"missing"), 0)
        self.assertEqual(store.ttl(b"session"), 0)
        self.assertEqual(len(store), 0)

    def test_active_expiration_cleans_expired_keys_during_writes(self) -> None:
        clock = FakeClock()
        store = HashTableStore(
            bucket_count=1,
            clock=clock,
            active_expiration_writes=1,
            active_expiration_bucket_count=1,
        )
        store.set(b"stale", b"old")
        self.assertTrue(store.expire(b"stale", 1))
        clock.advance(2)

        store.set(b"fresh", b"new")

        self.assertEqual(len(store), 1)
        self.assertIsNone(store.get(b"stale"))
        self.assertEqual(store.get(b"fresh"), b"new")
        self.assertEqual(store.expired_removed_count, 1)

    def test_snapshot_tracks_resize_and_expired_cleanup(self) -> None:
        clock = FakeClock()
        store = HashTableStore(bucket_count=2, load_factor_threshold=0.5, clock=clock)

        store.set(b"stale", b"old")
        self.assertTrue(store.expire(b"stale", 1))
        clock.advance(2)
        self.assertIsNone(store.get(b"stale"))

        store.set(b"alpha", b"1")
        store.set(b"beta", b"2")

        stats = store.get_stats()

        self.assertEqual(stats.size, 2)
        self.assertEqual(stats.capacity, 4)
        self.assertEqual(stats.load_factor, 0.5)
        self.assertEqual(stats.resize_count, 1)
        self.assertEqual(stats.expired_removed_count, 1)

    def test_snapshot_is_consistent_after_concurrent_access(self) -> None:
        store = HashTableStore(bucket_count=4, load_factor_threshold=0.75)
        worker_count = 6
        iterations = 80
        errors: list[BaseException] = []
        error_lock = threading.Lock()
        start = threading.Barrier(worker_count)

        def worker(worker_id: int) -> None:
            try:
                start.wait()
                for index in range(iterations):
                    key = f"worker:{worker_id}:{index}".encode()
                    store.set(key, b"value")
                    self.assertEqual(store.get(key), b"value")
                    if index % 4 == 0:
                        self.assertTrue(store.expire(key, 0))
                        self.assertIsNone(store.get(key))
                    else:
                        self.assertEqual(store.delete([key]), 1)
            except BaseException as exc:  # pragma: no cover - surfaced by the test assertions below
                with error_lock:
                    errors.append(exc)

        threads = [threading.Thread(target=worker, args=(worker_id,)) for worker_id in range(worker_count)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())

        self.assertFalse(errors, errors)
        stats = store.get_stats()
        expired_per_worker = sum(1 for index in range(iterations) if index % 4 == 0)
        self.assertEqual(stats.size, 0)
        self.assertEqual(stats.capacity, store.capacity)
        self.assertEqual(stats.load_factor, 0.0)
        self.assertEqual(stats.expired_removed_count, worker_count * expired_per_worker)


if __name__ == "__main__":
    unittest.main()
