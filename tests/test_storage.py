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


if __name__ == "__main__":
    unittest.main()
