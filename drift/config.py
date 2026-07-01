"""Configuration for Drift.

Resolved with this precedence (highest wins):
  1. DRIFT_* environment variables
  2. ~/.config/drift/drift.ini  (or $DRIFT_CONFIG)
  3. built-in defaults

Mirrors Mechanic's config so the two tools feel like siblings. The ini file is what
makes a real install coherent: the installer writes data_dir into drift.ini, so the
interactive `drift diff` (no env var) reads the same DB the snapshotter daemon writes.
"""

from __future__ import annotations

import configparser
import os
from dataclasses import dataclass, field
from pathlib import Path


def _default_data_dir() -> Path:
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / "drift"
    return Path.home() / ".local" / "share" / "drift"


def _default_config_path() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) / "drift" if xdg else Path.home() / ".config" / "drift"
    return base / "drift.ini"


@dataclass
class Config:
    """Runtime configuration. Values are safe defaults; override via env vars or ini."""

    # Storage
    data_dir: Path = field(default_factory=_default_data_dir)
    db_path: Path | None = None

    # Snapshotting
    interval_hours: float = 6.0
    retention_snapshots: int = 240  # keep most recent N; prune the rest

    # Collectors
    enabled_collectors: list[str] = field(default_factory=list)  # empty == all available

    config_path: Path | None = None

    def __post_init__(self) -> None:
        if self.config_path is None:
            self.config_path = _default_config_path()

    def _load_ini(self) -> dict[str, str]:
        path = self.config_path
        if path is None or not Path(path).exists():
            return {}
        parser = configparser.ConfigParser()
        try:
            parser.read(path)
        except configparser.Error:
            return {}
        flat: dict[str, str] = {}
        for section in parser.sections():
            for key, value in parser.items(section):
                flat[key] = value
        return flat

    def resolve(self) -> Config:
        if env_cfg := os.environ.get("DRIFT_CONFIG"):
            self.config_path = Path(env_cfg)
        ini = self._load_ini()

        def pick(key: str, env_name: str) -> str | None:
            env = os.environ.get(env_name)
            if env is not None:
                return env
            return ini.get(key)

        if (v := pick("data_dir", "DRIFT_DATA_DIR")) is not None:
            self.data_dir = Path(v)
        if (v := pick("db_path", "DRIFT_DB_PATH")) is not None:
            self.db_path = Path(v)
        if (v := pick("interval_hours", "DRIFT_INTERVAL_HOURS")) is not None:
            self.interval_hours = float(v)
        if (v := pick("retention_snapshots", "DRIFT_RETENTION_SNAPSHOTS")) is not None:
            self.retention_snapshots = int(v)
        if (v := pick("enabled_collectors", "DRIFT_ENABLED_COLLECTORS")) is not None:
            self.enabled_collectors = [c.strip() for c in v.split(",") if c.strip()]

        if self.db_path is None:
            self.db_path = self.data_dir / "drift.sqlite"
        return self

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)


SCHEMA_VERSION = 1
