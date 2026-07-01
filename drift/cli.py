"""Drift command-line interface.

Subcommands:
  snap         — capture one snapshot now (--label optional; manual snapshots are
                 exempt from prune)
  diff A B     — compare two snapshots (by id or label); prints English summary,
                 or structured JSON with --json
  list         — recent snapshots
  snapshotter  — run the auto-snapshot daemon (foreground; supervisors manage this)
  doctor       — report collector availability + storage health
  status       — show the most recent snapshot

Exit codes: 0 ok · 1 diff/error · 2 missing-deps
"""

from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import threading
import time
from collections.abc import Sequence

from drift.config import Config
from drift.differ import diff, summarize
from drift.plugins import registry as _collector_registry
from drift.snapshot import snapshot
from drift.store import Store

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_MISSING_DEPS = 2


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="drift",
        description="A diff for live systems — snapshot operational state, ask what changed.",
    )
    p.add_argument("-v", "--verbose", action="count", default=0, help="-v info, -vv debug")
    sub = p.add_subparsers(dest="command", required=True)

    sp_snap = sub.add_parser("snap", help="capture a snapshot now")
    sp_snap.add_argument(
        "--label", default=None,
        help="label for the snapshot (manual; exempt from prune)",
    )

    sp_diff = sub.add_parser("diff", help="compare two snapshots")
    sp_diff.add_argument("snapshot_a")
    sp_diff.add_argument("snapshot_b")
    sp_diff.add_argument(
        "--json", action="store_true",
        help="print structured JSON instead of English",
    )

    sub.add_parser("list", help="list recent snapshots")
    sub.add_parser("snapshotter", help="run the auto-snapshot daemon (foreground)")
    sub.add_parser("doctor", help="report collector availability + storage health")
    sub.add_parser("status", help="show the most recent snapshot")
    return p


def _config_from_env() -> Config:
    cfg = Config().resolve()
    cfg.ensure_dirs()
    return cfg


def _open_store(cfg: Config) -> Store:
    store = Store(cfg)
    store.open()
    return store


def cmd_snap(cfg: Config, label: str | None = None) -> int:
    store = _open_store(cfg)
    try:
        doc = snapshot(_collector_registry.all(), label=label)
        sid = store.write_snapshot(doc, label=label)
        # status goes to stderr so stdout stays clean for piping/JSON
        print(f"snapshot #{sid} captured ({label or 'auto'}) -> {cfg.db_path}", file=sys.stderr)
    finally:
        store.close()
    return EXIT_OK


def cmd_diff(cfg: Config, a: str, b: str, as_json: bool = False) -> int:
    store = _open_store(cfg)
    try:
        sa = store.resolve_snapshot(a)
        sb = store.resolve_snapshot(b)
        if sa is None:
            print(f"snapshot '{a}' not found", file=sys.stderr)
            return EXIT_ERROR
        if sb is None:
            print(f"snapshot '{b}' not found", file=sys.stderr)
            return EXIT_ERROR
        d = diff(sa["payload"], sb["payload"])
        label_a = sa["label"] or f"#{sa['id']}"
        label_b = sb["label"] or f"#{sb['id']}"
        summary = summarize(d, label_a, label_b)
        if as_json:
            print(json.dumps({
                "snapshot_a": {"id": sa["id"], "label": sa["label"], "ts": sa["ts"]},
                "snapshot_b": {"id": sb["id"], "label": sb["label"], "ts": sb["ts"]},
                "diff": d,
                "summary": summary,
            }, indent=2, default=str))
        else:
            print(summary)
    finally:
        store.close()
    return EXIT_OK


def cmd_list(cfg: Config) -> int:
    store = _open_store(cfg)
    try:
        rows = store.list_snapshots(limit=50)
        if not rows:
            print("no snapshots yet — run `drift snap`")
            return EXIT_OK
        for r in rows:
            age = time.time() - r["ts"]
            label = r["label"] or "auto"
            print(f"#{r['id']:<4} {age:>7.0f}s ago  {label}")
    finally:
        store.close()
    return EXIT_OK


def cmd_status(cfg: Config) -> int:
    store = _open_store(cfg)
    try:
        snap = store.latest()
        if snap is None:
            print("no snapshots yet")
            return EXIT_OK
        age = time.time() - snap["ts"]
        label = snap["label"] or "auto"
        collectors = list(snap["payload"].get("collectors", {}).keys())
        print(f"latest: #{snap['id']} ({label}), {age:.0f}s ago")
        print(f"  collectors: {', '.join(collectors) or '(none)'}")
        errs = snap["payload"].get("errors", [])
        if errs:
            print(f"  errors: {errs}")
    finally:
        store.close()
    return EXIT_OK


def cmd_doctor(cfg: Config) -> int:
    print(f"Drift v{_version()}")
    print(f"  data dir : {cfg.data_dir}")
    print(f"  db path  : {cfg.db_path}")
    print(f"  interval : {cfg.interval_hours}h · retention: {cfg.retention_snapshots} snapshots")
    print()
    print("Collectors:")
    for c in _collector_registry.all():
        try:
            avail = bool(c.is_available())
        except Exception:  # noqa: BLE001
            avail = False
        mark = "✓" if avail else "✗"
        state = "available" if avail else "not available (will be skipped)"
        print(f"  {mark} {c.name:<12} {state}")
    print()
    try:
        store = _open_store(cfg)
        n = store.count()
        store.close()
        print(f"Storage: OK ({n} snapshots)")
    except Exception as exc:  # noqa: BLE001
        print(f"Storage: ERROR — {exc}")
        return EXIT_ERROR
    return EXIT_OK


def cmd_snapshotter(cfg: Config) -> int:
    stop = threading.Event()

    def on_signal(signum, frame):  # noqa: ANN001
        log.info("received signal %d, stopping after current cycle", signum)
        stop.set()

    try:
        signal.signal(signal.SIGTERM, on_signal)
        signal.signal(signal.SIGINT, on_signal)
    except (ValueError, OSError):
        pass  # not main thread

    log.info("snapshotter starting; interval=%.1fh", cfg.interval_hours)
    store = _open_store(cfg)
    try:
        while not stop.is_set():
            doc = snapshot(_collector_registry.all(), label=None)
            store.write_snapshot(doc, label=None)  # auto-prune runs inside write
            log.info("snapshot captured; %d total", store.count())
            if stop.wait(cfg.interval_hours * 3600):
                break
    finally:
        store.close()
    log.info("snapshotter stopped")
    return EXIT_OK


def _version() -> str:
    from drift import __version__

    return __version__


log = logging.getLogger("drift.snapshotter")


_DISPATCH = {
    "snap": lambda cfg, args: cmd_snap(cfg, args.label),
    "diff": lambda cfg, args: cmd_diff(cfg, args.snapshot_a, args.snapshot_b, args.json),
    "list": lambda cfg, args: cmd_list(cfg),
    "snapshotter": lambda cfg, args: cmd_snapshotter(cfg),
    "doctor": lambda cfg, args: cmd_doctor(cfg),
    "status": lambda cfg, args: cmd_status(cfg),
}


def run(argv: Sequence[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        code = exc.code
        return code if isinstance(code, int) else EXIT_MISSING_DEPS
    level = logging.WARNING
    if args.verbose == 1:
        level = logging.INFO
    elif args.verbose >= 2:
        level = logging.DEBUG
    logging.basicConfig(level=level, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    cfg = _config_from_env()
    handler = _DISPATCH.get(args.command)
    if handler is None:
        parser.print_help()
        return EXIT_MISSING_DEPS
    return handler(cfg, args)


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
