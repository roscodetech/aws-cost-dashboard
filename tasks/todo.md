# aws-cost-dashboard — Implementation Plan

Spec: `docs/superpowers/specs/2026-06-19-aws-cost-dashboard-design.md`

## Wave 0 — Foundation (sequential, locks contracts)
- [x] `requirements.txt` (Flask, boto3, python-dotenv, pytest, moto, playwright)
- [x] `.env.example` (profile + key placeholders, region, cache TTL)
- [x] `iam-policy.json` (least-privilege read-only)
- [x] `models.py` (frozen dataclasses from spec)
- [x] `config.py` (load profile/keys/region/paths, validate)
- [x] `aws_client.py` (boto3 Session + ce/budgets/organizations clients)
- [x] `cache.py` (TTL JSON file cache)

## Wave 1 — Services (parallel, depend on models/aws_client)
- [x] `org_service.py` — account-id → name map
- [x] `cost_service.py` — per-account, by-service, credits-applied, forecast
- [x] `budgets_service.py` — payer budgets → BudgetStatus
- [x] `credits_store.py` — read/write credits.json (remaining balance)

## Wave 2 — Web layer (depends on services)
- [x] `app.py` — routes `/`, `/api/refresh`, `POST /credits`; build DashboardData
- [x] `templates/` — base + dashboard (account cards, budgets, charts)
- [x] `static/` — Chart.js wiring, minimal CSS
- [x] `run.bat`

## Wave 3 — Tests (parallel)
- [x] Unit: cost_service (Stubber), credits_store, cache TTL, org/budgets (moto) — 80%
- [x] E2E: Playwright against fake data provider — load, cards, Refresh
- [x] `README.md` — setup, IAM user creation, profile/.env, run, test

## Review

Built `aws-cost-dashboard` — a local Flask read-only dashboard for multi-account
AWS cost/credits/forecast/budgets under one Organizations payer account.

**What changed / why:**
- Foundation written by hand to lock contracts (`config`, `models`, `aws_client`,
  `cache`); service + UI + test layers fanned out to parallel subagents against
  those contracts.
- Credentials resolve via AWS profile or explicit keys (never root); least-privilege
  read-only IAM policy shipped as `iam-policy.json`.
- Cost Explorer results cached (1h TTL) to keep CE charges (~$0.01/call) negligible;
  Refresh button forces a live pull.
- Remaining credit balance has no AWS API → manual `credits.json`, editable per
  account; cache patched in place on edit (no billed CE call).

**Verification:** 56 unit tests pass (97% core coverage, botocore Stubber + fakes),
5 Playwright E2E tests pass against real Chromium with a fake provider (no AWS, no
money), 1 live smoke test gated behind `AWS_COST_DASHBOARD_LIVE=1`.

**Not yet done (needs real creds, your side):** create the `roscode-billing` IAM
user + policy, enable IAM billing access on the payer, drop creds in `.env`, then
`run.bat` and click through. Live smoke + a real-browser pass should follow.
