"""Live smoke test against real AWS Cost Explorer.

Skipped unless AWS_COST_DASHBOARD_LIVE=1. Each Cost Explorer call costs ~$0.01,
so this is manual-only — never run in CI. Uses the real .env credentials.
"""
from __future__ import annotations

import os

import pytest

from config import load_config
from providers import LiveProvider

LIVE = os.getenv("AWS_COST_DASHBOARD_LIVE") == "1"

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not LIVE, reason="set AWS_COST_DASHBOARD_LIVE=1 to run"),
]


def test_live_build_returns_real_data() -> None:
    """Force a live pull and assert the shape looks like real billing data."""
    provider = LiveProvider(load_config())
    data = provider.get(force=True)

    assert data.refreshed_at
    assert data.currency
    # Consolidated billing: at least the payer account should be present.
    assert len(data.accounts) >= 1
    for account in data.accounts:
        assert account.account_id
        assert account.mtd_cost >= 0.0
        # Every account with cost data should have a by_service entry key.
        assert account.account_id in data.by_service or account.mtd_cost == 0.0
