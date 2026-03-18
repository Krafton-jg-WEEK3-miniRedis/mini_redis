from __future__ import annotations

from dataclasses import dataclass
from typing import Any, BinaryIO


class RespError(Exception):
    pass


@dataclass(slots=True)
class Reply:
    kind: str
    value: Any = None
    error_code: str = "ERR"

    @classmethod
    def simple(cls, value: str) -> "Reply":
        return cls("simple", value)

    @classmethod
    def bulk(cls, value: bytes | None) -> "Reply":
        return cls("bulk", value)

    @classmethod
    def integer(cls, value: int) -> "Reply":
        return cls("integer", value)

    @classmethod
    def array(cls, value: list[Any]) -> "Reply":
        return cls("array", value)

    @classmethod
    def error(cls, message: str, code: str = "ERR") -> "Reply":
        return cls("error", message, error_code=code)


class RespReader:
    def __init__(self, source: BinaryIO) -> None:
        self._source = source

    def read_command(self) -> list[bytes] | None:
        first = self._source.readline()
        if not first:
            return None

        if first.startswith(b"*"):
            return self._read_resp_array(first)

        inline = first.strip()
        if not inline:
            return []
        return inline.split()

    def _read_resp_array(self, first_line: bytes) -> list[bytes]:
        try:
            count = int(first_line[1:].strip())
        except ValueError as exc:
            raise RespError("invalid multibulk length") from exc

        parts: list[bytes] = []
        for _ in range(count):
            length_line = self._source.readline()
            if not length_line.startswith(b"$"):
                raise RespError("expected bulk string")

            try:
                length = int(length_line[1:].strip())
            except ValueError as exc:
                raise RespError("invalid bulk length") from exc

            if length < 0:
                parts.append(b"")
                continue

            data = self._source.read(length)
            trailing = self._source.read(2)
            if trailing != b"\r\n":
                raise RespError("invalid bulk terminator")
            parts.append(data)

        return parts


class RespWriter:
    def __init__(self, sink: BinaryIO) -> None:
        self._sink = sink

    def write_reply(self, reply: Reply) -> None:
        if reply.kind == "simple":
            self._sink.write(f"+{reply.value}\r\n".encode())
        elif reply.kind == "error":
            self._sink.write(f"-{reply.error_code} {reply.value}\r\n".encode())
        elif reply.kind == "integer":
            self._sink.write(f":{reply.value}\r\n".encode())
        elif reply.kind == "bulk":
            self._write_bulk(reply.value)
        elif reply.kind == "array":
            self._write_array(reply.value)
        else:
            raise TypeError(f"unsupported reply kind: {reply.kind!r}")

        self._sink.flush()

    def _write_bulk(self, value: bytes | None) -> None:
        if value is None:
            self._sink.write(b"$-1\r\n")
            return

        self._sink.write(f"${len(value)}\r\n".encode() + value + b"\r\n")

    def _write_array(self, values: list[Any]) -> None:
        self._sink.write(f"*{len(values)}\r\n".encode())
        for value in values:
            self._write_value(value)

    def _write_value(self, value: Any) -> None:
        if isinstance(value, bytes):
            self._sink.write(f"${len(value)}\r\n".encode() + value + b"\r\n")
        elif isinstance(value, str):
            encoded = value.encode()
            self._sink.write(f"${len(encoded)}\r\n".encode() + encoded + b"\r\n")
        elif isinstance(value, int):
            self._sink.write(f":{value}\r\n".encode())
        elif value is None:
            self._sink.write(b"$-1\r\n")
        elif isinstance(value, list):
            self._write_array(value)
        else:
            raise TypeError(f"unsupported RESP value: {type(value)!r}")
