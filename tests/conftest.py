"""Shared pytest fixtures for Drift. Hermetic: temp DB per test, no real collectors."""

import os
from pathlib import Path

import pytest


@pytest.fixture
def tmp_data_dir(tmp_path: Path) -> Path:
    d = tmp_path / "data"
    d.mkdir()
    return d


@pytest.fixture
def isolated_env(monkeypatch):
    for k in list(os.environ):
        if k.startswith("DRIFT_"):
            monkeypatch.delenv(k, raising=False)
    yield


@pytest.fixture
def config(tmp_data_dir, isolated_env):
    from drift.config import Config

    cfg = Config(data_dir=tmp_data_dir, db_path=tmp_data_dir / "drift.sqlite")
    cfg.ensure_dirs()
    return cfg
