"""Users collector — system user accounts.

macOS: `dscl . list /Users` (then filter out system accounts starting with underscore
and the common daemons). Linux: parse /etc/passwd directly (no subprocess needed — it's
a file). Both normalize to a sorted list of usernames.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from drift.plugins.base import CollectorError

_NAME = "users"


class UsersCollector:
    name = _NAME

    def is_available(self) -> bool:
        if shutil.which("dscl") is not None:
            return True
        return Path("/etc/passwd").exists()

    def collect(self) -> dict:
        if shutil.which("dscl") is not None:
            return self._via_dscl()
        if Path("/etc/passwd").exists():
            return self._via_passwd()
        raise CollectorError("no user source available (need dscl or /etc/passwd)")

    def _via_dscl(self) -> dict:
        try:
            proc = subprocess.run(
                ["dscl", ".", "-list", "/Users"],
                capture_output=True, text=True, timeout=10, check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
            raise CollectorError(f"dscl failed: {exc}") from exc
        users = []
        for line in proc.stdout.splitlines():
            name = line.split()[0] if line.split() else ""
            if name and not name.startswith("_") and name not in ("daemon", "nobody", "root"):
                users.append(name)
        return {"users": sorted(users)}

    def _via_passwd(self) -> dict:
        try:
            text = Path("/etc/passwd").read_text()
        except OSError as exc:
            raise CollectorError(f"could not read /etc/passwd: {exc}") from exc
        users = []
        for line in text.splitlines():
            if ":" not in line:
                continue
            fields = line.split(":")
            name = fields[0]
            uid = int(fields[2]) if len(fields) > 2 and fields[2].lstrip("-").isdigit() else -1
            if name and uid >= 1000:
                users.append(name)
        return {"users": sorted(users)}


collector = UsersCollector()

