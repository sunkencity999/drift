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
        """Compare two snapshots and explain what changed in plain English.

        Use this to answer 'what changed?' questions about OPERATIONAL STATE:
        ports opened/closed, packages installed/removed, services enabled/disabled,
        users added/removed, cron/launchd entries changed. Each argument is a
        snapshot id (int) or label (resolved to the latest with that label). Returns
        a structured diff (added/removed/changed per collector) AND a plain-English
        summary. For a no-args 'what changed recently?' use diff_latest instead.
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

    @mcp.tool(name="diff_latest")
    def diff_latest_tool() -> dict[str, Any]:
        """What changed on this box recently? No arguments needed.

        This is the tool to reach for when a user asks casually: 'what changed?',
        'were any packages installed or removed?', 'did any ports open or close?',
        'were any services or users added?', 'what's different since the last
        snapshot?' It diffs the two most recent snapshots and returns a structured
        diff plus a plain-English summary. Use `diff` instead when the user names
        specific snapshots or labels to compare.
        """
        rows = store.list_snapshots(limit=2)
        if len(rows) < 2:
            return {"ok": False, "error": f"need at least two snapshots to diff (have {len(rows)})"}
        latest_row = rows[0]  # newest first
        prev_row = rows[1]
        a = store.read_snapshot(prev_row["id"])
        b = store.read_snapshot(latest_row["id"])
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
    def list_snapshots(limit: int = 20) -> dict[str, Any]:
        """List recent snapshots the user could diff — newest first, with id/ts/label.

        Use this when a user asks 'what snapshots do I have?' or 'which two should I
        compare to see Tuesday's changes?' — then call `diff` on the chosen pair.
        """
        rows = store.list_snapshots(limit=limit)
        return {
            "count": len(rows),
            "snapshots": [
                {"id": r["id"], "ts": r["ts"], "label": r["label"]} for r in rows
            ],
        }

    @mcp.tool()
    def doctor() -> dict[str, Any]:
        """Is Drift healthy on this box? Reports which collectors are available
        (ports, services, packages, users, cron) and storage status. Use this for
        'is drift working?' / 'what can it watch here?' questions.
        """
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
