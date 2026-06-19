"""Organization account lookups (system boundary).

Resolves the {account_id: account_name} map the cost views use to label spend
by account. Standalone accounts (not part of an Organization) simply return an
empty map, and the caller falls back to labelling the single account by id.
"""
from __future__ import annotations

from botocore.exceptions import BotoCoreError, ClientError

from aws_client import AwsClients

# Errors that mean "this account isn't an Organizations member" rather than a
# real failure — treated as single-account mode, not an error.
_STANDALONE_ERRORS = {
    "AWSOrganizationsNotInUseException",
    "AccessDeniedException",
    "AccessDenied",
}


class OrgService:
    """Reads account metadata from AWS Organizations, if any."""

    def __init__(self, clients: AwsClients) -> None:
        self._clients = clients

    def account_names(self) -> dict[str, str]:
        """Return {account_id: account_name} for all accounts in the org.

        Returns an empty dict when the account is standalone (no Organization)
        or lacks Organizations read access — the dashboard then runs in
        single-account mode.
        """
        try:
            paginator = self._clients.organizations.get_paginator("list_accounts")
            return {
                account["Id"]: account["Name"]
                for page in paginator.paginate()
                for account in page["Accounts"]
            }
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in _STANDALONE_ERRORS:
                return {}
            raise RuntimeError(f"Failed to list organization accounts: {exc}") from exc
        except BotoCoreError as exc:
            raise RuntimeError(f"Failed to list organization accounts: {exc}") from exc
