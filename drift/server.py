"""The MCP server — the AI-facing surface over the store + differ.

FastMCP (stdio) server. Four tools, all read-only, all stateless:
  - diff(snapshot_a, snapshot_b) : structured diff + plain-English summary
  - latest()                      : the most recent snapshot
  - list_snapshots(limit)         : recent snapshots (id/ts/label)
  - doctor()                      : collector availability + storage health

Stateless: every tool reads from the store on each call. No in-memory state, no
warmup, no drift. The server process is spawned on demand by the AI client.
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from drift.config import SCHEMA_VERSION, Config
from drift.differ import diff, summarize
from drift.plugins import registry as _collector_registry
from drift.store import Store


def build_server(store: Store, config: Config) -> FastMCP:
    mcp = FastMCP("drift")

    @mcp.tool(name="diff")
    def diff_snapshots(snapshot_a: str, snapshot_b: str) -> dict[str, Any]:
        """Compare two snapshots and explain the changes.

        Each argument is a snapshot id (int) or label (resolved to the latest with
        that label). Returns a structured diff (added/removed/changed per collector)
        AND a plain-English summary string. Use this to answer 'what changed?'.
        """
        a = store.resolve_snapshot(snapshot_a)
        b = store.resolve_snapshot(snapshot_b)
        if a is None:
            return {"ok": False, "error": f"snapshot '{snapshot_a}' not found"}
        if b is None:
            return {"ok": False, "error": f"snapshot '{snapshot_b}' not found"}
        d = diff(a["payload"], b["payload"])
        label_a = a["label"] or f"#{a['id']}"
        label_b = b["label"] or f"#{b['id']}"
        return {
            "ok": True,
            "snapshot_a": {"id": a["id"], "label": a["label"], "ts": a["ts"]},
            "snapshot_b": {"id": b["id"], "label": b["label"], "ts": b["ts"]},
            "diff": d,
            "summary": summarize(d, label_a, label_b),
        }

    @mcp.tool()
    def latest() -> dict[str, Any]:
        """The most recent snapshot (id, ts, label, full payload)."""
        snap = store.latest()
        if snap is None:
            return {"snapshot": None, "note": "no snapshots yet"}
        return {
            "id": snap["id"],
            "ts": snap["ts"],
            "label": snap["label"],
            "payload": snap["payload"],
        }

    @mcp.tool()
    def list_snapshots(limit: int = 20) -> dict[str, Any]:
        """Recent snapshots, newest first. Each: id, ts, label."""
        rows = store.list_snapshots(limit=limit)
        return {
            "count": len(rows),
            "snapshots": [
                {"id": r["id"], "ts": r["ts"], "label": r["label"]} for r in rows
            ],
        }

    @mcp.tool()
    def doctor() -> dict[str, Any]:
        """Report Drift's health: collector availability + storage status."""
        collectors = []
        for c in _collector_registry.all():
            try:
                avail = bool(c.is_available())
            except Exception:  # noqa: BLE001
                avail = False
            collectors.append({"name": c.name, "available": avail})
        store_ok = True
        n = 0
        try:
            n = store.count()
        except Exception:  # noqa: BLE001
            store_ok = False
        return {
            "ok": store_ok,
            "version": _version(),
            "store": {
                "path": str(store.config.db_path),
                "schema_version": SCHEMA_VERSION,
                "total_snapshots": n,
                "ok": store_ok,
            },
            "collectors": collectors,
        }

    return mcp


def _version() -> str:
    from drift import __version__

    return __version__


def main() -> None:
    cfg = Config().resolve()
    cfg.ensure_dirs()
    store = Store(cfg)
    store.open()
    mcp = build_server(store, cfg)
    mcp.run()


if __name__ == "__main__":
    main()
