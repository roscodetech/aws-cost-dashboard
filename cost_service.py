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


def _months_back(d: date, n: int) -> date:
    """First day of the month n months before d's month."""
    total = (d.year * 12 + (d.month - 1)) - n
    return date(total // 12, total % 12 + 1, 1)


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

    def historical_totals(self) -> dict[str, dict]:
        """Per-account all-time and trailing-12-month spend.

        Pulls the widest monthly window Cost Explorer allows. AWS caps the API at
        14 months unless 'historical data beyond 14 months' is enabled (up to 38);
        we probe wide and fall back to 14 months so the dashboard uses whatever is
        available. Returns ``{account_id: {all_time, last_12mo, since}}``.
        """
        today = date.today()
        # Widest first; step in on the "beyond N months" cap. 13 is the safe floor
        # (14 lands exactly on the boundary and re-errors). Captures a 24-month
        # enablement if present, else falls back to the default ~14-month window.
        for months in (38, 24, 13):
            start = _months_back(today, months)
            try:
                resp = self._ce.get_cost_and_usage(
                    TimePeriod={"Start": _iso(start), "End": _iso(today)},
                    Granularity="MONTHLY",
                    Metrics=[_METRIC],
                    GroupBy=[_LINKED_ACCOUNT],
                )
                break
            except ClientError as exc:
                if "14 months" in exc.response.get("Error", {}).get("Message", ""):
                    continue  # extended history not enabled — fall back to 14
                raise RuntimeError(f"Failed to fetch history: {exc}") from exc
            except BotoCoreError as exc:
                raise RuntimeError(f"Failed to fetch history: {exc}") from exc
        else:
            return {}

        # account_id -> ordered list of (month, amount)
        series: dict[str, list[tuple[str, float]]] = {}
        for bucket in resp.get("ResultsByTime", []):
            month = bucket["TimePeriod"]["Start"][:7]
            for group in bucket.get("Groups", []):
                series.setdefault(group["Keys"][0], []).append(
                    (month, _amount(group["Metrics"]))
                )

        totals: dict[str, dict] = {}
        for account_id, rows in series.items():
            billed = [m for m, v in rows if v > 0.005]
            totals[account_id] = {
                "all_time": round(sum(v for _, v in rows), 2),
                "last_12mo": round(sum(v for _, v in rows[-12:]), 2),
                "since": billed[0] if billed else (rows[0][0] if rows else None),
            }
        return totals

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
