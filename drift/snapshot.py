"""Snapshot aggregator — runs all available collectors into one JSON document.

The glue between collectors and the store. For each registered collector: if available,
run it; on success include its output; on failure record an entry in `errors` and move
on. One collector's failure never stops the snapshot. The result is a single
JSON-serializable doc the store persists as one row.
"""

from __future__ import annotations

import platform
import time
from collections.abc import Iterable
from typing import Any

from drift.plugins.base import CollectorPlugin


def snapshot(
    collectors: Iterable[CollectorPlugin],
    label: str | None = None,
) -> dict[str, Any]:
    """Capture the current operational state of the box.

    Returns a JSON-serializable dict:
        {
          "ts": <epoch>,
          "label": <str|None>,
          "host": <node name>,
          "collectors": {name: payload, ...},   # only available + successful
          "errors": [{"collector": name, "error": str}, ...]
        }
    """
    doc: dict[str, Any] = {
        "ts": time.time(),
        "label": label,
        "host": platform.node(),
        "collectors": {},
        "errors": [],
    }
    for c in collectors:
        try:
            if not c.is_available():
                continue
            doc["collectors"][c.name] = c.collect()
        except Exception as exc:  # noqa: BLE001 - isolate per-collector failure
            doc["errors"].append({"collector": c.name, "error": str(exc)})
    return doc
