"""Packages collector — installed package set.

Detects the package manager: brew (macOS), dpkg (Debian), rpm (Red Hat). Returns the
list of installed package names plus the manager name (so cross-manager comparisons
are honest — a brew set and a dpkg set aren't comparable).
"""

from __future__ import annotations

import shutil
import subprocess

from drift.plugins.base import CollectorError

_NAME = "packages"


class PackagesCollector:
    name = _NAME

    def is_available(self) -> bool:
        for mgr in ("brew", "dpkg-query", "rpm"):
            if shutil.which(mgr) is not None:
                return True
        return False

    def collect(self) -> dict:
        if shutil.which("brew") is not None:
            return self._run("brew", ["list", "--formula"], "brew")
        if shutil.which("dpkg-query") is not None:
            return self._run("dpkg-query", ["-W", "-f=${Package}\n"], "dpkg")
        if shutil.which("rpm") is not None:
            return self._run("rpm", ["-qa", "--qf", "%{NAME}\n"], "rpm")
        raise CollectorError("no package manager available (need brew, dpkg-query, or rpm)")

    def _run(self, mgr: str, args: list[str], label: str) -> dict:
        try:
            proc = subprocess.run(
                [mgr, *args], capture_output=True, text=True, timeout=30, check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
            raise CollectorError(f"{mgr} failed: {exc}") from exc
        installed = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
        return {"manager": label, "installed": installed}


collector = PackagesCollector()
