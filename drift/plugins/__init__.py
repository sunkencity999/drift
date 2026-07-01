"""Collector plugins. Each plugin is one module satisfying the CollectorPlugin protocol.

Auto-discovered via the registry in this package. Add a collector by dropping a new
module here that defines a class with name, is_available(), and collect().
"""

from __future__ import annotations

from drift.plugins.base import (  # noqa: F401
    CollectorError,
    CollectorPlugin,
    discover,
    registry,
)

discover()
