from __future__ import annotations

import unittest

from mini_redis.router import CommandRouter, ServerStats
from mini_redis.storage import HashTableStore


class CommandRouterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.stats = ServerStats()
        self.store = HashTableStore()
        self.router = CommandRouter(self.store, self.stats)

    def test_set_get_and_delete_round_trip(self) -> None:
        self.assertEqual(self.router.dispatch([b"SET", b"alpha", b"1"], 1).reply.kind, "simple")

        get_result = self.router.dispatch([b"GET", b"alpha"], 1)
        self.assertEqual(get_result.reply.kind, "bulk")
        self.assertEqual(get_result.reply.value, b"1")

        delete_result = self.router.dispatch([b"DEL", b"alpha", b"missing"], 1)
        self.assertEqual(delete_result.reply.kind, "integer")
        self.assertEqual(delete_result.reply.value, 1)

    def test_expire_removes_key_lazily(self) -> None:
        self.router.dispatch([b"SET", b"temp", b"value"], 1)
        expire_result = self.router.dispatch([b"EXPIRE", b"temp", b"0"], 1)

        self.assertEqual(expire_result.reply.value, 1)
        self.assertIsNone(self.store.get(b"temp"))

    def test_persist_removes_expiration(self) -> None:
        self.router.dispatch([b"SET", b"temp", b"value"], 1)
        self.router.dispatch([b"EXPIRE", b"temp", b"10"], 1)

        persist_result = self.router.dispatch([b"PERSIST", b"temp"], 1)

        self.assertEqual(persist_result.reply.kind, "integer")
        self.assertEqual(persist_result.reply.value, 1)

    def test_info_includes_store_stats(self) -> None:
        self.router.dispatch([b"SET", b"alpha", b"1"], 1)

        result = self.router.dispatch([b"INFO"], 1)

        self.assertEqual(result.reply.kind, "bulk")
        self.assertIn(b"# Store\r\n", result.reply.value)
        self.assertIn(b"keys:1\r\n", result.reply.value)
        self.assertIn(b"capacity:64\r\n", result.reply.value)
        self.assertIn(b"load_factor:", result.reply.value)
        self.assertIn(b"resize_count:0\r\n", result.reply.value)
        self.assertIn(b"expired_removed_count:0\r\n", result.reply.value)

    def test_exit_and_quit_close_connection(self) -> None:
        self.assertTrue(self.router.dispatch([b"EXIT"], 1).close_connection)
        self.assertTrue(self.router.dispatch([b"QUIT"], 1).close_connection)

    def test_wrong_arity_returns_error(self) -> None:
        result = self.router.dispatch([b"GET"], 1)
        self.assertEqual(result.reply.kind, "error")
        self.assertIn("wrong number of arguments", result.reply.value)

    def test_unknown_command_returns_error(self) -> None:
        result = self.router.dispatch([b"UNKNOWN"], 1)
        self.assertEqual(result.reply.kind, "error")
        self.assertIn("unknown command", result.reply.value)


if __name__ == "__main__":
    unittest.main()
