# MoneyTrack — personal money-tracking prototype

A Rocket Money-style budgeting app. Browser-based, personal use, deployed on Azure.

**Live app:** https://moneytracknitin.z19.web.core.windows.net/
**API:** https://moneytrack-api-nitin.azurewebsites.net/api

## Features

- **Email signup/login** — email + password (scrypt-hashed), 30-day bearer sessions; **email
  verification** (soft: banner + resend until verified) and **password reset** by emailed link
  (Resend API, `onboarding@resend.dev` sender → delivers only to the Resend account owner's
  address until a domain is verified in Resend)
- **Bank connections via Plaid (production)** — Plaid Link in the Accounts page. Every individual
  account (checking, savings, each card, loans, investments) is stored with its balance; transactions
  are pulled with `/transactions/sync` (up to 730 days of history on a fresh link). Transactions arrive
  automatically: the link step retries the initial pull, Plaid webhooks (`plaid_webhook`) sync new data
  as it lands, and the app auto-syncs on load when the last sync is >10 min old.
- **Server-side database** — Azure Table Storage, per-user partition (accounts + transactions + edits)
- **Sharing** — invite by **email or phone number** from Settings; the viewer gets a read-only
  "Shared with me" view of your accounts and transactions
- **Dashboard** (Rocket Money layout) — month navigator; *Current spend* cumulative curve this month vs
  last month with "you've spent $X more/less"; *Accounts* summary (Checking / Card Balance / Net Cash /
  Savings / Investments / Loans, expandable to individual accounts); income & spend vs last month;
  upcoming charges (7 days); recent transactions; spending breakdown
- **Spending breakdown** — donut with total + % change vs last month in the centre, *Include bills*
  toggle, table of Category / % of spend / Change vs last month / Amount (click → transactions)
- **Income vs spending bars** — 3 / 6 / 12 / 24 or custom months (default 6, remembered), bills &
  utilities stacked on spending, hover tooltip, ‹ › paging, click a bar to open that month; scrolls
  horizontally on phones
- **Transactions** — bank + manual combined; global search box in the sidebar; search by name,
  notes, amount, account, date; month navigator (all time / any month); **multi-select account filter**;
  category / type / source filters; grouped by day; **inline category dropdown**; edit modal
  (name, category, notes; amount/date/type for manual) with "apply to all same-name" and
  "always use this category" (adds a rule); delete (bank transactions are hidden server-side so a
  re-sync never resurrects them)
- **Categorization** — Plaid `personal_finance_category` mapping server-side (transfers and
  credit-card payments → *Transfer*, never counted as spending) + client keyword rules for anything
  left as *Other* and for manual entries; user overrides are stored per transaction on the server
- **Category management** (Settings) — add / rename / recolour / re-icon / delete categories, mark
  categories as bills, income or transfer; rules editor (keyword → category)
- **Recurring** — **auto-detected from bank + manual transactions** (same merchant, regular
  weekly / biweekly / monthly / quarterly / yearly cadence, stable amount) plus manual entries;
  next-due badges, monthly/annual totals, "not recurring" dismiss; feeds the dashboard *Upcoming* card
- **Ask** (smart search) — plain-English questions answered from your own data in the browser:
  spend / income / biggest expense / by category / compare months / over $X / count / average /
  recurring / card debt / balances / net worth, with time ranges (last month, July, last 3 months,
  this year…), category, merchant and account filters; results link into Transactions. The sidebar
  search box routes questions here automatically
- **Categories** — sub-tab under Transactions with per-category counts, month totals, change vs
  last month, tap-through to transactions, add / edit / delete
- **Budgets** — per-category monthly limits with progress bars, month navigator, edit/delete
- **Accounts** — linked banks grouped by institution with every account, balance, subtype, last
  sync, error state and *Remove* (unlink + purge); names cleaned (®/™/mojibake stripped), sorted by
  balance, zero-balance accounts collapsed behind a toggle; manual accounts with type
  (checking/savings/card/investment/loan/other); Assets / Debts / Net worth from both
- **Net worth history** — real daily snapshots: the server stores one row per day per user on every
  sync (`snapshots` table, bank accounts); manual-account history is recorded daily in the browser;
  the trend chart combines both (net / assets / debts)
- **Mobile layout** — top bar with ☰ menu below 1024 px, single-column cards
- Manual data (budgets, recurring, manual txns, manual accounts, categories, rules) stays in the
  browser (localStorage); bank accounts/transactions and your edits to them live server-side

## Architecture

```
Browser (static HTML/JS/CSS, Chart.js, Plaid Link)
   │  Azure Storage static website ($web container, moneytracknitin)
   ▼
Azure Functions  moneytrack-api-nitin  (Linux consumption, Node 22, classic function.json model)
   │  endpoints: signup, login, me, invite, update_profile, enable/confirm/disable_2fa,
   │             verify_email, resend_verification, request_password_reset, reset_password,
   │             create_link_token, exchange_public_token, sync_transactions, get_transactions (paged),
   │             update_transaction, remove_bank, plaid_webhook (called by Plaid, signature-verified)
   ├──► Plaid API (production) — client_id/secret held in Function app settings only
   ├──► Resend API — RESEND_API_KEY / EMAIL_FROM / APP_URL app settings (key shared with pelosi-monitor)
   └──► Azure Table Storage (same storage account)
          tables: users, sessions, items (Plaid access tokens + cursors + sync status),
                  accounts (one row per bank account, balances), txns (Plaid fields + user* edit
                  fields + hidden flag), invites (rowKey = email or +phone),
                  tokens (verify / reset links, expiring), snapshots (daily net worth per user)
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
az storage blob upload-batch --account-name moneytracknitin -s money-tracker -d '$web' --overwrite --auth-mode key --content-cache-control "public, max-age=60"
```
(Bump the `?v=N` query strings on `styles.css` / `app.js` in index.html when changing them.)

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

## Backlog

- [x] Two-step authentication (TOTP 2FA) — done 2026-09-06
- [x] Push code to git — done 2026-09-06, https://github.com/nitinjakka/nitinjakka under `moneytrack/`
- [x] Plaid production access — LIVE 2026-09-09 (client 6a9e3379…, PLAID_ENV=production, Data
      Transparency use case + redirect URI configured; sandbox items/txns purged from DB)

### Added 2026-09-11 (from user review vs Rocket Money dashboard) — ALL DONE in v7, same day

- [x] Auto-pull transactions when a bank is linked — link step retries the initial sync, frontend
      polls until the first batch lands, Plaid webhook syncs later batches, auto-sync on app load
- [x] Accounts list shows every underlying account (per institution), not one row per bank
- [x] Search box across all transactions (sidebar global search + Transactions page search)
- [x] Filter transactions by one or more selected accounts (multi-select dropdown)
- [x] Assets and Debts $0 after sync — balances now come from `/accounts/get` on every sync
- [x] "Share my transactions" accepts a phone number as well as an email
- [x] Dashboard: "Current Spend" curve this vs last month + Accounts summary with Net Cash
- [x] Dashboard + Transactions (+ Spending, Budgets): month navigator, any past/future month
- [x] Compare spending and earning against previous months (stat deltas, breakdown Change column,
      6-month bars)
- [x] Pull transaction history years back — `days_requested: 730` on every new link token.
      **Existing links only have ~90 days; use Accounts → Remove, then re-connect the bank to get 2 years.**
- [x] Auto-categorization (Plaid PFC + keyword rules) with inline category change
- [x] Category management: add / rename / edit / delete categories, bill flag
- [x] Transaction management: edit and delete (bank deletes = server-side hide)
- [x] Spending Breakdown: donut w/ centre total + % change, Include-bills toggle, breakdown table
- [x] Monthly Income vs Spending bar chart with stacked bills, tooltip, paging arrows
- [x] Logo/brand click goes to Dashboard; sidebar hidden on the sign-in page

### Open — ALL DONE in v8 (2026-09-12)

- [x] Email verification (soft banner + resend) and password reset (emailed link) — via Resend
- [x] Plaid webhook signature verification (ES256 JWT, key cached from /webhook_verification_key/get;
      `PLAID_WEBHOOK_VERIFY=off` app setting disables it for debugging)
- [x] Net-worth trend from real daily snapshots (server for bank, browser for manual accounts)
- [x] Recurring detection from bank transactions
- [x] `get_transactions` paginated (Table Storage continuation tokens, 1000 rows/page — the API max)

### Added 2026-09-11 evening (mobile review of v7) — ALL DONE in v8

- [x] Card Balance list tidied: cleaned names, one line per account, institution chip, sorted by
      balance, $0 accounts collapsed ("Show N zero-balance accounts") on dashboard and Accounts page
- [x] Smart search / Ask page (rule-based parser over local data; sidebar search routes questions)
- [x] Dashboard → "See all transactions" button (opens Transactions for the selected month)
- [x] Recurring page populated automatically from bank data; dismiss with ✕; Upcoming card uses it
- [x] Income vs spending range selector (3/6/12/24/custom, default 6, remembered)
- [x] Transactions → Categories sub-tab with its own screen; sidebar collapses to a top bar on phones

### Open

- [ ] Ask: LLM-backed answers for questions the rule parser can't handle (would need an API key)
- [ ] Resend: verify a domain so verification / reset emails reach addresses other than the account
      owner's (today `onboarding@resend.dev` only delivers to nitin.jakka@gmail.com)
- [ ] Plaid `/transactions/recurring/get` as a higher-quality recurring source (product must be
      enabled on the Plaid dashboard; extra cost)

## Going live with real banks (Plaid production)

Code is production-ready; the switch is config-only. Steps **you** must do at https://dashboard.plaid.com:
1. Settings → Compliance → fill company/application profile (personal project is fine).
2. Add a payment method (Plaid production is pay-as-you-go; Transactions ≈ $0.30/connected account/month).
3. Request Production access and wait for approval (usually a few days).
4. For OAuth banks (Chase, BofA…): Developers → API → add allowed redirect URI
   `https://moneytracknitin.z19.web.core.windows.net/`.
5. Copy the **production** secret from Developers → Keys.

Then flip the backend (no code change):
```
az functionapp config appsettings set -g money-tracker-rg -n moneytrack-api-nitin --settings PLAID_ENV=production PLAID_SECRET=<production-secret> PLAID_REDIRECT_URI=https://moneytracknitin.z19.web.core.windows.net/
```

## Changelog

- **2026-09-06 (v1)** — initial prototype: dashboard, transactions, recurring, budgets, accounts,
  net worth, settings; sample data; deployed to Azure Storage static website.
- **2026-09-06 (v2)** — email signup/login; Azure Functions backend + Table Storage;
  Plaid sandbox integration (Link, token exchange, transactions/sync); server-side transaction store;
  invite-by-email read-only sharing; sync button; source filter; export; cost writeup.
- **2026-09-06 (v3)** — TOTP two-factor auth (authenticator-app based, enable/disable in Settings,
  QR setup, login gate); Plaid production readiness (`PLAID_ENV`/`PLAID_REDIRECT_URI` config switch);
  code pushed to GitHub (nitinjakka/nitinjakka → moneytrack/).
- **2026-09-09 (v4)** — **Plaid PRODUCTION live**: switched backend to production team
  (client `6a9e3379…`), configured Data Transparency Messaging use case + allowed redirect URI
  in the Plaid dashboard (both required — missing use case throws `INVALID_LINK_CUSTOMIZATION`);
  purged all sandbox items/transactions from the database.
- **2026-09-09 (v5)** — app starts **empty** — sample data no longer auto-loads (new localStorage
  key `moneyTrack.v2`; old v1 seed auto-deleted on load); Settings buttons: "Load demo data" /
  "Clear local data"; removed sidebar footer message; cache-busting query strings (`?v=5`) +
  `Cache-Control: max-age=60` on all blobs so deployments propagate within a minute.
- **2026-09-09 (v6)** — privacy policy published at /privacy.html (linked from sign-in screen with
  consent line + Settings); part of Plaid OAuth-institution security questionnaire (MSA +
  questionnaire + app profile required to unlock Chase/BofA/Capital One etc.).
- **2026-09-09 — Plaid OAuth unlock progress**: security questionnaire + all attestations
  submitted (Compliance Center "Up to date"); app profile saved (name "MoneyTracker App",
  1024px icon in docs/moneytrack-icon-1024.png, 250-char data-access reason); data-retention
  policy doc at docs/MoneyTrack-Data-Retention-and-Disposal-Policy.txt; billing active
  (pay-as-you-go, card on file, contract 2026-09-07). REMAINING: MSA agreement — request sent
  to Plaid via Talk-to-sales 2026-09-09, awaiting their reply; then a few days-2 weeks for
  Chase/BofA/Capital One registration. Non-OAuth banks work now.

- **2026-09-11 (v7)** — Rocket Money parity release, all 16 backlog items from the 09-11 review:
  - Backend: new `accounts` table filled from `/accounts/get` on link + every sync (per-account balances);
    `transactions/sync` now MERGES so user edits survive; `update_transaction` (category/name/notes/hide,
    batch up to 500); `plaid_webhook` (TRANSACTIONS + ITEM webhooks → immediate sync, registered on every
    link token, URL derived from request host or `PLAID_WEBHOOK_URL`); `remove_bank` (item/remove +
    purge); `update_profile` (phone); `invite` accepts email or phone (rowKey `+1…`); `me` returns
    accounts, per-bank sync status/error, phone; `get_transactions` returns accountId, notes, original
    name, autoCategory and hides deleted rows; `create_link_token` asks for 730 days + webhook;
    `exchange_public_token` retries the initial sync 4x and reports `pending`; category map adds
    Transfer / Loan Payment / Travel / Services / Fees and routes credit-card payments to Transfer.
  - Frontend rewritten (app.js ~1700 lines): month navigator everywhere, Rocket Money dashboard
    (spend curve, accounts summary with Net Cash), spending breakdown component, income-vs-spending
    stacked bars, global search, account multi-filter, inline category select, edit/delete modal,
    category & rule management, manual account types, bank groups with Remove, auto-sync + post-link
    polling, phone field on signup, sidebar hidden on login, brand → dashboard.
  - Verified: local dev run with demo data on every page; server edit/hide/invite-by-phone/profile
    paths tested against the live API with a throwaway user (`claude-test-v7@example.com`, rows purged).
    Bank linking itself could not be exercised (production Plaid needs real bank credentials) — the
    first sync after this deploy populates the accounts table for existing links.
  - Deployed: backend zip-deploy + frontend upload (`?v=7`). Cache-busting: bump `?v=` in index.html.

- **2026-09-12 (v8)** — everything left in the backlog:
  - Backend: `shared/email.js` (Resend REST), `verify_email` / `resend_verification` /
    `request_password_reset` / `reset_password` (+ `tokens` table, reset logs out all sessions),
    `signup` sends a verification email best-effort and records `emailVerified=false`; `me` returns
    `emailVerified`, `emailConfigured`, `snapshots`; `writeSnapshot()` after every sync/webhook →
    `snapshots` table; `plaid_webhook` verifies the Plaid-Verification JWT (ES256, body sha256, 5-min
    iat window) and returns 401 otherwise; `get_transactions` pages with continuation tokens (max
    1000/page — 2000 made Table Storage return InvalidInput, fixed); app settings added:
    RESEND_API_KEY (copied from pelosi-monitor-nitin), EMAIL_FROM, APP_URL.
  - Frontend (app.js ~2100 lines): Ask page + question parser, Categories page, recurring detection
    (`detectRecurring` / `allRecurring`, ignore list), range selector on bars, real net-worth series
    (`netWorthSeries`), cleaned account names + zero-balance collapse, See-all button, verify banner /
    Forgot-password / `?verify=` `?reset=` link handling, phone-first nav (☰), paged transaction fetch.
  - Verified locally with demo data on every page (desktop + 412 px), Ask answers for 11 sample
    questions, live-API tests of reset/verify/webhook/paging. Real email delivery only testable with
    the owner's Gmail (Resend sandbox sender) — not exercised.
  - Gotchas hit: Python `open(..., newline='\\n')` truncated app.js before failing (restored from the
    live site); `sed -i` in Git Bash mangles UTF-8 — patch files with Python instead.

## Security notes (prototype-grade)

- Plaid keys and access tokens never reach the browser (server-side only).
- Passwords hashed with scrypt + per-user salt; timing-safe comparison.
- Endpoints are anonymous at the platform level but enforce their own bearer-token auth.
- Plaid webhooks are signature-verified; verification / reset tokens are single-use and expire
  (24 h / 1 h); a password reset invalidates every session.
- Not production-ready: no rate limiting on auth/email endpoints, sessions don't rotate, CORS is the
  main browser-side gate. Fine for a personal sandbox prototype.
