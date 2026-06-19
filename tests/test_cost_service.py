"""Unit tests for CostService using botocore Stubber against a real ce client.

Stubber matches queued responses to calls in order, so each test queues exactly the
ce calls the method under test will make. ``account_costs`` makes one
``get_cost_and_usage`` call followed by one ``get_cost_forecast`` per account, so
those forecast calls are queued after the usage response in the order the accounts
are iterated.
"""
from __future__ import annotations

from types import SimpleNamespace

import boto3
import pytest
from botocore.stub import Stubber

from cost_service import CostService


@pytest.fixture
def ce():
    return boto3.client(
        "ce",
        region_name="us-east-1",
        aws_access_key_id="x",
        aws_secret_access_key="x",
    )


def _clients(ce):
    """A minimal fake AwsClients exposing only .cost_explorer."""
    return SimpleNamespace(cost_explorer=ce)


def _metric(amount: str, unit: str = "USD") -> dict:
    return {"UnblendedCost": {"Amount": amount, "Unit": unit}}


def _forecast_response(amount: str) -> dict:
    return {
        "Total": {"Amount": amount, "Unit": "USD"},
        "ForecastResultsByTime": [],
    }


# --------------------------------------------------------------------------- #
# account_costs
# --------------------------------------------------------------------------- #
def test_account_costs_maps_sorts_and_reads_currency(ce):
    """Two ResultsByTime buckets: [0]=last month, [1]=current (MTD)."""
    usage = {
        "ResultsByTime": [
            {  # last month
                "Groups": [
                    {"Keys": ["111111111111"], "Metrics": _metric("300.0")},
                    {"Keys": ["222222222222"], "Metrics": _metric("50.0")},
                ]
            },
            {  # current month-to-date
                "Groups": [
                    {"Keys": ["111111111111"], "Metrics": _metric("120.5")},
                    {"Keys": ["222222222222"], "Metrics": _metric("200.0")},
                ]
            },
        ]
    }

    stubber = Stubber(ce)
    stubber.add_response("get_cost_and_usage", usage)
    # account_costs calls _forecast once per account. The iteration order over a
    # set is not deterministic, so stub both forecasts and assert mapping by id.
    stubber.add_response("get_cost_forecast", _forecast_response("10.0"))
    stubber.add_response("get_cost_forecast", _forecast_response("20.0"))

    with stubber:
        service = CostService(_clients(ce))
        result = service.account_costs({"111111111111": "prod"})

    by_id = {a.account_id: a for a in result}

    # Currency read from Unit.
    assert by_id["111111111111"].currency == "USD"
    # mtd from current bucket, last_month from first bucket.
    assert by_id["111111111111"].mtd_cost == 120.5
    assert by_id["111111111111"].last_month_cost == 300.0
    assert by_id["222222222222"].mtd_cost == 200.0
    assert by_id["222222222222"].last_month_cost == 50.0
    # name resolved from the names map, fallback to id.
    assert by_id["111111111111"].name == "prod"
    assert by_id["222222222222"].name == "222222222222"
    # Sorted by mtd descending: 222 (200) before 111 (120.5).
    assert [a.account_id for a in result] == ["222222222222", "111111111111"]
    stubber.assert_no_pending_responses()


def test_account_costs_currency_from_unit_field(ce):
    usage = {
        "ResultsByTime": [
            {"Groups": []},
            {
                "Groups": [
                    {"Keys": ["111111111111"], "Metrics": _metric("9.0", unit="EUR")},
                ]
            },
        ]
    }
    stubber = Stubber(ce)
    stubber.add_response("get_cost_and_usage", usage)
    stubber.add_response("get_cost_forecast", _forecast_response("1.0"))
    with stubber:
        result = CostService(_clients(ce)).account_costs({})
    assert result[0].currency == "EUR"
    stubber.assert_no_pending_responses()


def test_account_costs_empty(ce):
    stubber = Stubber(ce)
    stubber.add_response("get_cost_and_usage", {"ResultsByTime": []})
    with stubber:
        result = CostService(_clients(ce)).account_costs({})
    assert result == ()
    stubber.assert_no_pending_responses()


def test_account_costs_raises_runtimeerror_on_client_error(ce):
    stubber = Stubber(ce)
    stubber.add_client_error("get_cost_and_usage", service_error_code="AccessDenied")
    with stubber:
        with pytest.raises(RuntimeError, match="Failed to fetch account costs"):
            CostService(_clients(ce)).account_costs({})


# --------------------------------------------------------------------------- #
# services_by_account
# --------------------------------------------------------------------------- #
def test_services_by_account_shape_and_sorting(ce):
    usage = {
        "ResultsByTime": [
            {
                "Groups": [
                    {"Keys": ["111111111111", "S3"], "Metrics": _metric("20.5")},
                    {"Keys": ["111111111111", "EC2"], "Metrics": _metric("100.0")},
                    {"Keys": ["222222222222", "Lambda"], "Metrics": _metric("10.0")},
                ]
            }
        ]
    }
    stubber = Stubber(ce)
    stubber.add_response("get_cost_and_usage", usage)
    with stubber:
        result = CostService(_clients(ce)).services_by_account()

    assert set(result.keys()) == {"111111111111", "222222222222"}
    # Sorted by amount descending within each account.
    svcs = result["111111111111"]
    assert [s.service for s in svcs] == ["EC2", "S3"]
    assert [s.amount for s in svcs] == [100.0, 20.5]
    assert result["222222222222"][0].service == "Lambda"
    stubber.assert_no_pending_responses()


def test_services_by_account_empty(ce):
    stubber = Stubber(ce)
    stubber.add_response("get_cost_and_usage", {"ResultsByTime": []})
    with stubber:
        result = CostService(_clients(ce)).services_by_account()
    assert result == {}
    stubber.assert_no_pending_responses()


def test_services_by_account_raises_on_error(ce):
    stubber = Stubber(ce)
    stubber.add_client_error("get_cost_and_usage", service_error_code="AccessDenied")
    with stubber:
        with pytest.raises(RuntimeError, match="Failed to fetch services by account"):
            CostService(_clients(ce)).services_by_account()


# --------------------------------------------------------------------------- #
# credits_applied
# --------------------------------------------------------------------------- #
def test_credits_applied_returns_absolute_magnitude(ce):
    usage = {
        "ResultsByTime": [
            {
                "Groups": [
                    {"Keys": ["111111111111"], "Metrics": _metric("-5.0")},
                    {"Keys": ["222222222222"], "Metrics": _metric("-12.34")},
                ]
            }
        ]
    }
    stubber = Stubber(ce)
    stubber.add_response("get_cost_and_usage", usage)
    with stubber:
        result = CostService(_clients(ce)).credits_applied()
    assert result == {"111111111111": 5.0, "222222222222": 12.34}
    stubber.assert_no_pending_responses()


def test_credits_applied_empty(ce):
    stubber = Stubber(ce)
    stubber.add_response("get_cost_and_usage", {"ResultsByTime": []})
    with stubber:
        result = CostService(_clients(ce)).credits_applied()
    assert result == {}
    stubber.assert_no_pending_responses()


def test_credits_applied_raises_on_error(ce):
    stubber = Stubber(ce)
    stubber.add_client_error("get_cost_and_usage", service_error_code="AccessDenied")
    with stubber:
        with pytest.raises(RuntimeError, match="Failed to fetch credits"):
            CostService(_clients(ce)).credits_applied()


# --------------------------------------------------------------------------- #
# _forecast (tested in isolation)
# --------------------------------------------------------------------------- #
def test_forecast_parses_total_amount(ce):
    stubber = Stubber(ce)
    stubber.add_response("get_cost_forecast", _forecast_response("123.45"))
    with stubber:
        value = CostService(_clients(ce))._forecast("111111111111")
    assert value == 123.45
    stubber.assert_no_pending_responses()


def test_forecast_returns_zero_on_client_error(ce):
    stubber = Stubber(ce)
    stubber.add_client_error("get_cost_forecast", service_error_code="DataUnavailable")
    with stubber:
        value = CostService(_clients(ce))._forecast("111111111111")
    assert value == 0.0
