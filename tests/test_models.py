"""Unit tests for the immutable data models."""
from __future__ import annotations

from models import (
    AccountCost,
    BudgetStatus,
    CreditInfo,
    DashboardData,
    ServiceCost,
)


def _sample() -> DashboardData:
    return DashboardData(
        accounts=(
            AccountCost(
                account_id="111111111111",
                name="prod",
                mtd_cost=120.5,
                last_month_cost=300.0,
                forecast=250.25,
                currency="USD",
            ),
            AccountCost(
                account_id="222222222222",
                name="dev",
                mtd_cost=10.0,
                last_month_cost=20.0,
                forecast=12.75,
                currency="USD",
            ),
        ),
        by_service={
            "111111111111": (
                ServiceCost(service="EC2", amount=100.0),
                ServiceCost(service="S3", amount=20.5),
            ),
            "222222222222": (ServiceCost(service="Lambda", amount=10.0),),
        },
        credits=(
            CreditInfo(
                account_id="111111111111",
                applied_mtd=5.0,
                remaining_balance=95.0,
                expiry="2026-12-31",
                note="promo",
            ),
            CreditInfo(
                account_id="222222222222",
                applied_mtd=0.0,
                remaining_balance=None,
                expiry=None,
                note=None,
            ),
        ),
        budgets=(
            BudgetStatus(
                name="monthly",
                account_id="111111111111",
                limit=500.0,
                actual=120.5,
                forecasted=250.25,
            ),
        ),
        currency="USD",
        refreshed_at="2026-06-20T00:00:00+00:00",
    )


def test_round_trip_to_dict_from_dict_equal():
    original = _sample()
    restored = DashboardData.from_dict(original.to_dict())
    assert restored == original


def test_to_dict_is_json_shaped():
    d = _sample().to_dict()
    assert isinstance(d["accounts"], list)
    assert isinstance(d["by_service"], dict)
    assert isinstance(d["by_service"]["111111111111"], list)
    assert d["accounts"][0]["account_id"] == "111111111111"
    assert d["currency"] == "USD"


def test_total_mtd_sums_and_rounds():
    data = _sample()
    # 120.5 + 10.0 = 130.5
    assert data.total_mtd == 130.5


def test_total_forecast_sums_and_rounds():
    data = _sample()
    # 250.25 + 12.75 = 263.0
    assert data.total_forecast == 263.0


def test_totals_round_to_two_places():
    data = DashboardData(
        accounts=(
            AccountCost("a", "a", 0.1, 0.0, 0.001, "USD"),
            AccountCost("b", "b", 0.2, 0.0, 0.002, "USD"),
        ),
        by_service={},
        credits=(),
        budgets=(),
        currency="USD",
        refreshed_at="2026-06-20T00:00:00+00:00",
    )
    assert data.total_mtd == 0.3
    assert data.total_forecast == 0.0


def test_empty_dashboard_round_trips():
    empty = DashboardData(
        accounts=(),
        by_service={},
        credits=(),
        budgets=(),
        currency="USD",
        refreshed_at="2026-06-20T00:00:00+00:00",
    )
    assert DashboardData.from_dict(empty.to_dict()) == empty
    assert empty.total_mtd == 0.0
    assert empty.total_forecast == 0.0
