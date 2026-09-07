# MoneyTrack — personal money-tracking prototype

A Rocket Money-style budgeting app. Browser-based, personal use, deployed on Azure.

**Live app:** https://moneytracknitin.z19.web.core.windows.net/
**API:** https://moneytrack-api-nitin.azurewebsites.net/api

## Features

- **Email signup/login** — email + password (scrypt-hashed), 30-day bearer sessions
- **Bank connections via Plaid (sandbox)** — Plaid Link in the Accounts page; transactions
  pulled with `/transactions/sync` and stored server-side. Sandbox test login: `user_good` / `pass_good`
- **Server-side transaction database** — Azure Table Storage, per-user partition, for analysis
- **Sharing** — invite any email from Settings; when that person signs up/logs in, they get a
  read-only "Shared with me" view of your bank transactions
- **Dashboard** — monthly spend vs last month, income, recurring total, net worth, category donut, upcoming bills
- **Transactions** — bank + manual combined, search/filter by category/type/source
- **Recurring** — subscription list with due-date badges, monthly/annual totals
- **Budgets** — per-category monthly limits with progress bars
- **Accounts / Net worth** — manual asset & debt accounts, trend + breakdown charts
- Manual data (budgets, recurring, manual txns, accounts) stays in the browser (localStorage);
  bank transactions live server-side under your login

## Architecture

```
Browser (static HTML/JS/CSS, Chart.js, Plaid Link)
   │  Azure Storage static website ($web container, moneytracknitin)
   ▼
Azure Functions  moneytrack-api-nitin  (Linux consumption, Node 22, classic function.json model)
   │  endpoints: signup, login, me, invite,
   │             create_link_token, exchange_public_token, sync_transactions, get_transactions
   ├──► Plaid API (sandbox) — client_id/secret held in Function app settings only
   └──► Azure Table Storage (same storage account)
          tables: users, sessions, items (Plaid access tokens + cursors), txns, invites
```

Azure resources (subscription "Subscription 1", resource group `money-tracker-rg`, centralus):

| Resource | Purpose |
|---|---|
| `moneytracknitin` storage account | static website ($web) + Table Storage database |
| `moneytrack-api-nitin` function app | API (consumption plan) |
| `moneytrack-api-nitin` App Insights | logs/exceptions |

## Repo layout

- `money-tracker/` — frontend (index.html, app.js, styles.css)
- `money-tracker-api/` — Azure Functions backend (one folder per endpoint, `shared/` helpers)

## Deploy

Frontend:
```
az storage blob upload-batch --account-name moneytracknitin -s money-tracker -d '$web' --overwrite --auth-mode key
```

Backend:
```
Compress-Archive -Path money-tracker-api\* -DestinationPath $env:TEMP\money-tracker-api.zip -Force
az functionapp deployment source config-zip -g money-tracker-rg -n moneytrack-api-nitin --src $env:TEMP\money-tracker-api.zip
```

Local dev: `python -m http.server 8123 --directory money-tracker` (or the `money-tracker` entry in `.claude/launch.json`). CORS on the function app allows the live site + `http://localhost:8123`.

## Cost (24×7)

| Item | Est. / month |
|---|---|
| Storage (static site + tables, <1 GB) | ~$0.05 |
| Bandwidth (personal use) | ~$0.00–0.10 |
| Azure Functions consumption (first 1M executions free) | $0.00 |
| Application Insights (low volume, free 5 GB ingestion) | $0.00 |
| Plaid sandbox | $0.00 |
| **Total** | **≈ $0.10–0.25/month** |

Nothing is billed per-hour; there is no VM. Going to real banks later means Plaid production
(pay-as-you-go, roughly $0.30/connected account/month for transactions) — still no Azure change needed.

## Backlog (not started)

- [ ] Two-step authentication (2FA) for login
- [ ] Push code to git (GitHub — nitinjakka/nitinjakka)

## Changelog

- **2026-09-06 (v1)** — initial prototype: dashboard, transactions, recurring, budgets, accounts,
  net worth, settings; sample data; deployed to Azure Storage static website.
- **2026-09-06 (v2)** — email signup/login; Azure Functions backend + Table Storage;
  Plaid sandbox integration (Link, token exchange, transactions/sync); server-side transaction store;
  invite-by-email read-only sharing; sync button; source filter; export; cost writeup.

## Security notes (prototype-grade)

- Plaid keys and access tokens never reach the browser (server-side only).
- Passwords hashed with scrypt + per-user salt; timing-safe comparison.
- Endpoints are anonymous at the platform level but enforce their own bearer-token auth.
- Not production-ready: no rate limiting, no email verification, no password reset, sessions
  don't rotate, CORS is the main browser-side gate. Fine for a personal sandbox prototype.
