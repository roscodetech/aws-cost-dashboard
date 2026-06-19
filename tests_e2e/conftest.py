"""E2E fixtures: a real Flask server driven by Playwright, fed a fake provider.

The server runs the REAL ``create_app`` against an in-memory ``FakeProvider`` so
no AWS access or billing is involved. The app is served on an ephemeral free port
via werkzeug's ``make_server`` on a background thread, and torn down on teardown.
"""
from __future__ import annotations

import threading
from dataclasses import replace
from pathlib import Path

import pytest
from werkzeug.serving import make_server

from app import create_app
from config import Config
from models import (
    AccountCost,
    BudgetStatus,
    CreditInfo,
    DashboardData,
    ServiceCost,
)

# Deterministic accounts: prod / staging / dev with varied costs.
_ACCOUNTS = (
    AccountCost("111111111111", "prod", 1234.56, 1500.00, 1800.00, "USD"),
    AccountCost("222222222222", "staging", 210.40, 180.00, 250.00, "USD"),
    AccountCost("333333333333", "dev", 42.10, 30.00, 55.00, "USD"),
)

_BY_SERVICE = {
    "111111111111": (
        ServiceCost("EC2", 800.00),
        ServiceCost("S3", 234.56),
        ServiceCost("RDS", 200.00),
    ),
    "222222222222": (
        ServiceCost("Lambda", 110.40),
        ServiceCost("CloudWatch", 100.00),
    ),
    "333333333333": (ServiceCost("EC2", 42.10),),
}

# One credit with a remaining_balance set, one with None.
_CREDITS = (
    CreditInfo("111111111111", 50.00, 950.00, "2026-12-31", "annual promo"),
    CreditInfo("222222222222", 10.00, None, None, None),
    CreditInfo("333333333333", 0.00, None, None, None),
)

_BUDGETS = (
    BudgetStatus("Monthly payer budget", "111111111111", 2000.00, 1487.06, 2105.00),
)


def _initial_data() -> DashboardData:
    return DashboardData(
        accounts=_ACCOUNTS,
        by_service=_BY_SERVICE,
        credits=_CREDITS,
        budgets=_BUDGETS,
        currency="USD",
        refreshed_at="2026-06-20T00:00:00+00:00",
    )


class FakeProvider:
    """In-memory provider. Records update_credit calls and reflects them on reload."""

    def __init__(self) -> None:
        self._data = _initial_data()
        self.get_calls: list[bool] = []
        self.update_calls: list[dict] = []

    def get(self, force: bool = False) -> DashboardData:
        self.get_calls.append(force)
        return self._data

    def update_credit(self, account_id, balance, expiry, note) -> None:
        self.update_calls.append(
            {
                "account_id": account_id,
                "balance": balance,
                "expiry": expiry,
                "note": note,
            }
        )
        # Mutate the in-memory credit so a subsequent reload reflects the edit.
        new_credits = tuple(
            replace(c, remaining_balance=balance, expiry=expiry, note=note)
            if c.account_id == account_id
            else c
            for c in self._data.credits
        )
        self._data = replace(self._data, credits=new_credits)


def _fake_config(tmp_path: Path) -> Config:
    return Config(
        profile="fake-profile",
        access_key_id=None,
        secret_access_key=None,
        region="us-east-1",
        cache_ttl_seconds=3600,
        cache_path=tmp_path / "cache.json",
        credits_path=tmp_path / "credits.json",
        host="127.0.0.1",
        port=0,
    )


class _ServerThread(threading.Thread):
    """Runs a werkzeug server on a background thread; binds port 0 for a free port."""

    def __init__(self, app) -> None:
        super().__init__(daemon=True)
        # Port 0 -> OS picks a free ephemeral port; read it back below.
        self._server = make_server("127.0.0.1", 0, app, threaded=True)
        self.port = self._server.server_port

    def run(self) -> None:
        self._server.serve_forever()

    def shutdown(self) -> None:
        self._server.shutdown()


@pytest.fixture
def fake_provider() -> FakeProvider:
    return FakeProvider()


@pytest.fixture
def live_server(tmp_path: Path, fake_provider: FakeProvider):
    """Start the real Flask app with the fake provider; yield (base_url, provider)."""
    app = create_app(_fake_config(tmp_path), fake_provider)
    server = _ServerThread(app)
    server.start()
    base_url = f"http://127.0.0.1:{server.port}"
    try:
        yield base_url, fake_provider
    finally:
        server.shutdown()
        server.join(timeout=5)
