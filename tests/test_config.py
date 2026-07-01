"""Tests for Config — env vars, ini file, precedence (mirrors Mechanic)."""

from pathlib import Path

from drift.config import Config


def write_ini(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_defaults_when_no_env_no_ini(isolated_env, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = Config().resolve()
    assert cfg.data_dir == tmp_path / ".local" / "share" / "drift"
    assert cfg.interval_hours == 6.0
    assert cfg.retention_snapshots == 240


def test_ini_sets_data_dir(isolated_env, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    ini = tmp_path / ".config" / "drift" / "drift.ini"
    write_ini(ini, "[storage]\ndata_dir = /opt/drift-data\n")
    cfg = Config(config_path=ini).resolve()
    assert str(cfg.data_dir) == "/opt/drift-data"
    assert str(cfg.db_path) == "/opt/drift-data/drift.sqlite"


def test_ini_sets_interval_and_retention(isolated_env, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    ini = tmp_path / ".config" / "drift" / "drift.ini"
    write_ini(ini, "[snapshotter]\ninterval_hours = 3\nretention_snapshots = 100\n")
    cfg = Config(config_path=ini).resolve()
    assert cfg.interval_hours == 3.0
    assert cfg.retention_snapshots == 100


def test_env_overrides_ini(isolated_env, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("DRIFT_INTERVAL_HOURS", "1")
    ini = tmp_path / ".config" / "drift" / "drift.ini"
    write_ini(ini, "[snapshotter]\ninterval_hours = 3\n")
    cfg = Config(config_path=ini).resolve()
    assert cfg.interval_hours == 1.0  # env wins


def test_env_data_dir_overrides_ini(isolated_env, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("DRIFT_DATA_DIR", "/from-env")
    ini = tmp_path / ".config" / "drift" / "drift.ini"
    write_ini(ini, "[storage]\ndata_dir = /from-ini\n")
    cfg = Config(config_path=ini).resolve()
    assert str(cfg.data_dir) == "/from-env"


def test_missing_ini_falls_back_to_defaults(isolated_env, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = Config(config_path=tmp_path / "nonexistent.ini").resolve()
    assert cfg.interval_hours == 6.0


def test_enabled_collectors_from_ini(isolated_env, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    ini = tmp_path / ".config" / "drift" / "drift.ini"
    write_ini(ini, "[collectors]\nenabled_collectors = ports, users\n")
    cfg = Config(config_path=ini).resolve()
    assert cfg.enabled_collectors == ["ports", "users"]


def test_drift_config_env_overrides_config_path(isolated_env, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    custom = tmp_path / "custom.ini"
    write_ini(custom, "[snapshotter]\ninterval_hours = 9\n")
    monkeypatch.setenv("DRIFT_CONFIG", str(custom))
    cfg = Config().resolve()
    assert cfg.interval_hours == 9.0
