"""Tests for the snapshot aggregator. Runs all available collectors into one JSON doc."""

import platform

from drift.snapshot import snapshot


class FakeCollector:
    def __init__(self, name, available=True, payload=None, raises=None):
        self.name = name
        self._available = available
        self.payload = payload if payload is not None else {"x": 1}
        self.raises = raises

    def is_available(self):
        return self._available

    def collect(self):
        if self.raises:
            raise self.raises
        return dict(self.payload)


def test_snapshot_aggregates_all_available_collectors():
    cols = [FakeCollector("a", payload={"k": 1}), FakeCollector("b", payload={"k": 2})]
    doc = snapshot(cols)
    assert doc["collectors"]["a"] == {"k": 1}
    assert doc["collectors"]["b"] == {"k": 2}


def test_snapshot_records_ts_and_host():
    cols = [FakeCollector("a")]
    doc = snapshot(cols)
    assert "ts" in doc and doc["ts"] > 0
    assert "host" in doc and isinstance(doc["host"], str)
    assert doc["host"] == platform.node() or isinstance(doc["host"], str)


def test_snapshot_omits_unavailable_collectors():
    cols = [FakeCollector("a", available=True), FakeCollector("b", available=False)]
    doc = snapshot(cols)
    assert "a" in doc["collectors"]
    assert "b" not in doc["collectors"]


def test_snapshot_isolates_collector_failure():
    """One collector raising must not stop the snapshot — the rest still captured."""
    cols = [
        FakeCollector("good", payload={"k": 1}),
        FakeCollector("bad", raises=RuntimeError("boom")),
        FakeCollector("also_good", payload={"k": 2}),
    ]
    doc = snapshot(cols)
    assert "good" in doc["collectors"]
    assert "also_good" in doc["collectors"]
    assert "bad" not in doc["collectors"]
    # the failed collector is recorded in an errors list for visibility
    assert "errors" in doc
    assert any(e["collector"] == "bad" for e in doc["errors"])


def test_snapshot_records_label_when_given():
    cols = [FakeCollector("a")]
    doc = snapshot(cols, label="before-deploy")
    assert doc["label"] == "before-deploy"


def test_snapshot_label_defaults_none():
    cols = [FakeCollector("a")]
    doc = snapshot(cols)
    assert doc["label"] is None


def test_snapshot_no_available_collectors():
    cols = [FakeCollector("a", available=False), FakeCollector("b", available=False)]
    doc = snapshot(cols)
    assert doc["collectors"] == {}


def test_snapshot_is_json_serializable():
    import json

    cols = [
        FakeCollector("a", payload={"k": [1, 2, 3]}),
        FakeCollector("b", payload={"k": {"nested": True}}),
    ]
    doc = snapshot(cols, label="t")
    json.dumps(doc)  # raises if not serializable
