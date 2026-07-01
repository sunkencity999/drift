"""SQLite-backed snapshot store.

Single writer (the snapshotter daemon or a manual `drift snap`), many readers (the
MCP server). Schema: one row per snapshot, payload as JSON. The key behavior beyond
read/write is **count-based prune with a labeled-snapshot exemption**: keep the most
recent `retention_snapshots` unlabeled snapshots, never prune labeled (manual) ones.
"""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any

from drift.config import SCHEMA_VERSION, Config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL,
    applied_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS snapshots (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts      REAL    NOT NULL,
    label   TEXT,
    payload TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_snapshots_ts ON snapshots (ts DESC);
CREATE INDEX IF NOT EXISTS idx_snapshots_label ON snapshots (label);
"""


class Store:
    def __init__(self, config: Config):
        self.config = config
        self._cx: sqlite3.Connection | None = None

    def open(self) -> Store:
        if self._cx is not None:
            return self
        self.config.ensure_dirs()
        assert self.config.db_path is not None
        cx = sqlite3.connect(self.config.db_path, check_same_thread=False)
        cx.row_factory = sqlite3.Row
        cx.executescript(_SCHEMA)
        if cx.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0] == 0:
            cx.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                (SCHEMA_VERSION, time.time()),
            )
        cx.commit()
        self._cx = cx
        return self

    def close(self) -> None:
        if self._cx is not None:
            self._cx.commit()
            self._cx.close()
            self._cx = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._cx is None:
            raise RuntimeError("Store is not open; call open() first")
        return self._cx

    # ---- writes -----------------------------------------------------------

    def write_snapshot(self, payload: dict[str, Any], label: str | None = None) -> int:
        ts = time.time()
        blob = json.dumps(payload, default=str, sort_keys=True)
        cur = self.conn.execute(
            "INSERT INTO snapshots (ts, label, payload) VALUES (?, ?, ?)",
            (ts, label, blob),
        )
        self.conn.commit()
        # Auto-prune after each write so storage stays bounded over long unattended runs.
        self.prune()
        return cur.lastrowid

    def prune(self) -> int:
        """Keep the most recent `retention_snapshots` unlabeled snapshots; delete older
        unlabeled rows. Labeled (manual) snapshots are exempt — never pruned.

        Returns the number of rows deleted.
        """
        keep = self.config.retention_snapshots
        # Find the oldest unlabeled snapshot we want to KEEP (the keep-th newest,
        # offset keep-1). Anything unlabeled older than it gets deleted. Labeled
        # rows are exempt from both ranking and delete. Using id (monotonic with
        # insertion) avoids timestamp-collision edge cases.
        threshold = self.conn.execute(
            """
            SELECT id FROM snapshots
            WHERE label IS NULL
            ORDER BY id DESC
            LIMIT 1 OFFSET ?
            """,
            (keep - 1,),
        ).fetchone()
        if threshold is None:
            return 0  # fewer than `keep` unlabeled rows → nothing to prune
        cur = self.conn.execute(
            """
            DELETE FROM snapshots
            WHERE label IS NULL AND id < ?
            """,
            (threshold["id"],),
        )
        self.conn.commit()
        return cur.rowcount

    # ---- reads ------------------------------------------------------------

    def read_snapshot(self, snapshot_id: int) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT id, ts, label, payload FROM snapshots WHERE id = ?",
            (snapshot_id,),
        ).fetchone()
        return _row_to_dict(row) if row else None

    def list_snapshots(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT id, ts, label, payload FROM snapshots ORDER BY ts DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def latest(self) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT id, ts, label, payload FROM snapshots ORDER BY ts DESC LIMIT 1"
        ).fetchone()
        return _row_to_dict(row) if row else None

    def resolve_snapshot(self, id_or_label: str | int) -> dict[str, Any] | None:
        """Resolve a snapshot by integer id or by label (latest with that label)."""
        # try as int id first
        try:
            sid = int(id_or_label)
            got = self.read_snapshot(sid)
            if got is not None:
                return got
        except (ValueError, TypeError):
            pass
        # fall back to label → latest snapshot with that label
        row = self.conn.execute(
            "SELECT id, ts, label, payload FROM snapshots WHERE label = ? "
            "ORDER BY ts DESC LIMIT 1",
            (str(id_or_label),),
        ).fetchone()
        return _row_to_dict(row) if row else None

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "ts": row["ts"],
        "label": row["label"],
        "payload": json.loads(row["payload"]),
    }
