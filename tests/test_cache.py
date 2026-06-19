"""Unit tests for the TTL-backed JSON file cache."""
from __future__ import annotations

import os
import time

from cache import DashboardCache
from models import AccountCost, DashboardData, ServiceCost


def _data(refreshed_at: str = "2026-06-20T00:00:00+00:00") -> DashboardData:
    return DashboardData(
        accounts=(
            AccountCost("111111111111", "prod", 120.5, 300.0, 250.25, "USD"),
        ),
        by_service={"111111111111": (ServiceCost("EC2", 100.0),)},
        credits=(),
        budgets=(),
        currency="USD",
        refreshed_at=refreshed_at,
    )


def test_write_then_read_returns_equal(tmp_path):
    cache = DashboardCache(tmp_path / "cache.json", ttl_seconds=3600)
    data = _data()
    cache.write(data)
    assert cache.read() == data


def test_is_fresh_true_right_after_write(tmp_path):
    cache = DashboardCache(tmp_path / "cache.json", ttl_seconds=3600)
    cache.write(_data())
    assert cache.is_fresh() is True


def test_is_fresh_false_when_ttl_zero(tmp_path):
    cache = DashboardCache(tmp_path / "cache.json", ttl_seconds=0)
    cache.write(_data())
    # age (>=0) is never < 0 ttl
    assert cache.is_fresh() is False


def test_is_fresh_false_when_expired_via_utime(tmp_path):
    path = tmp_path / "cache.json"
    cache = DashboardCache(path, ttl_seconds=60)
    cache.write(_data())
    # Age the file two minutes into the past.
    old = time.time() - 120
    os.utime(path, (old, old))
    assert cache.is_fresh() is False


def test_is_fresh_false_when_file_missing(tmp_path):
    cache = DashboardCache(tmp_path / "missing.json", ttl_seconds=3600)
    assert cache.is_fresh() is False


def test_read_returns_none_for_missing_file(tmp_path):
    cache = DashboardCache(tmp_path / "missing.json", ttl_seconds=3600)
    assert cache.read() is None


def test_read_returns_none_for_corrupt_file(tmp_path):
    path = tmp_path / "cache.json"
    path.write_text("{not valid json", encoding="utf-8")
    cache = DashboardCache(path, ttl_seconds=3600)
    assert cache.read() is None


def test_read_returns_none_for_wrong_shape(tmp_path):
    path = tmp_path / "cache.json"
    path.write_text('{"accounts": "oops"}', encoding="utf-8")
    cache = DashboardCache(path, ttl_seconds=3600)
    assert cache.read() is None


def test_read_ignores_freshness(tmp_path):
    """read() returns data even when the file is stale."""
    path = tmp_path / "cache.json"
    cache = DashboardCache(path, ttl_seconds=1)
    data = _data()
    cache.write(data)
    old = time.time() - 9999
    os.utime(path, (old, old))
    assert cache.is_fresh() is False
    assert cache.read() == data
