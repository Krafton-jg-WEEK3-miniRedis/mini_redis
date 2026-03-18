from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter
from pathlib import Path
from time import perf_counter
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from mini_redis.cli import encode_command


async def read_resp_line(reader: asyncio.StreamReader) -> bytes:
    line = await reader.readline()
    if not line:
        raise ConnectionError("server closed the connection")
    return line.rstrip(b"\r\n")


async def read_resp_value(reader: asyncio.StreamReader) -> Any:
    prefix = await reader.readexactly(1)

    if prefix == b"+":
        return {"kind": "simple", "value": (await read_resp_line(reader)).decode("utf-8", errors="replace")}

    if prefix == b"-":
        message = (await read_resp_line(reader)).decode("utf-8", errors="replace")
        return {"kind": "error", "value": message}

    if prefix == b":":
        return {"kind": "integer", "value": int(await read_resp_line(reader))}

    if prefix == b"$":
        length = int(await read_resp_line(reader))
        if length < 0:
            return {"kind": "bulk", "value": None}
        payload = await reader.readexactly(length)
        trailer = await reader.readexactly(2)
        if trailer != b"\r\n":
            raise ValueError("invalid bulk terminator")
        return {"kind": "bulk", "value": payload.decode("utf-8", errors="replace")}

    if prefix == b"*":
        count = int(await read_resp_line(reader))
        return {"kind": "array", "value": [await read_resp_value(reader) for _ in range(count)]}

    raise ValueError(f"unexpected RESP reply prefix: {prefix!r}")


def build_command(args: argparse.Namespace, index: int) -> list[str]:
    if args.command == "PING":
        return ["PING"]
    if args.command == "INFO":
        return ["INFO"]
    if args.command == "HELLO":
        return ["HELLO", args.hello_version]
    if args.command == "SET":
        return ["SET", f"{args.key_prefix}:{index}", f"{args.value_prefix}:{index}"]
    if args.command == "GET":
        return ["GET", f"{args.key_prefix}:{index}"]
    if args.command == "DEL":
        return ["DEL", f"{args.key_prefix}:{index}"]
    raise ValueError(f"unsupported command: {args.command}")


async def run_one(
    index: int,
    args: argparse.Namespace,
    semaphore: asyncio.Semaphore,
    started: asyncio.Event,
) -> tuple[bool, str]:
    async with semaphore:
        await started.wait()
        writer: asyncio.StreamWriter | None = None
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(args.host, args.port),
                timeout=args.connect_timeout,
            )
            command = build_command(args, index)
            writer.write(encode_command(command))
            await writer.drain()
            reply = await asyncio.wait_for(read_resp_value(reader), timeout=args.read_timeout)

            if args.hold_seconds > 0:
                await asyncio.sleep(args.hold_seconds)

            if reply["kind"] == "error":
                return False, f"server_error:{reply['value']}"
            return True, reply["kind"]
        except Exception as exc:
            return False, f"{type(exc).__name__}: {exc}"
        finally:
            if writer is not None:
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass


async def main_async(args: argparse.Namespace) -> int:
    semaphore = asyncio.Semaphore(args.concurrency)
    started = asyncio.Event()

    tasks = [
        asyncio.create_task(run_one(index, args, semaphore, started))
        for index in range(args.requests)
    ]

    begin = perf_counter()
    started.set()
    results = await asyncio.gather(*tasks)
    elapsed = perf_counter() - begin

    success_count = 0
    failures = Counter()
    reply_kinds = Counter()

    for ok, detail in results:
        if ok:
            success_count += 1
            reply_kinds[detail] += 1
        else:
            failures[detail] += 1

    print("Mini Redis TCP stress test")
    print(f"target={args.host}:{args.port}")
    print(f"command={args.command}")
    print(f"requests={args.requests}")
    print(f"concurrency={args.concurrency}")
    print(f"hold_seconds={args.hold_seconds}")
    print(f"elapsed={elapsed:.3f}s")
    print(f"throughput={args.requests / elapsed:.2f} req/s" if elapsed > 0 else "throughput=inf")
    print(f"success={success_count}")
    print(f"failure={args.requests - success_count}")

    if reply_kinds:
        print("reply_kinds:")
        for kind, count in reply_kinds.most_common():
            print(f"  {kind}: {count}")

    if failures:
        print("failures:")
        for detail, count in failures.most_common(10):
            print(f"  {detail}: {count}")

    return 0 if success_count == args.requests else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stress Mini Redis with many concurrent TCP requests.")
    parser.add_argument("--host", default="127.0.0.1", help="Mini Redis host")
    parser.add_argument("--port", type=int, default=6379, help="Mini Redis port")
    parser.add_argument("--requests", type=int, default=10_000, help="Total request count")
    parser.add_argument(
        "--concurrency",
        type=int,
        default=2_000,
        help="Maximum number of simultaneous client coroutines",
    )
    parser.add_argument(
        "--command",
        choices=["PING", "SET", "GET", "DEL", "INFO", "HELLO"],
        default="PING",
        help="Command sent by each client",
    )
    parser.add_argument(
        "--hold-seconds",
        type=float,
        default=0.0,
        help="Keep each connection open after the first reply to increase pressure",
    )
    parser.add_argument("--key-prefix", default="stress:key", help="Key prefix for SET/GET/DEL")
    parser.add_argument("--value-prefix", default="stress:value", help="Value prefix for SET")
    parser.add_argument("--hello-version", default="2", help="HELLO protocol version")
    parser.add_argument("--connect-timeout", type=float, default=3.0, help="TCP connect timeout")
    parser.add_argument("--read-timeout", type=float, default=3.0, help="Reply read timeout")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.requests <= 0:
        raise SystemExit("--requests must be greater than zero")
    if args.concurrency <= 0:
        raise SystemExit("--concurrency must be greater than zero")
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
