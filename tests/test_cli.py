"""Tests for the CLI entrypoint. Dispatch + exit codes; long-running subcommands
are short-circuited (snapshotter tested separately)."""

import os

from drift import cli


def test_cli_has_subcommands():
    parser = cli.build_parser()
    # subcommands with required positional args need dummy values
    cases = [
        ["snap"],
        ["diff", "a", "b"],
        ["list"],
        ["snapshotter"],
        ["server"],
        ["doctor"],
        ["status"],
    ]
    for argv in cases:
        args = parser.parse_args(argv)
        assert args.command == argv[0]


def test_doctor_returns_zero(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DRIFT_DB_PATH", str(tmp_path / "d.db"))
    rc = cli.run(["doctor"])
    assert rc == 0


def test_snap_writes_a_snapshot_and_returns_zero(tmp_path):
    os.environ["DRIFT_DATA_DIR"] = str(tmp_path)
    os.environ["DRIFT_DB_PATH"] = str(tmp_path / "d.db")
    try:
        rc = cli.run(["snap", "--label", "test-1"])
    finally:
        del os.environ["DRIFT_DATA_DIR"]
        del os.environ["DRIFT_DB_PATH"]
    assert rc == 0
    from drift.config import Config
    from drift.store import Store

    cfg = Config(data_dir=tmp_path, db_path=tmp_path / "d.db").resolve()
    s = Store(cfg)
    s.open()
    assert s.count() == 1
    snap = s.latest()
    assert snap["label"] == "test-1"
    s.close()


def test_snap_without_label(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DRIFT_DB_PATH", str(tmp_path / "d.db"))
    rc = cli.run(["snap"])
    assert rc == 0


def test_diff_prints_summary(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DRIFT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DRIFT_DB_PATH", str(tmp_path / "d.db"))
    cli.run(["snap", "--label", "a"])
    cli.run(["snap", "--label", "b"])
    rc = cli.run(["diff", "a", "b"])
    assert rc == 0
    out = capsys.readouterr().out
    # two empty-ish snapshots → "No changes" mentions both labels
    assert "a" in out and "b" in out


def test_diff_json_flag(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DRIFT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DRIFT_DB_PATH", str(tmp_path / "d.db"))
    cli.run(["snap", "--label", "a"])
    cli.run(["snap", "--label", "b"])
    rc = cli.run(["diff", "a", "b", "--json"])
    assert rc == 0
    out = capsys.readouterr().out
    import json

    parsed = json.loads(out)  # --json prints valid JSON
    assert "diff" in parsed and "summary" in parsed


def test_list_prints_snapshots(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DRIFT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DRIFT_DB_PATH", str(tmp_path / "d.db"))
    cli.run(["snap", "--label", "first"])
    rc = cli.run(["list"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "first" in out


def test_status_shows_latest(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DRIFT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DRIFT_DB_PATH", str(tmp_path / "d.db"))
    cli.run(["snap"])
    rc = cli.run(["status"])
    assert rc == 0


def test_unknown_command_returns_nonzero(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFT_DATA_DIR", str(tmp_path))
    rc = cli.run(["bogus"])
    assert rc != 0


def test_diff_unknown_snapshot_returns_nonzero(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DRIFT_DB_PATH", str(tmp_path / "d.db"))
    cli.run(["snap", "--label", "a"])
    rc = cli.run(["diff", "a", "nonexistent"])
    assert rc != 0
