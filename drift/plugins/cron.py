"""Cron collector — scheduled jobs.

Captures crontab entries (if any) plus, on macOS, the user's launchd agents (which
serve the same role as cron for most macOS users). On Linux, also includes files in
/etc/cron.d. Empty crontab is a normal state, not an error.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

_NAME = "cron"
_USER_AGENTS = Path.home() / "Library" / "LaunchAgents"
_CRON_D = Path("/etc/cron.d")


class CronCollector:
    name = _NAME

    def is_available(self) -> bool:
        # Available if there's a crontab binary, or any cron-like source exists.
        return (
            shutil.which("crontab") is not None
            or _USER_AGENTS.exists()
            or _CRON_D.exists()
        )

    def collect(self) -> dict:
        entries = self._crontab_entries()
        agents = self._launchd_agents()
        cron_d = self._cron_d_entries()
        return {"entries": entries, "agents": agents, "cron_d": cron_d}

    def _crontab_entries(self) -> list[str]:
        if shutil.which("crontab") is None:
            return []
        try:
            proc = subprocess.run(
                ["crontab", "-l"], capture_output=True, text=True, timeout=10, check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return []
        # returncode 1 / "no crontab" is normal → empty list
        if proc.returncode != 0:
            return []
        return [line for line in proc.stdout.splitlines() if line.strip()]

    def _launchd_agents(self) -> list[str]:
        if not _USER_AGENTS.exists():
            return []
        try:
            return sorted(p.name for p in _USER_AGENTS.iterdir() if p.name.endswith(".plist"))
        except OSError:
            return []

    def _cron_d_entries(self) -> list[str]:
        if not _CRON_D.exists():
            return []
        out = []
        try:
            for f in sorted(_CRON_D.iterdir()):
                if f.is_file() and not f.name.startswith("."):
                    out.append(f.name)
        except OSError:
            pass
        return out


collector = CronCollector()
