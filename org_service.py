"""Organization account lookups (system boundary).

Resolves the {account_id: account_name} map the cost views use to label spend
by account, paging through the Organizations API and failing loudly if it can't.
"""
from __future__ import annotations

from botocore.exceptions import BotoCoreError, ClientError

from aws_client import AwsClients


class OrgService:
    """Reads account metadata from AWS Organizations."""

    def __init__(self, clients: AwsClients) -> None:
        self._clients = clients

    def account_names(self) -> dict[str, str]:
        """Return {account_id: account_name} for all accounts in the org."""
        try:
            paginator = self._clients.organizations.get_paginator("list_accounts")
            return {
                account["Id"]: account["Name"]
                for page in paginator.paginate()
                for account in page["Accounts"]
            }
        except (ClientError, BotoCoreError) as exc:
            raise RuntimeError(
                f"Failed to list organization accounts: {exc}"
            ) from exc
