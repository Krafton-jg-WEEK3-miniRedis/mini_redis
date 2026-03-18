import argparse
import itertools
import socketserver
from typing import Any

from mini_redis.storage import HashTableStore, KeyValueStore

STORE: KeyValueStore = HashTableStore()
CLIENT_IDS = itertools.count(1)


class RespError(Exception):
    pass


class MiniRedisHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        self.client_id = next(CLIENT_IDS)
        client = f"{self.client_address[0]}:{self.client_address[1]}"
        print(f"[connect] id={self.client_id} {client}", flush=True)

        try:
            while True:
                command = self.read_command()
                if command is None:
                    break

                should_close = self.execute(command)
                if should_close:
                    break
        except ConnectionResetError:
            pass
        finally:
            print(f"[disconnect] id={self.client_id} {client}", flush=True)

    def read_command(self) -> list[bytes] | None:
        first = self.rfile.readline()
        if not first:
            return None

        if first.startswith(b"*"):
            return self.read_resp_array(first)

        inline = first.strip()
        if not inline:
            return []
        return inline.split()

    def read_resp_array(self, first_line: bytes) -> list[bytes]:
        try:
            count = int(first_line[1:].strip())
        except ValueError as exc:
            raise RespError("invalid multibulk length") from exc

        parts: list[bytes] = []
        for _ in range(count):
            length_line = self.rfile.readline()
            if not length_line.startswith(b"$"):
                raise RespError("expected bulk string")

            try:
                length = int(length_line[1:].strip())
            except ValueError as exc:
                raise RespError("invalid bulk length") from exc

            if length < 0:
                parts.append(b"")
                continue

            data = self.rfile.read(length)
            trailing = self.rfile.read(2)
            if trailing != b"\r\n":
                raise RespError("invalid bulk terminator")
            parts.append(data)

        return parts

    def execute(self, command: list[bytes]) -> bool:
        if not command:
            self.write_error("empty command")
            return False

        name = command[0].upper()

        try:
            if name == b"PING":
                payload = command[1] if len(command) > 1 else None
                self.write_bulk(payload) if payload is not None else self.write_simple("PONG")
            elif name == b"ECHO":
                self.require_arity(command, 2)
                self.write_bulk(command[1])
            elif name == b"SET":
                self.require_arity(command, 3)
                STORE.set(command[1], command[2])
                self.write_simple("OK")
            elif name == b"GET":
                self.require_arity(command, 2)
                self.write_bulk(STORE.get(command[1]))
            elif name == b"DEL":
                self.require_min_arity(command, 2)
                self.write_integer(STORE.delete(command[1:]))
            elif name == b"EXPIRE":
                self.require_arity(command, 3)
                try:
                    seconds = int(command[2])
                except ValueError as exc:
                    raise RespError("value is not an integer or out of range") from exc
                self.write_integer(1 if STORE.expire(command[1], seconds) else 0)
            elif name == b"COMMAND":
                self.write_array([])
            elif name == b"CLIENT":
                self.execute_client(command)
            elif name == b"HELLO":
                self.execute_hello(command)
            elif name == b"INFO":
                self.write_bulk(
                    b"# Server\r\n"
                    b"redis_version:0.1.0\r\n"
                    b"redis_mode:standalone\r\n"
                    b"# Stats\r\n"
                    b"total_connections_received:1\r\n"
                )
            elif name == b"QUIT":
                self.write_simple("OK")
                return True
            else:
                self.write_error(f"unknown command '{command[0].decode('utf-8', errors='replace')}'")
        except RespError as exc:
            self.write_error(str(exc))

        return False

    def execute_client(self, command: list[bytes]) -> None:
        if len(command) >= 2 and command[1].upper() == b"SETINFO":
            self.write_simple("OK")
            return
        raise RespError("unsupported CLIENT subcommand")

    def execute_hello(self, command: list[bytes]) -> None:
        if len(command) > 2:
            raise RespError("unsupported HELLO arguments")
        if len(command) == 2 and command[1] not in {b"2", b"3"}:
            self.wfile.write(b"-NOPROTO unsupported protocol version\r\n")
            self.wfile.flush()
            return

        response = [
            b"server",
            b"redis",
            b"version",
            b"0.1.0",
            b"proto",
            2,
            b"id",
            self.client_id,
            b"mode",
            b"standalone",
            b"role",
            b"master",
            b"modules",
            [],
        ]
        self.write_array(response)

    def require_arity(self, command: list[bytes], expected: int) -> None:
        actual = len(command)
        if actual != expected:
            raise RespError(f"wrong number of arguments (expected {expected - 1})")

    def require_min_arity(self, command: list[bytes], minimum: int) -> None:
        actual = len(command)
        if actual < minimum:
            raise RespError(f"wrong number of arguments (expected at least {minimum - 1})")

    def write_simple(self, value: str) -> None:
        self.wfile.write(f"+{value}\r\n".encode())
        self.wfile.flush()

    def write_error(self, message: str) -> None:
        self.wfile.write(f"-ERR {message}\r\n".encode())
        self.wfile.flush()

    def write_integer(self, value: int) -> None:
        self.wfile.write(f":{value}\r\n".encode())
        self.wfile.flush()

    def write_bulk(self, value: bytes | None) -> None:
        if value is None:
            self.wfile.write(b"$-1\r\n")
        else:
            self.wfile.write(f"${len(value)}\r\n".encode() + value + b"\r\n")
        self.wfile.flush()

    def write_array(self, values: list[Any]) -> None:
        self.wfile.write(f"*{len(values)}\r\n".encode())
        for value in values:
            self.write_resp_value(value, flush=False)
        self.wfile.flush()

    def write_resp_value(self, value: Any, flush: bool = True) -> None:
        if isinstance(value, bytes):
            self.wfile.write(f"${len(value)}\r\n".encode() + value + b"\r\n")
        elif isinstance(value, str):
            encoded = value.encode()
            self.wfile.write(f"${len(encoded)}\r\n".encode() + encoded + b"\r\n")
        elif isinstance(value, int):
            self.wfile.write(f":{value}\r\n".encode())
        elif value is None:
            self.wfile.write(b"$-1\r\n")
        elif isinstance(value, list):
            self.wfile.write(f"*{len(value)}\r\n".encode())
            for item in value:
                self.write_resp_value(item, flush=False)
        else:
            raise TypeError(f"unsupported RESP value: {type(value)!r}")

        if flush:
            self.wfile.flush()


class ThreadedRedisServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main() -> None:
    parser = argparse.ArgumentParser(description="Tiny Redis-compatible TCP server")
    parser.add_argument("--host", default="0.0.0.0", help="bind host")
    parser.add_argument("--port", type=int, default=6379, help="bind port")
    args = parser.parse_args()

    with ThreadedRedisServer((args.host, args.port), MiniRedisHandler) as server:
        host, port = server.server_address
        print(f"mini redis listening on {host}:{port}", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
