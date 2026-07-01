"""Tests for the diff engine — the heart of Drift.

Pure functions: diff(past, latest) -> structured {added, removed, changed}, and
summarize(diff) -> plain English. No I/O. Set-valued collector outputs produce
added/removed; scalar values produce changed {from, to, delta}.
"""

from drift.differ import diff, summarize


def _snap(collectors):
    return {"ts": 100.0, "label": None, "host": "h", "collectors": collectors, "errors": []}


# ---- set-valued (lists) -----------------------------------------------------


def test_diff_added_and_removed_for_list_value():
    past = _snap({"ports": {"listeners": [
        {"proto": "tcp", "port": 80, "proc": "nginx"},
        {"proto": "tcp", "port": 443, "proc": "nginx"},
    ]}})
    latest = _snap({"ports": {"listeners": [
        {"proto": "tcp", "port": 443, "proc": "nginx"},
        {"proto": "tcp", "port": 8080, "proc": "python"},
    ]}})
    d = diff(past, latest)
    assert d["ports"]["listeners"]["added"] == [{"proto": "tcp", "port": 8080, "proc": "python"}]
    assert d["ports"]["listeners"]["removed"] == [{"proto": "tcp", "port": 80, "proc": "nginx"}]


def test_diff_list_unchanged_not_listed():
    past = _snap({"ports": {"listeners": [{"proto": "tcp", "port": 80, "proc": "n"}]}})
    latest = _snap({"ports": {"listeners": [{"proto": "tcp", "port": 80, "proc": "n"}]}})
    d = diff(past, latest)
    assert "ports" not in d  # no change → not in diff


# ---- scalar values ---------------------------------------------------------


def test_diff_scalar_change():
    past = _snap({"pkg": {"count": 100}})
    latest = _snap({"pkg": {"count": 105}})
    d = diff(past, latest)
    assert d["pkg"]["count"] == {"from": 100, "to": 105, "delta": 5}


def test_diff_scalar_unchanged_not_listed():
    past = _snap({"pkg": {"count": 100}})
    latest = _snap({"pkg": {"count": 100}})
    d = diff(past, latest)
    assert "pkg" not in d


# ---- collector only in one snapshot ----------------------------------------


def test_diff_collector_added_in_latest():
    past = _snap({"ports": {"listeners": []}})
    latest = _snap({"ports": {"listeners": []}, "users": {"users": ["bob"]}})
    d = diff(past, latest)
    # 'users' is new in latest — its whole presence is an addition
    assert "users" in d["added"] or d.get("users", {}).get("added") is not None


def test_diff_collector_removed_in_latest():
    past = _snap({"ports": {"listeners": []}, "users": {"users": ["bob"]}})
    latest = _snap({"ports": {"listeners": []}})
    d = diff(past, latest)
    assert "users" in d["removed"]


# ---- mixed per-collector diff ----------------------------------------------


def test_diff_per_collector_isolation():
    """Changes in one collector don't bleed into another."""
    past = _snap({
        "ports": {"listeners": [{"proto": "tcp", "port": 80, "proc": "n"}]},
        "packages": {"manager": "brew", "installed": ["a", "b"]},
    })
    latest = _snap({
        "ports": {"listeners": [
            {"proto": "tcp", "port": 80, "proc": "n"},
            {"proto": "tcp", "port": 8080, "proc": "p"},
        ]},
        "packages": {"manager": "brew", "installed": ["a", "b"]},  # unchanged
    })
    d = diff(past, latest)
    assert "ports" in d
    assert "packages" not in d  # unchanged


# ---- summarize (plain English) ---------------------------------------------


def test_summarize_empty_diff():
    d = diff(_snap({"ports": {"listeners": []}}), _snap({"ports": {"listeners": []}}))
    s = summarize(d, label_a="before", label_b="after")
    assert "No changes" in s
    assert "before" in s and "after" in s


def test_summarize_mentions_added_ports():
    past = _snap({"ports": {"listeners": [{"proto": "tcp", "port": 80, "proc": "n"}]}})
    latest = _snap({"ports": {"listeners": [
        {"proto": "tcp", "port": 80, "proc": "n"},
        {"proto": "tcp", "port": 8080, "proc": "python"},
    ]}})
    d = diff(past, latest)
    s = summarize(d, label_a="before", label_b="after")
    assert "port" in s.lower()
    assert "8080" in s  # the new port is named


def test_summarize_mentions_added_packages():
    past = _snap({"packages": {"manager": "brew", "installed": ["a"]}})
    latest = _snap({"packages": {"manager": "brew", "installed": ["a", "nginx", "certbot"]}})
    d = diff(past, latest)
    s = summarize(d, label_a="before", label_b="after")
    assert "package" in s.lower()
    assert "nginx" in s


def test_summarize_mentions_removed_users():
    past = _snap({"users": {"users": ["alice", "bob"]}})
    latest = _snap({"users": {"users": ["alice"]}})
    d = diff(past, latest)
    s = summarize(d, label_a="before", label_b="after")
    assert "user" in s.lower()
    assert "bob" in s


def test_summarize_mentions_service_changes():
    past = _snap({"services": {"labels": ["a", "b"]}})
    latest = _snap({"services": {"labels": ["a", "c"]}})
    d = diff(past, latest)
    s = summarize(d, label_a="before", label_b="after")
    assert "service" in s.lower() or "label" in s.lower()
    assert "c" in s  # added
    assert "b" in s  # removed


def test_summarize_is_a_string():
    d = diff(_snap({}), _snap({}))
    assert isinstance(summarize(d, "a", "b"), str)


def test_summarize_handles_unknown_labels():
    d = diff(_snap({}), _snap({}))
    s = summarize(d, label_a=None, label_b=None)
    assert isinstance(s, str) and len(s) > 0
