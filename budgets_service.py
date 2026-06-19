"""Budgets lookup against the payer/management account (optional feature).

Budgets live only on the payer account and require ``budgets:ViewBudget``. When
that permission or the budgets feature is absent, this service degrades quietly
to an empty result rather than failing the whole dashboard refresh.
"""
from __future__ import annotations

from botocore.exceptions import BotoCoreError, ClientError

from aws_client import AwsClients
from models import BudgetStatus


def _amount(value: dict, *keys: str) -> float:
    node: object = value
    for key in keys:
        if not isinstance(node, dict):
            return 0.0
        node = node.get(key, {})
    try:
        return float(node)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


class BudgetsService:
    """Reads AWS Budgets for the payer account."""

    def __init__(self, clients: AwsClients, account_id: str) -> None:
        """account_id is the payer/management account id."""
        self._clients = clients
        self._account_id = account_id

    def budgets(self) -> tuple[BudgetStatus, ...]:
        """Return all budgets for the payer account as an immutable tuple.

        Degrades to an empty tuple when budgets are unavailable or access is denied.
        """
        try:
            paginator = self._clients.budgets.get_paginator("describe_budgets")
            results: list[BudgetStatus] = []
            for page in paginator.paginate(AccountId=self._account_id):
                for budget in page.get("Budgets", ()):
                    results.append(
                        BudgetStatus(
                            name=budget["BudgetName"],
                            account_id=self._account_id,
                            limit=_amount(budget.get("BudgetLimit", {}), "Amount"),
                            actual=_amount(
                                budget, "CalculatedSpend", "ActualSpend", "Amount"
                            ),
                            forecasted=_amount(
                                budget, "CalculatedSpend", "ForecastedSpend", "Amount"
                            ),
                        )
                    )
            return tuple(results)
        except (ClientError, BotoCoreError):
            return ()
