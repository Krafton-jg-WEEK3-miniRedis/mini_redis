from __future__ import annotations

import itertools
import threading
from dataclasses import dataclass

from .resp import Reply
from .storage import KeyValueStore


@dataclass(slots=True)
class RouteResult:
    reply: Reply
    close_connection: bool = False


class ServerStats:
    def __init__(self) -> None:
        self._client_ids = itertools.count(1)
        self._total_connections = 0
        self._total_commands = 0
        self._lock = threading.Lock()

    def register_connection(self) -> int:
        with self._lock:
            self._total_connections += 1
            return next(self._client_ids)

    def mark_command_processed(self) -> None:
        with self._lock:
            self._total_commands += 1

    def get_stats(self) -> tuple[int, int]:
        with self._lock:
            return self._total_connections, self._total_commands


class CommandRouter:
    def __init__(self, store: KeyValueStore, stats: ServerStats | None = None) -> None:
        self._store = store
        self._stats = stats or ServerStats()

    def dispatch(self, command: list[bytes], client_id: int) -> RouteResult:
        if not command:
            return RouteResult(Reply.error("empty command"))

        name = command[0].upper()

        try:
            if name == b"PING":
                self._require_range_arity(command, minimum=1, maximum=2)
                payload = command[1] if len(command) == 2 else None
                return RouteResult(Reply.bulk(payload) if payload is not None else Reply.simple("PONG"))

            if name == b"ECHO":
                self._require_arity(command, 2)
                return RouteResult(Reply.bulk(command[1]))

            if name == b"SET":
                self._require_arity(command, 3)
                self._store.set(command[1], command[2])
                return RouteResult(Reply.simple("OK"))

            if name == b"GET":
                self._require_arity(command, 2)
                return RouteResult(Reply.bulk(self._store.get(command[1])))

            if name == b"DEL":
                self._require_min_arity(command, 2)
                deleted = self._store.delete(command[1:])
                return RouteResult(Reply.integer(deleted))

            if name == b"EXPIRE":
                self._require_arity(command, 3)
                try:
                    seconds = int(command[2])
                except ValueError:
                    return RouteResult(Reply.error("value is not an integer or out of range"))

                try:
                    updated = self._store.expire(command[1], seconds)
                except ValueError as exc:
                    return RouteResult(Reply.error(str(exc)))

                return RouteResult(Reply.integer(1 if updated else 0))

            if name == b"TTL":
                self._require_arity(command, 2)
                return RouteResult(Reply.integer(self._store.ttl(command[1])))

            if name == b"PERSIST":
                self._require_arity(command, 2)
                restored = self._store.persist(command[1])
                return RouteResult(Reply.integer(1 if restored else 0))

            if name == b"COMMAND":
                return RouteResult(Reply.array([]))

            if name == b"CLIENT":
                return RouteResult(self._handle_client(command))

            if name == b"HELLO":
                return RouteResult(self._handle_hello(command, client_id))

            if name == b"INFO":
                return RouteResult(Reply.bulk(self._build_info()))

            if name in {b"QUIT", b"EXIT"}:
                self._require_arity(command, 1)
                return RouteResult(Reply.simple("OK"), close_connection=True)
        except ValueError as exc:
            return RouteResult(Reply.error(str(exc)))

        decoded = command[0].decode("utf-8", errors="replace")
        return RouteResult(Reply.error(f"unknown command '{decoded}'"))

    def _handle_client(self, command: list[bytes]) -> Reply:
        if len(command) >= 2 and command[1].upper() == b"SETINFO":
            return Reply.simple("OK")
        return Reply.error("unsupported CLIENT subcommand")

    def _handle_hello(self, command: list[bytes], client_id: int) -> Reply:
        if len(command) > 2:
            return Reply.error("unsupported HELLO arguments")
        if len(command) == 2 and command[1] not in {b"2", b"3"}:
            return Reply.error("unsupported protocol version", code="NOPROTO")

        return Reply.array(
            [
                b"server",
                b"redis",
                b"version",
                b"0.2.0",
                b"proto",
                2,
                b"id",
                client_id,
                b"mode",
                b"standalone",
                b"role",
                b"master",
                b"modules",
                [],
            ]
        )

    def _build_info(self) -> bytes:
        total_connections, total_commands = self._stats.get_stats()
        store_stats = self._store.get_stats()
        return (
            b"# Server\r\n"
            b"redis_version:0.2.0\r\n"
            b"redis_mode:standalone\r\n"
            b"# Stats\r\n"
            + f"total_connections_received:{total_connections}\r\n".encode()
            + f"total_commands_processed:{total_commands}\r\n".encode()
            + b"# Store\r\n"
            + f"keys:{store_stats.size}\r\n".encode()
            + f"capacity:{store_stats.capacity}\r\n".encode()
            + f"load_factor:{store_stats.load_factor:.6f}\r\n".encode()
            + f"resize_count:{store_stats.resize_count}\r\n".encode()
            + f"expired_removed_count:{store_stats.expired_removed_count}\r\n".encode()
        )

    def _require_arity(self, command: list[bytes], expected: int) -> None:
        if len(command) != expected:
            raise ValueError(f"wrong number of arguments (expected {expected - 1})")

    def _require_min_arity(self, command: list[bytes], minimum: int) -> None:
        if len(command) < minimum:
            raise ValueError(f"wrong number of arguments (expected at least {minimum - 1})")

    def _require_range_arity(self, command: list[bytes], minimum: int, maximum: int) -> None:
        actual = len(command)
        if actual < minimum or actual > maximum:
            raise ValueError(
                f"wrong number of arguments (expected between {minimum - 1} and {maximum - 1})"
            )
