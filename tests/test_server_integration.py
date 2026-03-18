from __future__ import annotations

import socket
import threading
import unittest

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

    def test_invalid_resp_returns_error(self) -> None:
        with socket.create_connection((self.host, self.port), timeout=2) as conn:
            conn.sendall(b"*1\r\n+PING\r\n")
            self.assertEqual(conn.recv(1024), b"-ERR expected bulk string\r\n")

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


if __name__ == "__main__":
    unittest.main()
