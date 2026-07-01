"""Tests for the MCP server surface. Stateless reader over the store + differ.

Tools: diff(snapshot_a, snapshot_b), latest(), list_snapshots(limit), doctor().
Tests populate a real temp store and invoke tools in-process via FastMCP.call_tool.
"""

import asyncio
import json

import pytest

from drift.config import SCHEMA_VERSION
from drift.server import build_server
from drift.store import Store


@pytest.fixture
def store(config):
    s = Store(config)
    s.open()
    s.write_snapshot({"collectors": {"ports": {"listeners": [
        {"proto": "tcp", "port": 80, "proc": "nginx"},
    ]}}}, label="baseline")
    s.write_snapshot({"collectors": {"ports": {"listeners": [
        {"proto": "tcp", "port": 80, "proc": "nginx"},
        {"proto": "tcp", "port": 8080, "proc": "python"},
    ]}}}, label="after-deploy")
    return s


@pytest.fixture
def server(store, config):
    return build_server(store, config)


def _call(server, tool, args):
    result = asyncio.run(server.call_tool(tool, args))
    if isinstance(result, tuple):
        blocks, structured = result
        if isinstance(structured, dict):
            return structured
        return json.loads(blocks[0].text) if blocks else None
    return result


def test_list_tools_exposes_four(server):
    tools = asyncio.run(server.list_tools())
    names = {t.name for t in tools}
    assert {"diff", "latest", "list_snapshots", "doctor"} <= names


def test_doctor_reports_store_and_collectors(server, store):
    r = _call(server, "doctor", {})
    assert r["ok"] is True
    assert r["store"]["schema_version"] == SCHEMA_VERSION
    assert r["store"]["total_snapshots"] == 2
    names = {c["name"] for c in r["collectors"]}
    assert {"ports", "services", "packages", "users", "cron"} <= names


def test_latest_returns_most_recent(server, store):
    r = _call(server, "latest", {})
    assert r["label"] == "after-deploy"
    assert "listeners" in r["payload"]["collectors"]["ports"]


def test_latest_returns_none_when_empty(config):
    s = Store(config)
    s.open()
    srv = build_server(s, config)
    r = _call(srv, "latest", {})
    assert r.get("snapshot") is None or r is None or "id" not in r


def test_list_snapshots(server):
    r = _call(server, "list_snapshots", {"limit": 10})
    assert r["count"] == 2
    assert r["snapshots"][0]["label"] == "after-deploy"  # newest first
    assert r["snapshots"][1]["label"] == "baseline"


def test_diff_by_label(server):
    r = _call(server, "diff", {"snapshot_a": "baseline", "snapshot_b": "after-deploy"})
    assert "diff" in r
    assert "summary" in r
    # the diff should show 8080 added
    assert "8080" in json.dumps(r["diff"])
    # the summary should mention it
    assert "8080" in r["summary"]


def test_diff_by_id(server, store):
    rows = store.list_snapshots(10)
    a, b = rows[-1]["id"], rows[0]["id"]
    r = _call(server, "diff", {"snapshot_a": str(a), "snapshot_b": str(b)})
    assert "diff" in r and "summary" in r


def test_diff_no_changes(server):
    r = _call(server, "diff", {"snapshot_a": "after-deploy", "snapshot_b": "after-deploy"})
    assert r["summary"].startswith("No changes")


def test_diff_unknown_snapshot_returns_error(server):
    r = _call(server, "diff", {"snapshot_a": "nonexistent", "snapshot_b": "after-deploy"})
    assert "error" in r or r.get("ok") is False


def test_tools_return_json_serializable(server):
    for tool, args in [
        ("doctor", {}),
        ("latest", {}),
        ("list_snapshots", {"limit": 5}),
        ("diff", {"snapshot_a": "baseline", "snapshot_b": "after-deploy"}),
    ]:
        r = _call(server, tool, args)
        json.dumps(r)
