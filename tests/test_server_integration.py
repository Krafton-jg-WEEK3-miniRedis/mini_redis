from __future__ import annotations

import socket
import tempfile
import threading
import unittest
from pathlib import Path

from mini_redis.server import MiniRedisTCPServer
from mini_redis.storage import HashTableStore


def encode_command(*parts: bytes) -> bytes:
    payload = [f"*{len(parts)}\r\n".encode()]
    for part in parts:
        payload.append(f"${len(part)}\r\n".encode())
        payload.append(part + b"\r\n")
    return b"".join(payload)


def read_reply(stream) -> bytes:
    first = stream.read(1)
    if not first:
        return b""

    line = stream.readline()
    if first in {b"+", b"-", b":"}:
        return first + line

    if first == b"$":
        length = int(line.strip())
        if length < 0:
            return first + line
        return first + line + stream.read(length + 2)

    raise AssertionError(f"unexpected RESP reply prefix: {first!r}")


class MiniRedisServerIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.server = MiniRedisTCPServer(("127.0.0.1", 0), store=HashTableStore())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.host, self.port = self.server.server_address

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_ping_set_get_and_exit(self) -> None:
        with socket.create_connection((self.host, self.port), timeout=2) as conn:
            stream = conn.makefile("rwb")
            stream.write(encode_command(b"PING"))
            stream.flush()
            self.assertEqual(read_reply(stream), b"+PONG\r\n")

            stream.write(encode_command(b"SET", b"team", b"three"))
            stream.flush()
            self.assertEqual(read_reply(stream), b"+OK\r\n")

            stream.write(encode_command(b"GET", b"team"))
            stream.flush()
            self.assertEqual(read_reply(stream), b"$5\r\nthree\r\n")

            stream.write(encode_command(b"EXIT"))
            stream.flush()
            self.assertEqual(read_reply(stream), b"+OK\r\n")

    def test_hello_three_returns_noproto_error(self) -> None:
        with socket.create_connection((self.host, self.port), timeout=2) as conn:
            stream = conn.makefile("rwb")
            stream.write(encode_command(b"HELLO", b"3"))
            stream.flush()

            self.assertEqual(read_reply(stream), b"-NOPROTO unsupported protocol version\r\n")

    def test_invalid_resp_returns_error(self) -> None:
        with socket.create_connection((self.host, self.port), timeout=2) as conn:
            conn.sendall(b"*1\r\n+PING\r\n")
            self.assertEqual(conn.recv(1024), b"-ERR expected bulk string\r\n")

    def test_null_bulk_string_returns_error(self) -> None:
        with socket.create_connection((self.host, self.port), timeout=2) as conn:
            conn.sendall(b"*1\r\n$-1\r\n")
            self.assertEqual(conn.recv(1024), b"-ERR null bulk string is not supported in commands\r\n")

    def test_truncated_bulk_data_returns_error(self) -> None:
        with socket.create_connection((self.host, self.port), timeout=2) as conn:
            conn.sendall(b"*1\r\n$4\r\nPI")
            conn.shutdown(socket.SHUT_WR)
            self.assertEqual(conn.recv(1024), b"-ERR incomplete bulk data\r\n")

    def test_invalid_bulk_terminator_returns_error(self) -> None:
        with socket.create_connection((self.host, self.port), timeout=2) as conn:
            conn.sendall(b"*1\r\n$4\r\nPINGxx")
            self.assertEqual(conn.recv(1024), b"-ERR invalid bulk terminator\r\n")

    def test_expire_command_expires_key(self) -> None:
        with socket.create_connection((self.host, self.port), timeout=2) as conn:
            stream = conn.makefile("rwb")
            stream.write(encode_command(b"SET", b"session", b"cached"))
            stream.write(encode_command(b"EXPIRE", b"session", b"0"))
            stream.write(encode_command(b"GET", b"session"))
            stream.flush()

            self.assertEqual(read_reply(stream), b"+OK\r\n")
            self.assertEqual(read_reply(stream), b":1\r\n")
            self.assertEqual(read_reply(stream), b"$-1\r\n")

    def test_persist_command_keeps_key_available(self) -> None:
        with socket.create_connection((self.host, self.port), timeout=2) as conn:
            stream = conn.makefile("rwb")
            stream.write(encode_command(b"SET", b"session", b"cached"))
            stream.write(encode_command(b"EXPIRE", b"session", b"10"))
            stream.write(encode_command(b"PERSIST", b"session"))
            stream.write(encode_command(b"TTL", b"session"))
            stream.write(encode_command(b"GET", b"session"))
            stream.flush()

            self.assertEqual(read_reply(stream), b"+OK\r\n")
            self.assertEqual(read_reply(stream), b":1\r\n")
            self.assertEqual(read_reply(stream), b":1\r\n")
            self.assertEqual(read_reply(stream), b":-1\r\n")
            self.assertEqual(read_reply(stream), b"$6\r\ncached\r\n")

    def test_ttl_command_returns_zero_for_missing_or_expired_key(self) -> None:
        with socket.create_connection((self.host, self.port), timeout=2) as conn:
            stream = conn.makefile("rwb")
            stream.write(encode_command(b"TTL", b"missing"))
            stream.write(encode_command(b"SET", b"session", b"cached"))
            stream.write(encode_command(b"EXPIRE", b"session", b"0"))
            stream.write(encode_command(b"TTL", b"session"))
            stream.flush()

            self.assertEqual(read_reply(stream), b":0\r\n")
            self.assertEqual(read_reply(stream), b"+OK\r\n")
            self.assertEqual(read_reply(stream), b":1\r\n")
            self.assertEqual(read_reply(stream), b":0\r\n")

    def test_info_command_includes_store_stats(self) -> None:
        with socket.create_connection((self.host, self.port), timeout=2) as conn:
            stream = conn.makefile("rwb")
            stream.write(encode_command(b"SET", b"team", b"three"))
            stream.write(encode_command(b"INFO"))
            stream.flush()

            self.assertEqual(read_reply(stream), b"+OK\r\n")
            info_reply = read_reply(stream)
            self.assertIn(b"# Store\r\n", info_reply)
            self.assertIn(b"keys:1\r\n", info_reply)
            self.assertIn(b"capacity:64\r\n", info_reply)
            self.assertIn(b"load_factor:", info_reply)

    def test_quit_closes_connection_after_ok(self) -> None:
        with socket.create_connection((self.host, self.port), timeout=2) as conn:
            stream = conn.makefile("rwb")
            stream.write(encode_command(b"QUIT"))
            stream.flush()

            self.assertEqual(read_reply(stream), b"+OK\r\n")
            self.assertEqual(read_reply(stream), b"")

    def test_server_restores_snapshot_after_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            snapshot_path = Path(temp_dir) / "mini_redis.snapshot"

            first_server = MiniRedisTCPServer(
                ("127.0.0.1", 0),
                store=HashTableStore(),
                snapshot_path=str(snapshot_path),
            )
            first_thread = threading.Thread(target=first_server.serve_forever, daemon=True)
            first_thread.start()
            first_host, first_port = first_server.server_address

            try:
                with socket.create_connection((first_host, first_port), timeout=2) as conn:
                    stream = conn.makefile("rwb")
                    stream.write(encode_command(b"SET", b"persisted", b"value"))
                    stream.flush()
                    self.assertEqual(read_reply(stream), b"+OK\r\n")
            finally:
                first_server.shutdown()
                first_server.server_close()
                first_thread.join(timeout=2)

            second_server = MiniRedisTCPServer(
                ("127.0.0.1", 0),
                store=HashTableStore(),
                snapshot_path=str(snapshot_path),
            )
            second_thread = threading.Thread(target=second_server.serve_forever, daemon=True)
            second_thread.start()
            second_host, second_port = second_server.server_address

            try:
                with socket.create_connection((second_host, second_port), timeout=2) as conn:
                    stream = conn.makefile("rwb")
                    stream.write(encode_command(b"GET", b"persisted"))
                    stream.flush()
                    self.assertEqual(read_reply(stream), b"$5\r\nvalue\r\n")
            finally:
                second_server.shutdown()
                second_server.server_close()
                second_thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
