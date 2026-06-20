"""Unit tests for LiveProvider's multi-account merge and error isolation.

No real AWS is touched: ``_fetch_account`` (the only method that builds AwsClients
and calls billing APIs) is monkeypatched with a fake that returns a deterministic
``_AccountSlice`` for good accounts and raises for the bad one. ``_build()`` is
exercised directly so cache freshness never interferes.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from config import AccountConfig, Config
from models import AccountCost, BudgetStatus, CreditInfo, ServiceCost
from providers import LiveProvider, _AccountSlice


def _config(tmp_path: Path, *labels: str) -> Config:
    return Config(
        accounts=tuple(
            AccountConfig(label=l, access_key_id="x", secret_access_key="y")
            for l in labels
        ),
        cache_ttl_seconds=3600,
        cache_path=tmp_path / "cache.json",
        credits_path=tmp_path / "credits.json",
        host="127.0.0.1",
        port=0,
    )


def _slice_for(label: str) -> _AccountSlice:
    """A unique slice keyed off the account label so merges are observable."""
    acct_id = label * 12  # e.g. "prod" -> distinct id-ish string
    account = AccountCost(acct_id, label, 100.0, 90.0, 110.0, "USD")
    services = (ServiceCost("EC2", 100.0),)
    credit = CreditInfo(acct_id, 0.0, None, None, None)
    budget = BudgetStatus(f"{label}-budget", acct_id, 200.0, 100.0, 110.0)
    return _AccountSlice(
        accounts=(account,),
        by_service={acct_id: services},
        credits=(credit,),
        budgets=(budget,),
        currency="USD",
    )


def test_build_merges_all_good_accounts(tmp_path):
    cfg = _config(tmp_path, "prod", "staging", "dev")
    provider = LiveProvider(cfg)

    def fake_fetch(account_config: AccountConfig) -> _AccountSlice:
        return _slice_for(account_config.label)

    provider._fetch_account = fake_fetch  # type: ignore[assignment]

    data = provider._build()

    labels = {a.name for a in data.accounts}
    assert labels == {"prod", "staging", "dev"}
    # by_service dicts merged across accounts.
    assert set(data.by_service.keys()) == {
        "prod" * 12,
        "staging" * 12,
        "dev" * 12,
    }
    assert len(data.credits) == 3
    assert len(data.budgets) == 3
    assert data.errors == ()


def test_build_isolates_failing_account(tmp_path):
    cfg = _config(tmp_path, "good", "bad", "alsogood")
    provider = LiveProvider(cfg)

    def fake_fetch(account_config: AccountConfig) -> _AccountSlice:
        if account_config.label == "bad":
            raise RuntimeError("access denied for billing")
        return _slice_for(account_config.label)

    provider._fetch_account = fake_fetch  # type: ignore[assignment]

    data = provider._build()

    # Good accounts still present despite the failure.
    names = {a.name for a in data.accounts}
    assert names == {"good", "alsogood"}
    assert set(data.by_service.keys()) == {"good" * 12, "alsogood" * 12}

    # The failing account's message is recorded, prefixed with its label.
    assert len(data.errors) == 1
    assert data.errors[0].startswith("bad: ")
    assert "access denied for billing" in data.errors[0]


def test_build_all_accounts_fail(tmp_path):
    cfg = _config(tmp_path, "one", "two")
    provider = LiveProvider(cfg)

    def fake_fetch(account_config: AccountConfig) -> _AccountSlice:
        raise RuntimeError(f"boom-{account_config.label}")

    provider._fetch_account = fake_fetch  # type: ignore[assignment]

    data = provider._build()

    assert data.accounts == ()
    assert data.by_service == {}
    assert data.credits == ()
    assert data.budgets == ()
    assert len(data.errors) == 2
    assert data.errors[0].startswith("one: ")
    assert data.errors[1].startswith("two: ")
    # Currency defaults to USD when no account succeeds.
    assert data.currency == "USD"
