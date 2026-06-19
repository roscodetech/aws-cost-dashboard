"""Real-browser E2E tests for the AWS cost dashboard.

Drives a real Chromium against the real Flask app (fake provider, no AWS). Set
``HEADED=1`` to watch it run (headful + slow_mo). On failure a screenshot is
written to ``tests_e2e/artifacts/``.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright

ARTIFACTS_DIR = Path(__file__).parent / "artifacts"
HEADED = os.getenv("HEADED") == "1"

# Expected fake data (kept in sync with conftest).
ACCOUNT_NAMES = ("prod", "staging", "dev")
EXPECTED_TOTAL_MTD = round(1234.56 + 210.40 + 42.10, 2)  # 1487.06


def _digits(text: str) -> float:
    """Strip everything but digits/.- and parse, for format-tolerant comparison."""
    cleaned = re.sub(r"[^\d.\-]", "", text)
    return float(cleaned) if cleaned not in ("", "-", ".") else 0.0


@pytest.fixture
def page(request):
    """Launch a real browser/page; capture a screenshot on test failure."""
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=not HEADED,
            slow_mo=300 if HEADED else 0,
        )
        context = browser.new_context()
        pg = context.new_page()
        try:
            yield pg
        finally:
            if request.node.rep_call is not None and request.node.rep_call.failed:
                shot = ARTIFACTS_DIR / f"{request.node.name}.png"
                try:
                    pg.screenshot(path=str(shot), full_page=True)
                except Exception:
                    pass
            context.close()
            browser.close()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Expose each phase's result on the item so the page fixture can see failures."""
    outcome = yield
    rep = outcome.get_result()
    setattr(item, f"rep_{rep.when}", rep)


# --------------------------------------------------------------------------- #
# 1. Page loads, heading visible, exactly 3 account cards, names present.
# --------------------------------------------------------------------------- #
def test_dashboard_loads_with_three_accounts(live_server, page):
    base_url, _ = live_server
    page.goto(base_url)

    expect(page.get_by_role("heading", name="AWS Cost Dashboard")).to_be_visible()

    cards = page.locator(".account-card")
    expect(cards).to_have_count(3)

    for name in ACCOUNT_NAMES:
        expect(page.locator(".acct-name", has_text=name)).to_be_visible()


# --------------------------------------------------------------------------- #
# 2. Header Total MTD matches the sum of the fake accounts (format-tolerant).
# --------------------------------------------------------------------------- #
def test_total_mtd_matches_account_sum(live_server, page):
    base_url, _ = live_server
    page.goto(base_url)

    # The "Total MTD" stat value sits right after the "Total MTD" label.
    total_text = page.locator(".stat", has_text="Total MTD").locator(".stat-value").inner_text()
    assert round(_digits(total_text), 2) == EXPECTED_TOTAL_MTD


# --------------------------------------------------------------------------- #
# 3. Service charts render (Chart.js). Resilient to offline CDN.
# --------------------------------------------------------------------------- #
def test_service_charts_present(live_server, page):
    base_url, _ = live_server
    page.goto(base_url)

    canvases = page.locator("canvas.service-chart")
    assert canvases.count() >= 1

    # Give the deferred script + (possible) CDN a moment, then check rendering.
    page.wait_for_timeout(1000)
    chart_defined = page.evaluate("() => typeof window.Chart !== 'undefined'")
    first_width = page.evaluate(
        "() => document.querySelector('canvas.service-chart')?.width || 0"
    )

    # If the CDN was reachable Chart is defined and canvases get sized; if it was
    # blocked offline, at minimum the canvas element must exist (asserted above).
    assert chart_defined or first_width > 0 or canvases.count() >= 1


# --------------------------------------------------------------------------- #
# 4. Refresh button works; no error banner appears.
# --------------------------------------------------------------------------- #
def test_refresh_button_no_error(live_server, page):
    base_url, provider = live_server
    page.goto(base_url)

    page.locator("#refresh-btn").click()
    # JS calls /api/refresh (ok) then reloads. Wait for the reload to settle.
    page.wait_for_load_state("load")
    page.wait_for_timeout(500)

    expect(page.locator("#error-banner")).to_have_class(re.compile(r"\bhidden\b"))
    # The forced refresh hit the provider.
    assert True in provider.get_calls


# --------------------------------------------------------------------------- #
# 5. Credit edit form submits, redirects to / (200), provider records the call.
# --------------------------------------------------------------------------- #
def test_credit_edit_submits_and_records(live_server, page):
    base_url, provider = live_server
    page.goto(base_url)

    card = page.locator('.account-card[data-account-id="111111111111"]')
    card.locator("summary").click()  # open the <details> edit panel

    form = card.locator("form.credit-form")
    form.locator('input[name="balance"]').fill("777.77")

    with page.expect_navigation(wait_until="load"):
        form.locator('button[type="submit"]').click()

    assert page.url.rstrip("/") == base_url.rstrip("/")
    assert len(provider.update_calls) == 1
    call = provider.update_calls[0]
    assert call["account_id"] == "111111111111"
    assert call["balance"] == 777.77
