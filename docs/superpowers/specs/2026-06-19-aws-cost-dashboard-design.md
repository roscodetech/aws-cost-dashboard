# aws-cost-dashboard — Design

**Date:** 2026-06-19
**Status:** Approved for planning
**Author:** roscoe

## Purpose

A local Flask web dashboard that pulls cost, credit, forecast, and budget data
for every AWS account under a single AWS Organizations payer account, and
displays it in one place. Read-only. Replaces logging into the Billing console
per account.

## Context

- Accounts are under **AWS Organizations consolidated billing**. A single
  Cost Explorer call on the payer account (`055706347991`) returns every linked
  account broken down by `LINKED_ACCOUNT`.
- Follows the existing local-dashboard pattern in this repo
  (`sentry-dashboard`, `s3-bucket-dashboard`): Python + Flask, `.env` config,
  secrets gitignored.
- **Root credentials are never used.** A dedicated read-only IAM user is created
  on the payer account.

## Non-Goals (v1)

- No write/mutate operations of any kind.
- No live "remaining credit balance" scraping from the console (no API exists;
  see Credits below).
- No per-linked-account budgets (requires creds in each account).
- No ZAR currency conversion (Cost Explorer returns USD only).

## Authentication

`boto3.Session` resolves credentials in this precedence:

1. `AWS_PROFILE` env var (e.g. `roscode-billing`) → reads `~/.aws/credentials`.
2. Explicit `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` from gitignored `.env`.

Region is pinned to `us-east-1` (Cost Explorer endpoint). Credentials are
validated at startup with a cheap call (`organizations.describe_organization`);
on failure the app shows a clear "credentials missing or lack billing access"
message and does not start serving stale data.

### IAM policy (`iam-policy.json`, least privilege)

Attached to a new IAM user on the payer account:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ce:GetCostAndUsage",
        "ce:GetCostForecast",
        "ce:GetDimensionValues",
        "budgets:ViewBudget",
        "budgets:DescribeBudget",
        "budgets:DescribeBudgets",
        "organizations:ListAccounts",
        "organizations:DescribeOrganization"
      ],
      "Resource": "*"
    }
  ]
}
```

No root, no write, no resource data access.

## Data Sources

| Metric | API | Notes |
|--------|-----|-------|
| Cost per account (MTD + last month) | `ce:GetCostAndUsage` MONTHLY, `UnblendedCost`, GroupBy `LINKED_ACCOUNT` | One call spanning prior month start → today |
| Cost by service | `ce:GetCostAndUsage` GroupBy `SERVICE`, filtered per account | Drives the per-account breakdown chart |
| Credits applied (MTD) | `ce:GetCostAndUsage` GroupBy `RECORD_TYPE`, isolate `Credit` | Only credit data AWS exposes via API |
| Credit remaining balance | **none** — manual `credits.json` | `account_id → {balance, expiry, note}`; shown beside applied-MTD |
| Forecast (end of month) | `ce:GetCostForecast` | `UNBLENDED_COST` to month end |
| Budgets | `budgets:DescribeBudgets` on payer | Linked-account budgets out of scope v1 |
| Account names | `organizations:ListAccounts` | Maps account ID → friendly name |

### Cost Explorer cost caveat

Each Cost Explorer request costs **$0.01**. The dashboard caches results to a
local JSON file with a TTL (default 1 hour). `/` serves from cache; an explicit
**Refresh** button forces a live pull. This keeps charges to pennies and the UI
fast.

### Credits handling

AWS provides **no API** for promotional credit *balance*. We expose two things:

1. **Applied this month** — pulled live from Cost Explorer (`RECORD_TYPE=Credit`).
2. **Remaining balance** — entered manually via a small form (`POST /credits`)
   persisted to `credits.json`, displayed next to applied-MTD so burn is visible.

## Architecture

Small, single-concern modules (each < 400 lines):

```
config.py            load creds/profile, region, cache + credits.json paths
aws_client.py        build boto3 session + ce / budgets / organizations clients
cost_service.py      Cost Explorer queries → frozen dataclasses
budgets_service.py   budgets fetch → BudgetStatus
org_service.py       account-id → name map
credits_store.py     read/write manual remaining-balance JSON
cache.py             TTL file cache wrapping the services
app.py               Flask routes
templates/  static/  Jinja + Chart.js
.env.example  requirements.txt  run.bat  iam-policy.json  README.md  .gitignore
```

### Data model (frozen dataclasses, immutable)

```python
@dataclass(frozen=True)
class AccountCost:
    account_id: str
    name: str
    mtd_cost: float
    last_month_cost: float
    forecast: float
    currency: str

@dataclass(frozen=True)
class ServiceCost:
    service: str
    amount: float

@dataclass(frozen=True)
class CreditInfo:
    account_id: str
    applied_mtd: float
    remaining_balance: float | None
    expiry: str | None
    note: str | None

@dataclass(frozen=True)
class BudgetStatus:
    name: str
    account_id: str
    limit: float
    actual: float
    forecasted: float

@dataclass(frozen=True)
class DashboardData:
    accounts: tuple[AccountCost, ...]
    by_service: dict[str, tuple[ServiceCost, ...]]   # account_id -> services
    credits: tuple[CreditInfo, ...]
    budgets: tuple[BudgetStatus, ...]
    currency: str
    refreshed_at: str
```

### Routes

| Route | Method | Purpose |
|-------|--------|---------|
| `/` | GET | Render dashboard from cache (live pull if cache empty/expired) |
| `/api/refresh` | POST | Force live pull, rewrite cache, return JSON |
| `/credits` | POST | Update a `credits.json` entry (remaining balance/expiry/note) |

### UI

- One card per linked account: name, account ID, MTD cost, last-month cost,
  forecast, credits applied + remaining (with burn indication).
- Per-account by-service breakdown (Chart.js doughnut/bar).
- Budgets section (payer budgets) with actual-vs-limit bars.
- Header: total spend across accounts, last-refreshed timestamp, Refresh button.
- Errors surface as a dismissible banner, never a stack trace.

## Currency

Cost Explorer returns USD. The bill shows a separate ZAR conversion that the API
does not expose. v1 displays USD, clearly labelled. A fixed FX line is a possible
later addition, out of scope now.

## Error Handling

- Startup: validate creds with a cheap Organizations call; fail fast with a clear
  message.
- Every AWS call wrapped; `botocore` errors mapped to user-friendly banners.
- Cache read/write failures degrade gracefully (fall back to live pull / in-memory).

## Testing

- **Unit (target 80%):** botocore `Stubber` for Cost Explorer responses; `moto`
  for organizations + budgets. Cover cost aggregation, credit isolation,
  forecast parsing, cache TTL, credits.json read/write.
- **Integration:** a `--live` smoke test, env-gated (`AWS_COST_DASHBOARD_LIVE=1`),
  run manually — not in CI, since each CE call costs $0.01 and needs real creds.
- **E2E real-user (priority):** Playwright drives the local Flask dashboard
  against an **injected fake data provider** (no real AWS, no money): load `/`,
  assert account cards render, click **Refresh**, assert updated timestamp.
  Headless in CI, headed via one flag (`--headed`). Capture screenshot/trace on
  failure.

## Security

- Root credentials never used; dedicated read-only IAM user only.
- `.env`, `~/.aws` references, cache file, and `credits.json` gitignored.
- No secrets in source; `.env.example` ships with placeholders only.
- Read-only IAM policy committed as `iam-policy.json` for reproducibility.

## Open Questions

None blocking. Possible later additions: ZAR FX line, per-linked-account
budgets, anomaly/alert surfacing, CSV export.
