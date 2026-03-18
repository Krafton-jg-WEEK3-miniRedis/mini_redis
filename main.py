import argparse

from mini_redis.server import serve


def main() -> None:
    parser = argparse.ArgumentParser(description="Tiny Redis-compatible TCP server")
    parser.add_argument("--host", default="0.0.0.0", help="bind host")
    parser.add_argument("--port", type=int, default=6379, help="bind port")
    parser.add_argument("--snapshot-path", help="optional snapshot file for persistence")
    args = parser.parse_args()
    serve(host=args.host, port=args.port, snapshot_path=args.snapshot_path)


if __name__ == "__main__":
    main()
