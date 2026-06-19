"""Immutable data models for the dashboard.

All models are frozen dataclasses. JSON (de)serialization helpers live here so the
cache layer and Flask routes can round-trip a ``DashboardData`` without scattering
serialization logic across modules.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


@dataclass(frozen=True)
class AccountCost:
    account_id: str
    name: str
    mtd_cost: float
    last_month_cost: float
    forecast: float
    currency: str


@dataclass(frozen=True)
class ServiceCost:
    service: str
    amount: float


@dataclass(frozen=True)
class CreditInfo:
    account_id: str
    applied_mtd: float
    remaining_balance: float | None
    expiry: str | None
    note: str | None


@dataclass(frozen=True)
class BudgetStatus:
    name: str
    account_id: str
    limit: float
    actual: float
    forecasted: float


@dataclass(frozen=True)
class DashboardData:
    accounts: tuple[AccountCost, ...]
    by_service: dict[str, tuple[ServiceCost, ...]]  # account_id -> services
    credits: tuple[CreditInfo, ...]
    budgets: tuple[BudgetStatus, ...]
    currency: str
    refreshed_at: str  # ISO-8601 UTC

    def to_dict(self) -> dict[str, Any]:
        return {
            "accounts": [asdict(a) for a in self.accounts],
            "by_service": {
                acct: [asdict(s) for s in services]
                for acct, services in self.by_service.items()
            },
            "credits": [asdict(c) for c in self.credits],
            "budgets": [asdict(b) for b in self.budgets],
            "currency": self.currency,
            "refreshed_at": self.refreshed_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DashboardData":
        return cls(
            accounts=tuple(AccountCost(**a) for a in data["accounts"]),
            by_service={
                acct: tuple(ServiceCost(**s) for s in services)
                for acct, services in data["by_service"].items()
            },
            credits=tuple(CreditInfo(**c) for c in data["credits"]),
            budgets=tuple(BudgetStatus(**b) for b in data["budgets"]),
            currency=data["currency"],
            refreshed_at=data["refreshed_at"],
        )

    @property
    def total_mtd(self) -> float:
        return round(sum(a.mtd_cost for a in self.accounts), 2)

    @property
    def total_forecast(self) -> float:
        return round(sum(a.forecast for a in self.accounts), 2)
