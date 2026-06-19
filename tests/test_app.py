"""Integration tests for the Flask app factory and routes.

A fake in-memory provider is injected so no AWS access is needed. The templates
directory ships with the repo, so GET / renders; if it were absent only the
template-dependent assertions here would fail.
"""
from __future__ import annotations

import pytest

from app import create_app
from models import AccountCost, CreditInfo, DashboardData, ServiceCost


def _data() -> DashboardData:
    return DashboardData(
        accounts=(
            AccountCost("111111111111", "prod", 120.5, 300.0, 250.25, "USD"),
        ),
        by_service={"111111111111": (ServiceCost("EC2", 100.0),)},
        credits=(
            CreditInfo("111111111111", 5.0, 95.0, "2026-12-31", "promo"),
        ),
        budgets=(),
        currency="USD",
        refreshed_at="2026-06-20T00:00:00+00:00",
    )


class FakeProvider:
    """Records calls and returns canned data or raises on demand."""

    def __init__(self, data=None, error=None):
        self._data = data if data is not None else _data()
        self._error = error
        self.get_calls = []
        self.update_calls = []

    def get(self, force: bool = False) -> DashboardData:
        self.get_calls.append(force)
        if self._error is not None:
            raise self._error
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


def _client(provider):
    app = create_app(config=object(), provider=provider)
    app.config.update(TESTING=True)
    return app.test_client()


# --------------------------------------------------------------------------- #
# GET /
# --------------------------------------------------------------------------- #
def test_index_renders_200():
    provider = FakeProvider()
    resp = _client(provider).get("/")
    assert resp.status_code == 200
    assert provider.get_calls == [False]


def test_index_still_200_when_provider_raises():
    provider = FakeProvider(error=RuntimeError("boom"))
    resp = _client(provider).get("/")
    # Route catches the error and still renders the page.
    assert resp.status_code == 200
    assert b"boom" in resp.data


# --------------------------------------------------------------------------- #
# POST /api/refresh
# --------------------------------------------------------------------------- #
def test_refresh_returns_ok_json():
    provider = FakeProvider()
    resp = _client(provider).post("/api/refresh")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["ok"] is True
    assert payload["data"]["accounts"][0]["account_id"] == "111111111111"
    # Forced refresh.
    assert provider.get_calls == [True]


def test_refresh_returns_502_on_provider_error():
    provider = FakeProvider(error=RuntimeError("ce failed"))
    resp = _client(provider).post("/api/refresh")
    assert resp.status_code == 502
    payload = resp.get_json()
    assert payload["ok"] is False
    assert payload["error"] == "ce failed"


def test_refresh_get_not_allowed():
    resp = _client(FakeProvider()).get("/api/refresh")
    assert resp.status_code == 405


# --------------------------------------------------------------------------- #
# POST /credits
# --------------------------------------------------------------------------- #
def test_credits_calls_update_and_redirects():
    provider = FakeProvider()
    resp = _client(provider).post(
        "/credits",
        data={
            "account_id": "111111111111",
            "balance": "42.5",
            "expiry": "2026-12-31",
            "note": "promo",
        },
    )
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/")
    assert provider.update_calls == [
        {
            "account_id": "111111111111",
            "balance": 42.5,
            "expiry": "2026-12-31",
            "note": "promo",
        }
    ]


def test_credits_blank_balance_becomes_none():
    provider = FakeProvider()
    _client(provider).post(
        "/credits",
        data={"account_id": "111111111111", "balance": "", "expiry": "", "note": ""},
    )
    call = provider.update_calls[0]
    assert call["balance"] is None
    assert call["expiry"] is None
    assert call["note"] is None


def test_credits_invalid_balance_becomes_none():
    provider = FakeProvider()
    _client(provider).post(
        "/credits",
        data={"account_id": "111111111111", "balance": "abc"},
    )
    assert provider.update_calls[0]["balance"] is None


def test_credits_no_account_id_skips_update():
    provider = FakeProvider()
    resp = _client(provider).post("/credits", data={"account_id": "  "})
    assert resp.status_code == 302
    assert provider.update_calls == []


@pytest.mark.parametrize("missing", [{}])
def test_credits_missing_account_id_skips_update(missing):
    provider = FakeProvider()
    resp = _client(provider).post("/credits", data=missing)
    assert resp.status_code == 302
    assert provider.update_calls == []
