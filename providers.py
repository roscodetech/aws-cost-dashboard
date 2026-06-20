"""Dashboard data providers.

A provider exposes ``get(force)`` returning a ``DashboardData`` and
``update_credit(...)`` for the manual remaining-balance edits. The Flask app
depends only on this interface, which lets tests/E2E inject a fake provider with
no AWS access.

``LiveProvider`` pulls every account in the config, merges them into one
``DashboardData``, and records per-account failures in ``DashboardData.errors`` so
one bad credential never blanks the whole dashboard.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Protocol

from aws_client import AwsClients, AwsAuthError
from budgets_service import BudgetsService
from cache import DashboardCache
from config import AccountConfig, Config
from cost_service import CostService
from credits_api import CreditsApiService, CreditsApiUnavailable
from credits_store import CreditsStore
from models import AccountCost, BudgetStatus, CreditInfo, DashboardData, ServiceCost
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


@dataclass
class _AccountSlice:
    accounts: tuple[AccountCost, ...]
    by_service: dict[str, tuple[ServiceCost, ...]]
    credits: tuple[CreditInfo, ...]
    budgets: tuple[BudgetStatus, ...]
    currency: str


class LiveProvider:
    """Builds DashboardData across all configured accounts, cached to disk."""

    def __init__(self, config: Config) -> None:
        self._config = config
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
        accounts: list[AccountCost] = []
        by_service: dict[str, tuple[ServiceCost, ...]] = {}
        credits: list[CreditInfo] = []
        budgets: list[BudgetStatus] = []
        errors: list[str] = []
        currency = "USD"

        for account_config in self._config.accounts:
            try:
                part = self._fetch_account(account_config)
            except (AwsAuthError, RuntimeError) as exc:
                errors.append(f"{account_config.label}: {exc}")
                continue
            accounts.extend(part.accounts)
            by_service.update(part.by_service)
            credits.extend(part.credits)
            budgets.extend(part.budgets)
            currency = part.currency or currency

        return DashboardData(
            accounts=tuple(accounts),
            by_service=by_service,
            credits=tuple(credits),
            budgets=tuple(budgets),
            currency=currency,
            refreshed_at=_now_iso(),
            errors=tuple(errors),
        )

    def _fetch_account(self, account_config: AccountConfig) -> _AccountSlice:
        clients = AwsClients(account_config)
        caller_id = clients.validate()
        names = OrgService(clients).account_names()
        if not names:
            # Standalone account: label the single account by its config label.
            names = {caller_id: account_config.label}
        cost = CostService(clients)
        account_costs = cost.account_costs(names)
        account_costs = self._with_history(cost, account_costs)
        by_service = cost.services_by_account()
        applied = cost.credits_applied()
        account_ids = [a.account_id for a in account_costs]
        credits = self._build_credits(clients, caller_id, account_ids, applied)
        budgets = BudgetsService(clients, caller_id).budgets()
        currency = account_costs[0].currency if account_costs else "USD"
        return _AccountSlice(account_costs, by_service, credits, budgets, currency)

    def _with_history(
        self, cost: CostService, account_costs: tuple[AccountCost, ...]
    ) -> tuple[AccountCost, ...]:
        """Merge all-time / last-12-month totals into each AccountCost. History is a
        nice-to-have — if the call fails, return the costs unchanged."""
        try:
            history = cost.historical_totals()
        except RuntimeError:
            return account_costs
        return tuple(
            replace(
                a,
                last_12mo_cost=history.get(a.account_id, {}).get("last_12mo", 0.0),
                all_time_cost=history.get(a.account_id, {}).get("all_time", 0.0),
                history_since=history.get(a.account_id, {}).get("since"),
            )
            for a in account_costs
        )

    def _build_credits(
        self,
        clients: AwsClients,
        caller_account_id: str,
        account_ids: list[str],
        applied: dict[str, float],
    ) -> tuple[CreditInfo, ...]:
        """Prefer authoritative balances from billing:GetCredits; fall back to the
        manual credits.json for any account the API can't (or isn't allowed to)
        cover."""
        api_available = True
        try:
            api = CreditsApiService(clients).credits_by_account(
                caller_account_id, payer_account=len(account_ids) > 1
            )
        except (CreditsApiUnavailable, RuntimeError):
            api = {}
            api_available = False

        manual = {c.account_id: c for c in self._credits.build(applied, account_ids)}
        result: list[CreditInfo] = []
        for acct in account_ids:
            if acct in api:
                a = api[acct]
                result.append(
                    CreditInfo(
                        account_id=acct,
                        applied_mtd=applied.get(acct, 0.0),
                        remaining_balance=a.remaining,
                        expiry=a.earliest_expiry,
                        note=", ".join(a.names) or None,
                        initial_balance=a.initial,
                        estimated_remaining=a.estimated_remaining,
                        source="api",
                    )
                )
            elif api_available:
                # GetCredits succeeded but this account has no credits — an
                # authoritative "none", not a reason to fall back to manual entry.
                result.append(
                    CreditInfo(
                        account_id=acct,
                        applied_mtd=applied.get(acct, 0.0),
                        remaining_balance=None,
                        expiry=None,
                        note=None,
                        source="api",
                    )
                )
            else:
                result.append(manual[acct])
        return tuple(result)

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
                errors=cached.errors,
            )
        )
