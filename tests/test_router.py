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

    def test_hello_rejects_unsupported_protocol_version(self) -> None:
        result = self.router.dispatch([b"HELLO", b"9"], 7)

        self.assertEqual(result.reply.kind, "error")
        self.assertEqual(result.reply.error_code, "NOPROTO")
        self.assertIn("unsupported protocol version", result.reply.value)

    def test_hello_rejects_wrong_number_of_arguments(self) -> None:
        result = self.router.dispatch([b"HELLO", b"2", b"EXTRA"], 1)

        self.assertEqual(result.reply.kind, "error")
        self.assertEqual(result.reply.value, "wrong number of arguments for 'hello' command")

    def test_client_accepts_setinfo(self) -> None:
        result = self.router.dispatch([b"CLIENT", b"SETINFO", b"LIB-NAME", b"mini-redis-cli"], 1)

        self.assertEqual(result.reply.kind, "simple")
        self.assertEqual(result.reply.value, "OK")

    def test_client_rejects_unsupported_subcommand(self) -> None:
        result = self.router.dispatch([b"CLIENT", b"LIST"], 1)

        self.assertEqual(result.reply.kind, "error")
        self.assertEqual(result.reply.value, "unknown subcommand 'LIST' for CLIENT")

    def test_client_rejects_wrong_number_of_arguments_for_setinfo(self) -> None:
        result = self.router.dispatch([b"CLIENT", b"SETINFO", b"LIB-NAME"], 1)

        self.assertEqual(result.reply.kind, "error")
        self.assertEqual(result.reply.value, "wrong number of arguments for 'client' command")

    def test_client_rejects_unsupported_setinfo_option(self) -> None:
        result = self.router.dispatch([b"CLIENT", b"SETINFO", b"ID", b"client-1"], 1)

        self.assertEqual(result.reply.kind, "error")
        self.assertEqual(result.reply.value, "unsupported CLIENT SETINFO option 'ID'")

    def test_info_contains_connection_and_command_stats(self) -> None:
        self.stats.register_connection()
        self.stats.mark_command_processed()
        self.stats.mark_command_processed()

        result = self.router.dispatch([b"INFO"], 1)

        self.assertEqual(result.reply.kind, "bulk")
        self.assertIn(b"total_connections_received:1", result.reply.value)
        self.assertIn(b"total_commands_processed:2", result.reply.value)

    def test_info_supports_server_section(self) -> None:
        result = self.router.dispatch([b"INFO", b"server"], 1)

        self.assertEqual(result.reply.kind, "bulk")
        self.assertIn(b"# Server", result.reply.value)
        self.assertNotIn(b"# Stats", result.reply.value)

    def test_info_returns_empty_payload_for_unknown_section(self) -> None:
        result = self.router.dispatch([b"INFO", b"memory"], 1)

        self.assertEqual(result.reply.kind, "bulk")
        self.assertEqual(result.reply.value, b"")

    def test_info_rejects_wrong_number_of_arguments(self) -> None:
        result = self.router.dispatch([b"INFO", b"server", b"extra"], 1)

        self.assertEqual(result.reply.kind, "error")
        self.assertEqual(result.reply.value, "wrong number of arguments for 'info' command")


if __name__ == "__main__":
    unittest.main()
