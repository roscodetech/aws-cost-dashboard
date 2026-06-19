"""Cost Explorer queries for the consolidated-billing dashboard (system boundary).

One payer account; per-linked-account spend is pulled via the Cost Explorer ``ce``
client and shaped into the immutable models the routes consume. AWS errors are
wrapped in clear ``RuntimeError`` messages, except forecasts which degrade to 0.0.
"""
from __future__ import annotations

from datetime import date

from botocore.exceptions import BotoCoreError, ClientError

from aws_client import AwsClients
from models import AccountCost, ServiceCost

_METRIC = "UnblendedCost"
_LINKED_ACCOUNT = {"Type": "DIMENSION", "Key": "LINKED_ACCOUNT"}
_SERVICE = {"Type": "DIMENSION", "Key": "SERVICE"}
_DEFAULT_CURRENCY = "USD"


def _first_of_month(d: date) -> date:
    return d.replace(day=1)


def _first_of_next_month(d: date) -> date:
    if d.month == 12:
        return date(d.year + 1, 1, 1)
    return date(d.year, d.month + 1, 1)


def _first_of_last_month(d: date) -> date:
    first = _first_of_month(d)
    if first.month == 1:
        return date(first.year - 1, 12, 1)
    return date(first.year, first.month - 1, 1)


def _iso(d: date) -> str:
    return d.isoformat()


def _amount(metric: dict) -> float:
    return float(metric["UnblendedCost"]["Amount"])


def _unit(metric: dict) -> str:
    return metric["UnblendedCost"].get("Unit", _DEFAULT_CURRENCY)


class CostService:
    """Reads consolidated cost data from Cost Explorer into immutable models."""

    def __init__(self, clients: AwsClients) -> None:
        self._ce = clients.cost_explorer

    def account_costs(self, names: dict[str, str]) -> tuple[AccountCost, ...]:
        today = date.today()
        try:
            resp = self._ce.get_cost_and_usage(
                TimePeriod={
                    "Start": _iso(_first_of_last_month(today)),
                    "End": _iso(today),
                },
                Granularity="MONTHLY",
                Metrics=[_METRIC],
                GroupBy=[_LINKED_ACCOUNT],
            )
        except (ClientError, BotoCoreError) as exc:
            raise RuntimeError(f"Failed to fetch account costs: {exc}") from exc

        buckets = resp.get("ResultsByTime", [])
        last_month = buckets[0]["Groups"] if buckets else []
        current = buckets[1]["Groups"] if len(buckets) > 1 else []

        last_by_id = {g["Keys"][0]: g for g in last_month}
        current_by_id = {g["Keys"][0]: g for g in current}

        costs = []
        for account_id in last_by_id.keys() | current_by_id.keys():
            last_g = last_by_id.get(account_id)
            cur_g = current_by_id.get(account_id)
            currency = _unit(cur_g["Metrics"]) if cur_g else (
                _unit(last_g["Metrics"]) if last_g else _DEFAULT_CURRENCY
            )
            costs.append(
                AccountCost(
                    account_id=account_id,
                    name=names.get(account_id, account_id),
                    mtd_cost=_amount(cur_g["Metrics"]) if cur_g else 0.0,
                    last_month_cost=_amount(last_g["Metrics"]) if last_g else 0.0,
                    forecast=self._forecast(account_id),
                    currency=currency,
                )
            )
        return tuple(sorted(costs, key=lambda c: c.mtd_cost, reverse=True))

    def services_by_account(self) -> dict[str, tuple[ServiceCost, ...]]:
        today = date.today()
        try:
            resp = self._ce.get_cost_and_usage(
                TimePeriod={
                    "Start": _iso(_first_of_month(today)),
                    "End": _iso(today),
                },
                Granularity="MONTHLY",
                Metrics=[_METRIC],
                GroupBy=[_LINKED_ACCOUNT, _SERVICE],
            )
        except (ClientError, BotoCoreError) as exc:
            raise RuntimeError(f"Failed to fetch services by account: {exc}") from exc

        grouped: dict[str, list[ServiceCost]] = {}
        for bucket in resp.get("ResultsByTime", []):
            for group in bucket.get("Groups", []):
                account_id, service = group["Keys"]
                grouped.setdefault(account_id, []).append(
                    ServiceCost(service=service, amount=_amount(group["Metrics"]))
                )
        return {
            account_id: tuple(
                sorted(services, key=lambda s: s.amount, reverse=True)
            )
            for account_id, services in grouped.items()
        }

    def credits_applied(self) -> dict[str, float]:
        today = date.today()
        try:
            resp = self._ce.get_cost_and_usage(
                TimePeriod={
                    "Start": _iso(_first_of_month(today)),
                    "End": _iso(today),
                },
                Granularity="MONTHLY",
                Metrics=[_METRIC],
                GroupBy=[_LINKED_ACCOUNT],
                Filter={"Dimensions": {"Key": "RECORD_TYPE", "Values": ["Credit"]}},
            )
        except (ClientError, BotoCoreError) as exc:
            raise RuntimeError(f"Failed to fetch credits: {exc}") from exc

        credits: dict[str, float] = {}
        for bucket in resp.get("ResultsByTime", []):
            for group in bucket.get("Groups", []):
                credits[group["Keys"][0]] = abs(_amount(group["Metrics"]))
        return credits

    def _forecast(self, account_id: str) -> float:
        today = date.today()
        start, end = today, _first_of_next_month(today)
        if start >= end:
            return 0.0
        try:
            resp = self._ce.get_cost_forecast(
                TimePeriod={"Start": _iso(start), "End": _iso(end)},
                Metric="UNBLENDED_COST",
                Granularity="MONTHLY",
                Filter={
                    "Dimensions": {
                        "Key": "LINKED_ACCOUNT",
                        "Values": [account_id],
                    }
                },
            )
            return float(resp["Total"]["Amount"])
        except (ClientError, BotoCoreError):
            return 0.0
