"""Manual promotional-credit balance store.

AWS exposes applied credits via Cost Explorer but has no API for the remaining
promotional credit balance, so it is entered manually and persisted to a small
JSON file. This module owns reading/writing that file and combining it with the
live applied-MTD figures into immutable ``CreditInfo`` records.
"""
from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from models import CreditInfo


def _clean(value: str | None) -> str | None:
    """Treat empty/whitespace-only strings as absent."""
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


class CreditsStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    def all(self) -> dict[str, dict]:
        """Read credits.json. Return {} if file missing or unparseable."""
        try:
            raw = self._path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (OSError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        return data

    def update(
        self,
        account_id: str,
        balance: float | None,
        expiry: str | None,
        note: str | None,
    ) -> None:
        """Upsert one account's manual entry and rewrite the whole file."""
        current = self.all()
        entry: dict = {
            "balance": balance,
            "expiry": _clean(expiry),
            "note": _clean(note),
        }
        updated = {**current, account_id: entry}
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(updated, indent=2), encoding="utf-8"
        )

    def build(
        self, applied: dict[str, float], account_ids: Iterable[str]
    ) -> tuple[CreditInfo, ...]:
        """Combine live applied-MTD credits with stored manual balances."""
        stored = self.all()
        return tuple(
            CreditInfo(
                account_id=acct,
                applied_mtd=applied.get(acct, 0.0),
                remaining_balance=stored.get(acct, {}).get("balance"),
                expiry=stored.get(acct, {}).get("expiry"),
                note=stored.get(acct, {}).get("note"),
            )
            for acct in account_ids
        )
