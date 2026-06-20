# AWS Cost Dashboard

A local Flask dashboard that pulls **cost, credits, forecast, and budget** data for a
standalone AWS account — or every account under an **AWS Organizations** payer — and
shows it on a single page. Read-only. No more logging into the Billing console per
account.

![status](https://img.shields.io/badge/tests-61%20passing-brightgreen)

## What it shows

- **Cost per account** — month-to-date and last month, plus **last-12-month** and **all-time** totals (Cost Explorer, grouped by `LINKED_ACCOUNT`). All-time uses the widest window AWS allows: 14 months by default, up to 38 if you enable *historical data beyond 14 months* in Cost Explorer preferences.
- **Cost by service** — per-account breakdown (doughnut chart).
- **Credits** — real issued / remaining / estimated-remaining / expiry from the `billing:GetCredits` API, plus credits applied this month (Cost Explorer `RECORD_TYPE=Credit`). See [Credits](#credits).
- **Forecast** — projected end-of-month spend per account.
- **Budgets** — actual-vs-limit for budgets defined on the calling account.

## How it works

A single read-only IAM user calls Cost Explorer, Budgets, and `billing:GetCredits`.
On an **Organizations payer** one Cost Explorer call returns every linked account
(consolidated billing rolls spend up to the payer); a **standalone account** runs in
single-account mode automatically. Results are cached to `cache.json` (default 1h TTL)
so the page is fast and Cost Explorer charges stay in the pennies — **each CE API call
costs $0.01**. The **Refresh** button forces a live pull.

## Setup

### 1. Create a read-only IAM user (never use root)

In your account — a standalone account, or the **management/payer** account of an
AWS Organization — create an IAM user (e.g. `billing-readonly`, API access only, no
console login) and attach a custom policy with the contents of
[`iam-policy.json`](./iam-policy.json):

```
ce:GetCostAndUsage, ce:GetCostForecast, ce:GetDimensionValues,
budgets:ViewBudget,
billing:GetCredits, billing:GetCreditAllocationHistory,
organizations:ListAccounts, organizations:DescribeOrganization
```

Then create an **access key** for the user (Security credentials → Create access key
→ "Application running outside AWS").

### 1b. Activate IAM access to billing (required — this is a separate switch)

The policy above is not enough on its own. There is an **account-level** toggle that
gates *all* IAM access to billing data, and it can only be changed by the **root
user**:

```
Sign in as ROOT → https://console.aws.amazon.com/billing/home#/account
  → "IAM user and role access to Billing information" → Edit
  → Activate IAM Access → Update
```

This is account-wide (covers every IAM user/role), so you only do it once. Allow
~30–60s to propagate. Skipping it produces
`AccessDeniedException: "IAM user access not activated"` (HTTP 403) even when the
policy is correct — see [Troubleshooting](#troubleshooting).

### 2. Configure accounts

**Multiple accounts (recommended):** copy `accounts.example.json` to `accounts.json`
(gitignored) and list each account. Every entry needs a `label` plus **either** a
`profile` **or** `access_key_id` + `secret_access_key`; `region` is optional
(defaults `us-east-1`):

```json
[
  { "label": "Main",        "profile": "billing-readonly" },
  { "label": "Side account", "access_key_id": "AKIA…", "secret_access_key": "…" }
]
```

The dashboard pulls every listed account and shows them side by side. If one account's
credentials fail, the others still load and the failure appears in a banner. Each
account needs its own read-only IAM user **and** the billing-access toggle (steps 1 +
1b) done *inside that account*.

**Single account:** if `accounts.json` is absent, the dashboard falls back to one
account from `.env`:

```bash
cp .env.example .env
```

Two options (profile wins if both are set):

```env
# Option 1 (recommended): a named profile in ~/.aws/credentials
AWS_PROFILE=billing-readonly

# Option 2: explicit keys
# AWS_ACCESS_KEY_ID=AKIA...
# AWS_SECRET_ACCESS_KEY=...
```

For the profile option, add to `~/.aws/credentials`:

```ini
[billing-readonly]
aws_access_key_id = AKIA...
aws_secret_access_key = ...
```

### 3. Run

```bash
# Windows
run.bat

# or manually
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5057.

## Credits

The dashboard reads **real** credit balances from the `billing:GetCredits` API
(issued / remaining / estimated-remaining / expiry — the exact figures on the console
Credits page). These show with a **live** badge. Because the currently published
boto3/botocore does not yet model this operation, the dashboard calls it via a
SigV4-signed request to `https://billing.us-east-1.api.aws` (works with the installed
SDK). Requires `billing:GetCredits` in the IAM policy (included in `iam-policy.json`).

Credits **applied this month** still come from Cost Explorer (`RECORD_TYPE=Credit`),
shown alongside the remaining balance so you can watch the burn.

If the IAM principal lacks `billing:GetCredits`, the dashboard falls back to manual
entry: the "Edit credit balance" form on each card, persisted to a gitignored
`credits.json`. Manual edits patch the cached snapshot in place — no billed CE call.

## Currency

Cost Explorer reports in **USD**. Some accounts also see a local-currency conversion
on the invoice (e.g. ZAR) that the API does not expose, so the dashboard displays USD.
(A fixed-FX line is a possible later addition.)

## Troubleshooting

| Symptom | Cause & fix |
|---|---|
| `No AWS credentials found` at startup | `.env` is empty. Set `AWS_PROFILE`, or both `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`. |
| `400 ... no identity-based policy allows billing:GetCredits` | The IAM policy is missing the action. Add `billing:GetCredits` (and `billing:GetCreditAllocationHistory`) — see `iam-policy.json`. |
| `403 ... IAM user access not activated` | Policy is fine, but the **account-level** billing-access switch is off. Do step **1b** (root only, account-wide). |
| `AWSOrganizationsNotInUseException` | Expected on a standalone account — handled automatically (single-account mode). No action needed. |
| Credits show a manual "Edit" form / no **live** badge | The `billing:GetCredits` call isn't succeeding, so it fell back to manual entry. Fix the 400/403 above; the form disappears once live data flows. |
| `The action budgets:DescribeBudgets does not exist` | That's an API name, not an IAM action. The correct read action is `budgets:ViewBudget` (already in `iam-policy.json`). |

Note: the published `boto3`/`botocore` may not yet model `billing:GetCredits`. The
dashboard calls it via a SigV4-signed request to `https://billing.us-east-1.api.aws`,
so it works regardless of SDK version — no upgrade required.

## Project layout

```
config.py            credentials / settings (boundary, fails fast)
aws_client.py        boto3 session + ce/budgets/organizations clients
models.py            frozen dataclasses + JSON (de)serialization
cost_service.py      Cost Explorer queries
budgets_service.py   payer budgets
org_service.py       account-id -> name map
credits_api.py       real credit balances via billing:GetCredits (signed request)
credits_store.py     manual remaining-balance JSON (fallback)
cache.py             TTL file cache
providers.py         LiveProvider (assembles DashboardData, cached)
app.py               Flask factory + routes
templates/ static/   Jinja + Chart.js UI
iam-policy.json      least-privilege read-only policy
tests/               unit tests (botocore Stubber + fakes)
tests_e2e/           Playwright real-browser E2E (fake provider, no AWS)
```

## Testing

```bash
# Unit (mocked AWS — fast, free)
python -m pytest -q                      # 61 tests, ~95% core coverage

# E2E (real Chromium, fake data provider — no AWS, no money)
python -m pytest tests_e2e -q            # 5 tests
HEADED=1 python -m pytest tests_e2e      # watch it run

# Live smoke against real AWS (manual only — costs ~$0.01/call, needs real creds)
AWS_COST_DASHBOARD_LIVE=1 python -m pytest -m live
```

## Security

- Root credentials are never used — dedicated read-only IAM user only.
- `.env`, `accounts.json`, `credits.json`, `cache.json`, and any `*.pem` are gitignored.
- No secrets in source; `.env.example` ships placeholders only.
- The IAM policy is read-only and committed for reproducibility.

## Scope notes (v1)

- Works for both a **standalone account** and an **AWS Organizations payer**. With an
  org, every linked account is listed by name; standalone runs in single-account mode
  (the account is labelled by its id). Detection is automatic via STS + a graceful
  fallback when `organizations:ListAccounts` reports no organization.
- Per-linked-account budgets need credentials in each account → only the calling
  account's budgets are shown.
- No write/mutate operations of any kind.
