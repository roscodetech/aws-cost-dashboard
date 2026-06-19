"""AWS promotional credits via the Billing ``GetCredits`` API.

``billing:GetCredits`` is a real, IAM-authenticated API (service ``billing``,
api version 2023-09-07, JSON 1.0, target prefix ``AWSBilling``). The currently
published botocore (1.43.34) does not yet model the operation, so this issues a
SigV4-signed request directly to the billing endpoint and parses the response.

Returns authoritative per-account credit figures (initial / remaining / estimated
remaining / expiry) — the data the console Credits page shows, which Cost Explorer
does not expose. Raises ``CreditsApiUnavailable`` when the IAM principal lacks the
permission, so callers can fall back to manual entry.
"""
from __future__ import annotations

import datetime as dt
import json
import urllib.error
import urllib.request
from dataclasses import dataclass

from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

from aws_client import AwsClients

# Billing uses AWS's newer dual-stack endpoint, not *.amazonaws.com.
_ENDPOINT = "https://billing.us-east-1.api.aws"
_SIGNING_NAME = "billing"
_SIGNING_REGION = "us-east-1"
_TARGET = "AWSBilling.GetCredits"
_LOOKBACK_DAYS = 364  # startDate must be < 1 year before now
_TIMEOUT = 30


class CreditsApiUnavailable(RuntimeError):
    """Raised when GetCredits is not callable (missing IAM permission)."""


@dataclass(frozen=True)
class AccountCredits:
    account_id: str
    initial: float
    remaining: float
    estimated_remaining: float
    earliest_expiry: str | None  # ISO date
    names: tuple[str, ...]


def _amount(value: dict | None) -> float:
    if not value:
        return 0.0
    try:
        return float(value.get("currencyAmount", 0.0))
    except (TypeError, ValueError):
        return 0.0


def _epoch_to_iso_date(value: object) -> str | None:
    if value is None:
        return None
    try:
        return dt.datetime.fromtimestamp(
            float(value), tz=dt.timezone.utc
        ).date().isoformat()
    except (TypeError, ValueError, OSError):
        return None


def parse_credits(payload: dict) -> dict[str, AccountCredits]:
    """Aggregate the GetCredits response into one record per account id."""
    by_account: dict[str, dict] = {}
    for credit in payload.get("credits", []):
        acct = credit.get("accountId") or ""
        agg = by_account.setdefault(
            acct,
            {"initial": 0.0, "remaining": 0.0, "estimated": 0.0,
             "expiry": None, "names": []},
        )
        agg["initial"] += _amount(credit.get("initialAmount"))
        agg["remaining"] += _amount(credit.get("remainingAmount"))
        agg["estimated"] += _amount(credit.get("estimatedAmount"))
        expiry = _epoch_to_iso_date(credit.get("endDate"))
        if expiry and (agg["expiry"] is None or expiry < agg["expiry"]):
            agg["expiry"] = expiry
        name = credit.get("description")
        if name:
            agg["names"].append(name)
    return {
        acct: AccountCredits(
            account_id=acct,
            initial=round(a["initial"], 2),
            remaining=round(a["remaining"], 2),
            estimated_remaining=round(a["estimated"], 2),
            earliest_expiry=a["expiry"],
            names=tuple(a["names"]),
        )
        for acct, a in by_account.items()
    }


class CreditsApiService:
    """Calls billing:GetCredits via a signed request and parses the result."""

    def __init__(self, clients: AwsClients) -> None:
        self._clients = clients

    def credits_by_account(
        self, account_id: str, payer_account: bool = False
    ) -> dict[str, AccountCredits]:
        return parse_credits(self._call(account_id, payer_account))

    def _call(self, account_id: str, payer_account: bool) -> dict:
        now = dt.datetime.now(dt.timezone.utc)
        body = json.dumps(
            {
                "accountId": account_id,
                "startDate": int((now - dt.timedelta(days=_LOOKBACK_DAYS)).timestamp()),
                "endDate": int(now.timestamp()),
                "payerAccountFlag": payer_account,
            }
        )
        creds = self._clients.session.get_credentials().get_frozen_credentials()
        request = AWSRequest(
            method="POST",
            url=_ENDPOINT,
            data=body,
            headers={
                "Content-Type": "application/x-amz-json-1.0",
                "X-Amz-Target": _TARGET,
            },
        )
        SigV4Auth(creds, _SIGNING_NAME, _SIGNING_REGION).add_auth(request)
        prepared = request.prepare()
        payload = prepared.body
        if isinstance(payload, str):
            payload = payload.encode("utf-8")
        http_request = urllib.request.Request(
            prepared.url, data=payload, headers=dict(prepared.headers), method="POST"
        )
        try:
            with urllib.request.urlopen(http_request, timeout=_TIMEOUT) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            text = exc.read().decode(errors="replace")
            if "AccessDenied" in text or exc.code == 403:
                raise CreditsApiUnavailable(
                    "billing:GetCredits is not permitted for this IAM principal. "
                    "Add it to the policy (see iam-policy.json) to show real credit "
                    "balances; falling back to manual entry until then."
                ) from exc
            raise RuntimeError(f"GetCredits failed (HTTP {exc.code}): {text}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"GetCredits request failed: {exc}") from exc
