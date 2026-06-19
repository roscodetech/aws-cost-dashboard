"""TTL-backed JSON file cache for DashboardData.

Serves the dashboard from disk to avoid repeat Cost Explorer calls (each costs
$0.01). A forced refresh bypasses the TTL. Read/write failures degrade gracefully.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from models import DashboardData


class DashboardCache:
    def __init__(self, path: Path, ttl_seconds: int) -> None:
        self._path = path
        self._ttl = ttl_seconds

    def is_fresh(self) -> bool:
        if self._ttl <= 0:
            return False  # zero/negative TTL => always stale (deterministic)
        try:
            age = time.time() - self._path.stat().st_mtime
        except OSError:
            return False
        return age < self._ttl

    def read(self) -> DashboardData | None:
        """Return cached data regardless of freshness, or None if unreadable."""
        try:
            raw = self._path.read_text(encoding="utf-8")
            return DashboardData.from_dict(json.loads(raw))
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def write(self, data: DashboardData) -> None:
        try:
            self._path.write_text(
                json.dumps(data.to_dict(), indent=2), encoding="utf-8"
            )
        except OSError:
            # Non-fatal: dashboard still works from the in-memory object.
            pass
