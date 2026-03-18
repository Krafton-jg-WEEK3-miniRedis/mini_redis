from __future__ import annotations

import socketserver
from typing import cast

from .persistence import SnapshotPersistence
from .resp import Reply, RespError, RespReader, RespWriter
from .router import CommandRouter, ServerStats
from .storage import HashTableStore, KeyValueStore


class MiniRedisHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        server = cast("MiniRedisTCPServer", self.server)
        client_id = server.stats.register_connection()
        client = f"{self.client_address[0]}:{self.client_address[1]}"
        reader = RespReader(self.rfile)
        writer = RespWriter(self.wfile)

        print(f"[connect] id={client_id} {client}", flush=True)

        try:
            while True:
                try:
                    command = reader.read_command()
                except RespError as exc:
                    writer.write_reply(Reply.error(str(exc)))
                    break

                if command is None:
                    break

                server.stats.mark_command_processed()
                result = server.router.dispatch(command, client_id)
                writer.write_reply(result.reply)
                if result.close_connection:
                    break
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            print(f"[disconnect] id={client_id} {client}", flush=True)


class MiniRedisTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        store: KeyValueStore | None = None,
        snapshot_path: str | None = None,
    ) -> None:
        self.stats = ServerStats()
        self.store = store or HashTableStore()
        self.snapshot_persistence = None
        if snapshot_path is not None:
            if not isinstance(self.store, HashTableStore):
                raise TypeError("snapshot persistence requires HashTableStore")
            self.snapshot_persistence = SnapshotPersistence(snapshot_path)
            restored = self.snapshot_persistence.load(self.store)
            print(f"loaded {restored} entries from snapshot {snapshot_path}", flush=True)
        self.router = CommandRouter(self.store, stats=self.stats)
        super().__init__(server_address, MiniRedisHandler)

    def server_close(self) -> None:
        if self.snapshot_persistence is not None:
            saved = self.snapshot_persistence.save(self.store)
            print(f"saved {saved} entries to snapshot {self.snapshot_persistence.path}", flush=True)
        super().server_close()


def serve(
    host: str = "0.0.0.0",
    port: int = 6379,
    store: KeyValueStore | None = None,
    snapshot_path: str | None = None,
) -> None:
    with MiniRedisTCPServer((host, port), store=store, snapshot_path=snapshot_path) as server:
        server_host, server_port = server.server_address
        print(f"mini redis listening on {server_host}:{server_port}", flush=True)
        server.serve_forever()
