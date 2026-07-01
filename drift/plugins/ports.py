"""Ports collector — listening TCP/UDP ports.

Uses lsof on macOS, ss on Linux. Normalizes both to the same shape so the differ can
compare cross-platform: a list of {proto, port, proc}. No-op (unavailable) when
neither tool is present.
"""

from __future__ import annotations

import re
import shutil
import subprocess

from drift.plugins.base import CollectorError

_NAME = "ports"


class PortsCollector:
    name = _NAME

    def is_available(self) -> bool:
        return shutil.which("lsof") is not None or shutil.which("ss") is not None

    def collect(self) -> dict:
        if shutil.which("lsof") is not None:
            return self._via_lsof()
        if shutil.which("ss") is not None:
            return self._via_ss()
        raise CollectorError("no ports tool available (need lsof or ss)")

    def _via_lsof(self) -> dict:
        # -nP: no name resolution, no port-to-name; -iTCP -sTCP:LISTEN for tcp listeners.
        try:
            proc = subprocess.run(
                ["lsof", "-nP", "-iTCP", "-sTCP:LISTEN"],
                capture_output=True, text=True, timeout=10, check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
            raise CollectorError(f"lsof failed: {exc}") from exc
        listeners = []
        for line in proc.stdout.splitlines():
            cols = line.split()
            if len(cols) < 2:
                continue
            # find the NAME column: the token ending in :<port>. A real lsof header
            # line has no such token, so it's skipped naturally without a hard slice.
            addr = next((c for c in cols if re.search(r":\d+$", c)), None)
            if not addr:
                continue
            m = re.search(r":(\d+)$", addr)
            listeners.append({"proto": "tcp", "port": int(m.group(1)), "proc": cols[0]})
        return {"listeners": listeners}

    def _via_ss(self) -> dict:
        try:
            proc = subprocess.run(
                ["ss", "-tlnp"], capture_output=True, text=True, timeout=10, check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
            raise CollectorError(f"ss failed: {exc}") from exc
        listeners = []
        for line in proc.stdout.splitlines():
            cols = line.split()
            if len(cols) < 2:
                continue
            # local address is the token ending in :<port> that isn't '*:*'.
            # ss's header line has no such token → skipped naturally.
            local = next((c for c in cols if re.search(r":\d+$", c) and not c.endswith(":*")), None)
            if not local:
                continue
            m = re.search(r":(\d+)$", local)
            proc_match = re.search(r'users:\(\("([^"]+)"', line)
            listeners.append({
                "proto": "tcp", "port": int(m.group(1)),
                "proc": proc_match.group(1) if proc_match else "",
            })
        return {"listeners": listeners}


collector = PortsCollector()
