"""Tests for the billing:GetCredits parsing and signed-call error handling."""
from __future__ import annotations

import datetime as dt
import io
import json
import urllib.error
from types import SimpleNamespace

import pytest

import credits_api
from credits_api import CreditsApiService, CreditsApiUnavailable, parse_credits


def _epoch(y: int, m: int, d: int) -> int:
    return int(dt.datetime(y, m, d, tzinfo=dt.timezone.utc).timestamp())

# Mirrors the user's console Credits page: AWS Activate - Founders,
# $1,000 issued, $240.26 remaining, $196.72 estimated remaining, expires 2027-07-31.
_PAYLOAD = {
    "credits": [
        {
            "accountId": "055706347991",
            "creditId": "10050657117",
            "description": "AWS Activate - Founders",
            "creditStatus": "Active",
            "initialAmount": {"currencyAmount": "1000.00", "currencyCode": "USD"},
            "remainingAmount": {"currencyAmount": "240.26", "currencyCode": "USD"},
            "estimatedAmount": {"currencyAmount": "196.72", "currencyCode": "USD"},
            "endDate": _epoch(2027, 7, 31),
        }
    ]
}


def test_parse_maps_console_values():
    result = parse_credits(_PAYLOAD)
    assert set(result) == {"055706347991"}
    c = result["055706347991"]
    assert c.initial == 1000.00
    assert c.remaining == 240.26
    assert c.estimated_remaining == 196.72
    assert c.names == ("AWS Activate - Founders",)
    assert c.earliest_expiry == "2027-07-31"


def test_parse_aggregates_multiple_credits_per_account():
    payload = {
        "credits": [
            {"accountId": "111", "description": "A",
             "initialAmount": {"currencyAmount": "100"},
             "remainingAmount": {"currencyAmount": "40"},
             "estimatedAmount": {"currencyAmount": "35"}, "endDate": _epoch(2027, 7, 31)},
            {"accountId": "111", "description": "B",
             "initialAmount": {"currencyAmount": "50"},
             "remainingAmount": {"currencyAmount": "10"},
             "estimatedAmount": {"currencyAmount": "9"}, "endDate": _epoch(2026, 9, 1)},
        ]
    }
    c = parse_credits(payload)["111"]
    assert c.initial == 150.0
    assert c.remaining == 50.0
    assert c.names == ("A", "B")
    # earliest of the two expiries wins
    assert c.earliest_expiry == "2026-09-01"


def test_parse_empty():
    assert parse_credits({"credits": []}) == {}
    assert parse_credits({}) == {}


def _fake_clients():
    frozen = SimpleNamespace(access_key="AKIA", secret_key="secret", token=None)
    creds = SimpleNamespace(get_frozen_credentials=lambda: frozen)
    session = SimpleNamespace(get_credentials=lambda: creds)
    return SimpleNamespace(session=session)


def test_access_denied_maps_to_unavailable(monkeypatch):
    def raise_403(*_a, **_k):
        raise urllib.error.HTTPError(
            "url", 400, "Bad Request", {},
            io.BytesIO(json.dumps(
                {"__type": "AccessDeniedException", "Message": "not authorized"}
            ).encode()),
        )

    monkeypatch.setattr(credits_api.urllib.request, "urlopen", raise_403)
    with pytest.raises(CreditsApiUnavailable):
        CreditsApiService(_fake_clients()).credits_by_account("055706347991")


def test_successful_call_parses(monkeypatch):
    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return json.dumps(_PAYLOAD).encode()

    monkeypatch.setattr(credits_api.urllib.request, "urlopen", lambda *a, **k: _Resp())
    out = CreditsApiService(_fake_clients()).credits_by_account("055706347991")
    assert out["055706347991"].remaining == 240.26
