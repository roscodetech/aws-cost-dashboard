# aws-cost-dashboard — Implementation Plan

Spec: `docs/superpowers/specs/2026-06-19-aws-cost-dashboard-design.md`

## Wave 0 — Foundation (sequential, locks contracts)
- [ ] `requirements.txt` (Flask, boto3, python-dotenv, pytest, moto, playwright)
- [ ] `.env.example` (profile + key placeholders, region, cache TTL)
- [ ] `iam-policy.json` (least-privilege read-only)
- [ ] `models.py` (frozen dataclasses from spec)
- [ ] `config.py` (load profile/keys/region/paths, validate)
- [ ] `aws_client.py` (boto3 Session + ce/budgets/organizations clients)
- [ ] `cache.py` (TTL JSON file cache)

## Wave 1 — Services (parallel, depend on models/aws_client)
- [ ] `org_service.py` — account-id → name map
- [ ] `cost_service.py` — per-account, by-service, credits-applied, forecast
- [ ] `budgets_service.py` — payer budgets → BudgetStatus
- [ ] `credits_store.py` — read/write credits.json (remaining balance)

## Wave 2 — Web layer (depends on services)
- [ ] `app.py` — routes `/`, `/api/refresh`, `POST /credits`; build DashboardData
- [ ] `templates/` — base + dashboard (account cards, budgets, charts)
- [ ] `static/` — Chart.js wiring, minimal CSS
- [ ] `run.bat`

## Wave 3 — Tests (parallel)
- [ ] Unit: cost_service (Stubber), credits_store, cache TTL, org/budgets (moto) — 80%
- [ ] E2E: Playwright against fake data provider — load, cards, Refresh
- [ ] `README.md` — setup, IAM user creation, profile/.env, run, test

## Review
_(filled in after completion)_
