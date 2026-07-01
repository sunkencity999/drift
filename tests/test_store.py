"""Tests for the snapshot store. Pure I/O: write/read snapshots, count-based prune."""

import sqlite3
import time

from drift.config import SCHEMA_VERSION
from drift.store import Store


def test_store_creates_schema_and_version(config):
    s = Store(config)
    s.open()
    with sqlite3.connect(config.db_path) as cx:
        names = {r[0] for r in cx.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "snapshots" in names
    assert "schema_version" in names
    s.close()


def test_write_and_read_snapshot(config):
    s = Store(config)
    s.open()
    payload = {"collectors": {"ports": {"listeners": []}}}
    sid = s.write_snapshot(payload, label=None)
    assert isinstance(sid, int) and sid > 0

    got = s.read_snapshot(sid)
    assert got["payload"] == payload
    assert got["label"] is None
    assert got["ts"] > 0


def test_write_labeled_snapshot(config):
    s = Store(config)
    s.open()
    sid = s.write_snapshot({"x": 1}, label="before-deploy")
    got = s.read_snapshot(sid)
    assert got["label"] == "before-deploy"


def test_list_snapshots_newest_first(config):
    s = Store(config)
    s.open()
    a = s.write_snapshot({"i": 1}, label=None)
    b = s.write_snapshot({"i": 2}, label=None)
    c = s.write_snapshot({"i": 3}, label="manual")
    rows = s.list_snapshots(limit=10)
    assert [r["id"] for r in rows] == [c, b, a]  # newest first


def test_list_snapshots_limit(config):
    s = Store(config)
    s.open()
    for _ in range(5):
        s.write_snapshot({"i": 1}, label=None)
    assert len(s.list_snapshots(limit=3)) == 3


def test_latest_returns_most_recent(config):
    s = Store(config)
    s.open()
    s.write_snapshot({"i": 1}, label=None)
    sid2 = s.write_snapshot({"i": 2}, label=None)
    latest = s.latest()
    assert latest["id"] == sid2


def test_latest_returns_none_when_empty(config):
    s = Store(config)
    s.open()
    assert s.latest() is None


def test_resolve_id_or_label_by_id(config):
    s = Store(config)
    s.open()
    sid = s.write_snapshot({"i": 1}, label="deploy-1")
    assert s.resolve_snapshot("1")["id"] == sid
    assert s.resolve_snapshot(sid)["id"] == sid


def test_resolve_id_or_label_by_label(config):
    s = Store(config)
    s.open()
    s.write_snapshot({"i": 1}, label="deploy-1")
    sid2 = s.write_snapshot({"i": 2}, label="deploy-1")  # same label, later
    # label resolves to the LATEST snapshot with that label
    got = s.resolve_snapshot("deploy-1")
    assert got["id"] == sid2


def test_resolve_unknown_returns_none(config):
    s = Store(config)
    s.open()
    assert s.resolve_snapshot("nonexistent") is None


def _raw_insert(s, label):
    """Insert a snapshot row bypassing write_snapshot's auto-prune, so prune tests
    can set up an exact pre-prune state and assert on a single prune() call."""
    import json

    cur = s.conn.execute(
        "INSERT INTO snapshots (ts, label, payload) VALUES (?, ?, ?)",
        (time.time(), label, json.dumps({"i": 1})),
    )
    s.conn.commit()
    return cur.lastrowid


def test_prune_keeps_most_recent_n_unlabeled(config):
    """Count-based prune: keep the most recent `keep` unlabeled snapshots, delete older ones."""
    config.retention_snapshots = 3
    s = Store(config)
    s.open()
    ids = [_raw_insert(s, None) for _ in range(5)]
    deleted = s.prune()
    assert deleted == 2  # 5 present, keep 3 → 2 pruned
    remaining = {r["id"] for r in s.list_snapshots(limit=100)}
    assert remaining == set(ids[-3:])  # the newest 3 survive


def test_prune_exempts_labeled_snapshots(config):
    """Manual labeled snapshots are NEVER pruned — you don't want 'before-deploy'
    silently deleted out from under you. Prune only drops unlabeled auto-snapshots."""
    config.retention_snapshots = 2
    s = Store(config)
    s.open()
    u1 = _raw_insert(s, None)
    u2 = _raw_insert(s, None)
    u3 = _raw_insert(s, None)
    l1 = _raw_insert(s, "keep-1")
    l2 = _raw_insert(s, "keep-2")
    deleted = s.prune()
    assert deleted == 1  # only the oldest unlabeled (u1) pruned
    remaining = {r["id"] for r in s.list_snapshots(limit=100)}
    assert u2 in remaining and u3 in remaining
    assert l1 in remaining and l2 in remaining
    assert u1 not in remaining  # the one unlabeled casualty


def test_write_snapshot_auto_prunes(config):
    """write_snapshot prunes after each write, so storage stays bounded during long
    unattended runs — the explicit user requirement."""
    config.retention_snapshots = 3
    s = Store(config)
    s.open()
    ids = [s.write_snapshot({"i": i}, label=None) for i in range(5)]
    remaining = {r["id"] for r in s.list_snapshots(limit=100)}
    assert remaining == set(ids[-3:])  # auto-prune kept only the newest 3


def test_prune_noop_when_under_limit(config):
    config.retention_snapshots = 10
    s = Store(config)
    s.open()
    for _ in range(3):
        s.write_snapshot({"i": 1}, label=None)
    assert s.prune() == 0


def test_schema_version_recorded(config):
    s = Store(config)
    s.open()
    with sqlite3.connect(config.db_path) as cx:
        v = cx.execute("SELECT version FROM schema_version").fetchone()[0]
    assert v == SCHEMA_VERSION


def test_existing_db_not_recreated(config):
    s1 = Store(config)
    s1.open()
    sid = s1.write_snapshot({"x": 1}, label=None)
    s1.close()
    s2 = Store(config)
    s2.open()
    assert s2.read_snapshot(sid)["payload"] == {"x": 1}
    s2.close()


def test_count(config):
    s = Store(config)
    s.open()
    assert s.count() == 0
    s.write_snapshot({"x": 1}, label=None)
    s.write_snapshot({"x": 2}, label="m")
    assert s.count() == 2
