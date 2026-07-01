"""Services collector — enabled/running system services.

launchd on macOS (labels), systemd on Linux (units). Normalized to a list of service
identifiers per platform (the differ compares within-platform; cross-platform service
names don't map cleanly, so we keep the native namespace).
"""

from __future__ import annotations

import shutil
import subprocess

from drift.plugins.base import CollectorError

_NAME = "services"


class ServicesCollector:
    name = _NAME

    def is_available(self) -> bool:
        return shutil.which("launchctl") is not None or shutil.which("systemctl") is not None

    def collect(self) -> dict:
        if shutil.which("launchctl") is not None:
            return self._via_launchctl()
        if shutil.which("systemctl") is not None:
            return self._via_systemctl()
        raise CollectorError("no services tool available (need launchctl or systemctl)")

    def _via_launchctl(self) -> dict:
        try:
            proc = subprocess.run(
                ["launchctl", "list"], capture_output=True, text=True, timeout=10, check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
            raise CollectorError(f"launchctl failed: {exc}") from exc
        labels = []
        for line in proc.stdout.splitlines()[1:]:  # skip "PID Status Label" header
            cols = line.split()
            if len(cols) >= 3:
                labels.append(cols[2])
        return {"labels": labels}

    def _via_systemctl(self) -> dict:
        try:
            proc = subprocess.run(
                ["systemctl", "list-units", "--type=service", "--no-legend"],
                capture_output=True, text=True, timeout=10, check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
            raise CollectorError(f"systemctl failed: {exc}") from exc
        units = []
        for line in proc.stdout.splitlines():
            cols = line.split()
            if cols and cols[0].endswith(".service"):
                units.append(cols[0])
        return {"units": units}


collector = ServicesCollector()
