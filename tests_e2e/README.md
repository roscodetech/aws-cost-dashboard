# E2E tests (Playwright, real browser, fake data)

These drive a real Chromium against the real Flask app with a `FakeProvider` — no AWS access, no billing.

```bash
python -m pip install playwright && python -m playwright install chromium
python -m pytest tests_e2e -q          # headless (default)
HEADED=1 python -m pytest tests_e2e -q # watch it run (headful + slow-mo)
```

Run with the explicit `tests_e2e` path (root `pytest.ini` sets `testpaths = tests`). Failure screenshots land in `tests_e2e/artifacts/`.
