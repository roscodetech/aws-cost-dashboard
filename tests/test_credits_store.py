"""Unit tests for the manual promotional-credit store."""
from __future__ import annotations

import json

from credits_store import CreditsStore
from models import CreditInfo


def test_all_returns_empty_when_file_missing(tmp_path):
    store = CreditsStore(tmp_path / "credits.json")
    assert store.all() == {}


def test_all_returns_empty_when_corrupt(tmp_path):
    path = tmp_path / "credits.json"
    path.write_text("not json", encoding="utf-8")
    assert CreditsStore(path).all() == {}


def test_all_returns_empty_when_not_a_dict(tmp_path):
    path = tmp_path / "credits.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    assert CreditsStore(path).all() == {}


def test_update_then_all_shows_entry(tmp_path):
    path = tmp_path / "credits.json"
    store = CreditsStore(path)
    store.update("111111111111", balance=95.0, expiry="2026-12-31", note="promo")
    assert store.all() == {
        "111111111111": {
            "balance": 95.0,
            "expiry": "2026-12-31",
            "note": "promo",
        }
    }


def test_update_creates_parent_dir(tmp_path):
    path = tmp_path / "nested" / "dir" / "credits.json"
    store = CreditsStore(path)
    store.update("111111111111", balance=10.0, expiry=None, note=None)
    assert path.exists()
    assert json.loads(path.read_text(encoding="utf-8"))["111111111111"]["balance"] == 10.0


def test_update_normalizes_empty_expiry_and_note_to_none(tmp_path):
    store = CreditsStore(tmp_path / "credits.json")
    store.update("111111111111", balance=5.0, expiry="   ", note="")
    entry = store.all()["111111111111"]
    assert entry["expiry"] is None
    assert entry["note"] is None


def test_update_preserves_other_entries(tmp_path):
    store = CreditsStore(tmp_path / "credits.json")
    store.update("111111111111", balance=1.0, expiry=None, note=None)
    store.update("222222222222", balance=2.0, expiry=None, note=None)
    data = store.all()
    assert set(data.keys()) == {"111111111111", "222222222222"}
    assert data["111111111111"]["balance"] == 1.0


def test_build_merges_applied_and_stored_ordered_by_account_ids(tmp_path):
    store = CreditsStore(tmp_path / "credits.json")
    store.update("111111111111", balance=95.0, expiry="2026-12-31", note="promo")
    # 222 has no stored entry; 333 has a stored entry with None balance.
    store.update("333333333333", balance=None, expiry=None, note="manual")

    applied = {"111111111111": 5.0, "222222222222": 3.0}
    account_ids = ["222222222222", "111111111111", "333333333333"]

    result = store.build(applied, account_ids)

    assert isinstance(result, tuple)
    # Ordered by the input account_ids sequence.
    assert [c.account_id for c in result] == account_ids

    by_id = {c.account_id: c for c in result}

    # applied present, no stored entry -> balance None
    assert by_id["222222222222"] == CreditInfo(
        account_id="222222222222",
        applied_mtd=3.0,
        remaining_balance=None,
        expiry=None,
        note=None,
    )
    # applied present + stored balance/expiry/note
    assert by_id["111111111111"] == CreditInfo(
        account_id="111111111111",
        applied_mtd=5.0,
        remaining_balance=95.0,
        expiry="2026-12-31",
        note="promo",
    )
    # not in applied -> applied_mtd defaults to 0.0; stored balance None preserved
    assert by_id["333333333333"] == CreditInfo(
        account_id="333333333333",
        applied_mtd=0.0,
        remaining_balance=None,
        expiry=None,
        note="manual",
    )


def test_build_balance_none_preserved_distinct_from_missing(tmp_path):
    """A stored explicit None balance and a missing entry both yield None."""
    store = CreditsStore(tmp_path / "credits.json")
    store.update("111111111111", balance=None, expiry=None, note=None)
    result = store.build({}, ["111111111111", "999999999999"])
    by_id = {c.account_id: c for c in result}
    assert by_id["111111111111"].remaining_balance is None
    assert by_id["999999999999"].remaining_balance is None


def test_build_empty_account_ids_returns_empty_tuple(tmp_path):
    store = CreditsStore(tmp_path / "credits.json")
    assert store.build({"x": 1.0}, []) == ()
