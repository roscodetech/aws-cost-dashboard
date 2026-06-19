"""Dashboard data providers.

A provider exposes ``get(force)`` returning a ``DashboardData`` and
``update_credit(...)`` for the manual remaining-balance edits. The Flask app
depends only on this interface, which lets tests/E2E inject a fake provider with
no AWS access.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol

from aws_client import AwsClients
from budgets_service import BudgetsService
from cache import DashboardCache
from config import Config
from cost_service import CostService
from credits_store import CreditsStore
from models import DashboardData
from org_service import OrgService


class DashboardProvider(Protocol):
    def get(self, force: bool = False) -> DashboardData: ...
    def update_credit(
        self,
        account_id: str,
        balance: float | None,
        expiry: str | None,
        note: str | None,
    ) -> None: ...


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class LiveProvider:
    """Builds DashboardData from AWS, cached to disk to limit Cost Explorer calls."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._clients = AwsClients(config)
        self._cache = DashboardCache(config.cache_path, config.cache_ttl_seconds)
        self._credits = CreditsStore(config.credits_path)

    def get(self, force: bool = False) -> DashboardData:
        if not force and self._cache.is_fresh():
            cached = self._cache.read()
            if cached is not None:
                return cached
        data = self._build()
        self._cache.write(data)
        return data

    def _build(self) -> DashboardData:
        account_id = self._clients.validate()
        names = OrgService(self._clients).account_names()
        if not names:
            # Standalone account (no Organization): label the single account by id.
            names = {account_id: f"AWS account {account_id}"}
        cost = CostService(self._clients)
        accounts = cost.account_costs(names)
        by_service = cost.services_by_account()
        applied = cost.credits_applied()
        credits = self._credits.build(applied, [a.account_id for a in accounts])
        budgets = BudgetsService(self._clients, account_id).budgets()
        currency = accounts[0].currency if accounts else "USD"
        return DashboardData(
            accounts=accounts,
            by_service=by_service,
            credits=credits,
            budgets=budgets,
            currency=currency,
            refreshed_at=_now_iso(),
        )

    def update_credit(
        self,
        account_id: str,
        balance: float | None,
        expiry: str | None,
        note: str | None,
    ) -> None:
        """Persist the manual entry and patch the cached snapshot in place so the
        edit shows immediately without triggering a fresh (billed) CE pull."""
        self._credits.update(account_id, balance, expiry, note)
        cached = self._cache.read()
        if cached is None:
            return
        patched = self._credits.build(
            {c.account_id: c.applied_mtd for c in cached.credits},
            [c.account_id for c in cached.credits],
        )
        self._cache.write(
            DashboardData(
                accounts=cached.accounts,
                by_service=cached.by_service,
                credits=patched,
                budgets=cached.budgets,
                currency=cached.currency,
                refreshed_at=cached.refreshed_at,
            )
        )
