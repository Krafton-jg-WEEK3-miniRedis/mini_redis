from __future__ import annotations

import base64
import json
import os
import tempfile
from pathlib import Path

from .storage import HashTableStore, SnapshotEntry


class SnapshotPersistence:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self, store: HashTableStore) -> int:
        if not self.path.exists():
            return 0

        entries: list[SnapshotEntry] = []
        with self.path.open("r", encoding="utf-8") as snapshot_file:
            for line_number, line in enumerate(snapshot_file, start=1):
                if not line.strip():
                    continue
                try:
                    payload = json.loads(line)
                    entries.append(
                        SnapshotEntry(
                            key=base64.b64decode(payload["key"]),
                            value=base64.b64decode(payload["value"]),
                            expires_at=payload["expires_at"],
                        )
                    )
                except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                    raise ValueError(
                        f"invalid snapshot entry at line {line_number}"
                    ) from exc

        return store.restore_snapshot(entries)

    def save(self, store: HashTableStore) -> int:
        entries = store.dump_snapshot()
        self.path.parent.mkdir(parents=True, exist_ok=True)

        fd, temp_path = tempfile.mkstemp(
            dir=str(self.path.parent),
            prefix=f"{self.path.name}.",
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as snapshot_file:
                for entry in entries:
                    json.dump(
                        {
                            "key": base64.b64encode(entry.key).decode("ascii"),
                            "value": base64.b64encode(entry.value).decode("ascii"),
                            "expires_at": entry.expires_at,
                        },
                        snapshot_file,
                        separators=(",", ":"),
                    )
                    snapshot_file.write("\n")
                snapshot_file.flush()
                os.fsync(snapshot_file.fileno())

            os.replace(temp_path, self.path)
        except Exception:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            raise

        return len(entries)
