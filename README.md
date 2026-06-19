# AWS Cost Dashboard

A local Flask dashboard that pulls **cost, credits, forecast, and budget** data for
every AWS account under one **AWS Organizations** payer account, and shows it on a
single page. Read-only. No more logging into the Billing console per account.

![status](https://img.shields.io/badge/tests-61%20passing-brightgreen)

## What it shows

- **Cost per linked account** — month-to-date and last month (Cost Explorer, grouped by `LINKED_ACCOUNT`).
- **Cost by service** — per-account breakdown (doughnut chart).
- **Credits applied this month** — from Cost Explorer (`RECORD_TYPE=Credit`).
- **Remaining credit balance** — entered manually (AWS has **no API** for this — see [Credits](#credits)).
- **Forecast** — projected end-of-month spend per account.
- **Budgets** — actual-vs-limit for budgets defined on the payer account.

## How it works

One read-only IAM user on the **payer/management account** + a single set of Cost
Explorer calls returns every linked account, because consolidated billing rolls all
spend up to the payer. Results are cached to `cache.json` (default 1h TTL) so the
page is fast and Cost Explorer charges stay in the pennies — **each CE API call costs
$0.01**. The **Refresh** button forces a live pull.

## Setup

### 1. Create a read-only IAM user (never use root)

In the payer account (`055706347991`), create an IAM user, e.g. `roscode-billing`,
and attach a custom policy with the contents of [`iam-policy.json`](./iam-policy.json):

```
ce:GetCostAndUsage, ce:GetCostForecast, ce:GetDimensionValues,
budgets:ViewBudget,
organizations:ListAccounts, organizations:DescribeOrganization
```

Also make sure **IAM access to billing data is enabled**: payer account →
*Account → IAM User and Role Access to Billing Information → Activate*. Generate an
access key for the user.

### 2. Configure credentials

```bash
cp .env.example .env
```

Two options (profile wins if both are set):

```env
# Option 1 (recommended): a named profile in ~/.aws/credentials
AWS_PROFILE=roscode-billing

# Option 2: explicit keys
# AWS_ACCESS_KEY_ID=AKIA...
# AWS_SECRET_ACCESS_KEY=...
```

For the profile option, add to `~/.aws/credentials`:

```ini
[roscode-billing]
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

AWS exposes credits **applied** (via Cost Explorer) but provides **no API for your
remaining promotional credit balance**. So the dashboard lets you type the remaining
balance in per account (the "Edit credit balance" form on each card), persisted to a
gitignored `credits.json`. It's shown next to "applied this month" so you can watch
the burn. Editing a balance patches the cached snapshot in place — it does **not**
trigger a billed Cost Explorer call.

## Currency

Cost Explorer reports in **USD**. Your invoice also shows a ZAR conversion that the
API does not expose, so the dashboard displays USD. (A fixed-FX ZAR line is a possible
later addition.)

## Project layout

```
config.py            credentials / settings (boundary, fails fast)
aws_client.py        boto3 session + ce/budgets/organizations clients
models.py            frozen dataclasses + JSON (de)serialization
cost_service.py      Cost Explorer queries
budgets_service.py   payer budgets
org_service.py       account-id -> name map
credits_store.py     manual remaining-balance JSON
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
python -m pytest -q                      # 56 tests, ~97% core coverage

# E2E (real Chromium, fake data provider — no AWS, no money)
python -m pytest tests_e2e -q            # 5 tests
HEADED=1 python -m pytest tests_e2e      # watch it run

# Live smoke against real AWS (manual only — costs ~$0.01/call, needs real creds)
AWS_COST_DASHBOARD_LIVE=1 python -m pytest -m live
```

## Security

- Root credentials are never used — dedicated read-only IAM user only.
- `.env`, `credits.json`, `cache.json`, and any `*.pem` are gitignored.
- No secrets in source; `.env.example` ships placeholders only.
- The IAM policy is read-only and committed for reproducibility.

## Scope notes (v1)

- Per-linked-account budgets need credentials in each account → only payer budgets shown.
- No write/mutate operations of any kind.
