"""Collector plugin protocol + registry.

A collector is anything that satisfies the CollectorPlugin protocol:
  - name:          a stable, short string key (e.g. "ports", "packages")
  - is_available(): cheap probe — is this collector usable on this box right now?
  - collect():      return a JSON-serializable dict of current operational state.

Adding a collector is one file: drop a module in this package whose class satisfies
the protocol. The registry auto-discovers it.
"""

from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


class CollectorError(RuntimeError):
    """Raised when a collector cannot produce a snapshot (backend missing, command
    failed). The snapshotter isolates these so one collector's failure never stops
    a snapshot from being captured."""


@runtime_checkable
class CollectorPlugin(Protocol):
    name: str

    def is_available(self) -> bool:  # noqa: D401
        """True if this collector can run on the current box."""
        ...

    def collect(self) -> dict:
        """Return a JSON-serializable dict of current operational state."""
        ...


@dataclass
class _Registry:
    _collectors: list

    def register(self, collector: CollectorPlugin) -> None:
        self._collectors = [c for c in self._collectors if c.name != collector.name]
        self._collectors.append(collector)

    def all(self) -> list[CollectorPlugin]:
        return list(self._collectors)

    def get(self, name: str) -> CollectorPlugin | None:
        for c in self._collectors:
            if c.name == name:
                return c
        return None

    def available(self) -> list[CollectorPlugin]:
        return [c for c in self._collectors if c.is_available()]


registry = _Registry(_collectors=[])


def discover() -> list[CollectorPlugin]:
    """Import every module in this package and register any CollectorPlugin it exposes
    via a top-level `collector` instance or a `Collector` class with a default ctor."""
    import drift.plugins as pkg

    found: list[CollectorPlugin] = []
    for modinfo in pkgutil.iter_modules(pkg.__path__):
        if modinfo.name in ("base", "__init__"):
            continue
        try:
            mod = importlib.import_module(f"drift.plugins.{modinfo.name}")
        except Exception:  # noqa: BLE001
            continue
        inst = getattr(mod, "collector", None)
        if inst is None:
            cls = getattr(mod, "Collector", None)
            if cls is not None:
                try:
                    inst = cls()
                except Exception:  # noqa: BLE001
                    inst = None
        if (
            inst is not None
            and hasattr(inst, "name")
            and hasattr(inst, "is_available")
            and hasattr(inst, "collect")
        ):
            found.append(inst)
            registry.register(inst)
    return found
