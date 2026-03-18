from __future__ import annotations

import argparse
import shlex
import socket
import sys
from dataclasses import dataclass
from typing import BinaryIO, Callable, Sequence, TextIO


WELCOME_LINES = (
    "Mini Redis CLI에 연결되었습니다.",
    "처음이면 `?` 를 입력해 사용 가능한 명령어를 확인하세요.",
    "예시: SET name gracia",
)
HELP_LINES = (
    "사용 가능한 명령어:",
    "PING [message], ECHO <message>",
    "SET <key> <value>, GET <key>, DEL <key> [key ...]",
    "EXPIRE <key> <seconds>, INFO, HELLO [2|3], COMMAND",
    "CLIENT SETINFO, QUIT, EXIT, ?, HELP",
)
EMPTY_INPUT_MESSAGE = "입력된 명령이 없습니다. `?` 를 입력하면 도움말을 볼 수 있습니다."
PROMPT = "[5조] mini-redis > "


class CliError(Exception):
    pass


@dataclass(slots=True)
class ClientReply:
    kind: str
    value: object = None
    error_code: str = "ERR"


def _read_line(source: BinaryIO) -> str:
    line = source.readline()
    if not line:
        raise CliError("server closed the connection")
    return line.decode("utf-8", errors="replace").rstrip("\r\n")


def _split_error(message: str) -> tuple[str, str]:
    if " " not in message:
        return "ERR", message
    code, detail = message.split(" ", 1)
    return code, detail


def encode_command(parts: Sequence[str]) -> bytes:
    encoded_parts = [part.encode("utf-8") for part in parts]
    payload = [f"*{len(encoded_parts)}\r\n".encode("ascii")]
    for part in encoded_parts:
        payload.append(f"${len(part)}\r\n".encode("ascii"))
        payload.append(part + b"\r\n")
    return b"".join(payload)


def read_reply(source: BinaryIO) -> ClientReply:
    prefix = source.read(1)
    if not prefix:
        raise CliError("server closed the connection")

    if prefix == b"+":
        return ClientReply("simple", _read_line(source))

    if prefix == b"-":
        message = _read_line(source)
        code, detail = _split_error(message)
        return ClientReply("error", detail, error_code=code)

    if prefix == b":":
        return ClientReply("integer", int(_read_line(source)))

    if prefix == b"$":
        length = int(_read_line(source))
        if length < 0:
            return ClientReply("bulk", None)
        data = source.read(length)
        if source.read(2) != b"\r\n":
            raise CliError("invalid bulk terminator")
        return ClientReply("bulk", data)

    if prefix == b"*":
        count = int(_read_line(source))
        items = [read_reply(source) for _ in range(count)]
        return ClientReply("array", items)

    raise CliError(f"unexpected RESP reply prefix: {prefix!r}")


def send_command(stream: BinaryIO, parts: Sequence[str]) -> ClientReply:
    stream.write(encode_command(parts))
    stream.flush()
    return read_reply(stream)


def format_reply(reply: ClientReply) -> str:
    if reply.kind == "simple":
        return str(reply.value)

    if reply.kind == "bulk":
        if reply.value is None:
            return "(nil)"
        return bytes(reply.value).decode("utf-8", errors="replace")

    if reply.kind == "integer":
        return str(reply.value)

    if reply.kind == "error":
        return f"(error) {reply.error_code} {reply.value}"

    if reply.kind == "array":
        items: list[ClientReply] = list(reply.value)
        if not items:
            return "(empty array)"
        return "\n".join(f"{index}. {format_reply(item)}" for index, item in enumerate(items, start=1))

    raise CliError(f"unsupported reply kind: {reply.kind!r}")


def run_interactive(
    host: str,
    port: int,
    *,
    input_func: Callable[[str], str] = input,
    out: TextIO = sys.stdout,
) -> int:
    with socket.create_connection((host, port), timeout=5) as conn:
        stream = conn.makefile("rwb")

        for line in WELCOME_LINES:
            print(line, file=out)

        while True:
            try:
                raw = input_func(PROMPT)
            except EOFError:
                print(file=out)
                return 0
            except KeyboardInterrupt:
                print("\n종료합니다.", file=out)
                return 0

            stripped = raw.strip()

            if not stripped:
                print(EMPTY_INPUT_MESSAGE, file=out)
                continue

            if stripped in {"?", "HELP", "help"}:
                for line in HELP_LINES:
                    print(line, file=out)
                continue

            parts = shlex.split(raw)
            reply = send_command(stream, parts)
            print(format_reply(reply), file=out)

            if parts[0].upper() in {"QUIT", "EXIT"}:
                return 0


def run_once(host: str, port: int, command: Sequence[str], *, out: TextIO = sys.stdout) -> int:
    with socket.create_connection((host, port), timeout=5) as conn:
        stream = conn.makefile("rwb")
        reply = send_command(stream, command)
        print(format_reply(reply), file=out)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Mini Redis CLI client")
    parser.add_argument("--host", default="127.0.0.1", help="server host")
    parser.add_argument("--port", type=int, default=6379, help="server port")
    parser.add_argument("command", nargs="*", help="command to execute")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command:
            return run_once(args.host, args.port, args.command)
        return run_interactive(args.host, args.port)
    except (CliError, OSError, ValueError) as exc:
        print(f"CLI error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
