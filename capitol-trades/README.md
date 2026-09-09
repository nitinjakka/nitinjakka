# Capitol Trades Monitor — Congressional Trade Disclosure Watcher

Watches for new stock-trade disclosures (Periodic Transaction Reports) filed
by Rep. Nancy Pelosi (CA-11) and emails a summary when one appears. Hosted on
Azure Functions; email via Resend.

**Last updated: 2026-09-09** (see Changelog at the bottom)

---

## Live deployment (Azure)

Subscription "Subscription 1" → resource group **`capitol-trades-rg`** (centralus):

| Resource | Name | Notes |
|---|---|---|
| Function app | `pelosi-monitor-nitin` | Linux **Consumption (Y1)** plan, Python 3.11 |
| Storage account | `capitoltradesnitin` | Function runtime + state blob |
| App Insights | `pelosi-monitor-nitin` | Logs, 90-day retention, sampling on |

Functions (code in `azure-function/`):

- **`pelosi_timer`** — timer trigger, **hourly** at minute 0 UTC (`0 0 * * * *`)
- **`pelosi_run`** — HTTP trigger for manual runs/testing:
  ```
  KEY=$(az functionapp function keys list -g capitol-trades-rg \
    -n pelosi-monitor-nitin --function-name pelosi_run --query default -o tsv)
  curl "https://pelosi-monitor-nitin.azurewebsites.net/api/pelosi_run?send=0&delay=10&code=$KEY"
  ```
  Query params: `send=0` = dry run (no email, no state change), `delay=N` =
  seconds between the 3 verification fetches (default 45).

App settings (Function App → Configuration):

| Setting | Purpose |
|---|---|
| `RESEND_API_KEY` | Resend key "pelosi-monitor-azure" (sending-only) |
| `EMAIL_TO` | Recipient — nitin.jakka@gmail.com |
| `EMAIL_FROM` | `Pelosi Monitor <onboarding@resend.dev>` (see Email notes) |

## What each run does

1. Downloads the official House Clerk disclosure index **3 separate times**
   (triple verification); all 3 must agree or the run aborts and retries next hour.
2. Filters for Pelosi filings of type `P` (PTR = stock trades) and diffs
   against state (blob `pelosi-monitor/seen_filings.json` in the storage account).
3. For each new filing: downloads the official PDF and parses every trade —
   asset, ticker, stock vs option (strike/expiry), buy/sell/exchange/partial,
   trade date, amount range, owner, description. Handles page-break-wrapped
   rows and exact-amount entries (e.g. spinoffs).
4. Sends ONE summary email via Resend with the trades table + official PDF link.
5. Records filings as seen **only after the email succeeds** — a failed email
   is retried automatically on the next run. No duplicates: already-seen
   DocIDs are never emailed again.

Expected latency: within ~1 hour of the Clerk publishing a filing. (The trades
inside are typically 2–6 weeks old — the STOCK Act allows up to 30–45 days
between trade and disclosure. Nobody gets it fresher.)

## Cost

Effectively **~$1/month** (verified 2026-09):

- Compute: $0 — ~730 hourly runs/mo use <1% of the Consumption plan's free
  grant (1M executions + 400K GB-s).
- Storage: ~$0.50–$2/mo — runtime housekeeping transactions; data itself is KBs.
- App Insights & bandwidth: $0 — far below free tiers.

Check actuals: Azure portal → Cost Management → filter to `capitol-trades-rg`.

## Data source (and why not capitoltrades.com)

- **Index:** `https://disclosures-clerk.house.gov/public_disc/financial-pdfs/{year}FD.zip`
  — ZIP containing XML of every House disclosure filed that year (filer, type,
  date, DocID). Filing type `P` = PTR. Owner `SP` = spouse, `DC` = dependent child.
- **Filing PDFs:** `https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/{year}/{DocID}.pdf`

This is the primary source that capitoltrades.com, Quiver, Unusual Whales etc.
repackage. capitoltrades.com itself blocks automated access (Vercel bot
challenge), so we go straight to the government source — no middleman can
delay or spin the data.

## Verifying a viral claim manually (fact-check recipe)

When a tweet claims "Congressman X just disclosed N trades":

1. Download the index ZIP above, grep the XML for the member's `<Last>` name;
   note DocIDs and filing dates (`FilingType` = `P`).
2. Open the PDF for the DocID in question and count/read the actual rows.
3. Watch for the standard distortions:
   - Owner codes: `SP`/`DC` trades are spouse/children (often trust accounts
     run by outside managers), not the member personally.
   - "Worth up to $X" = sum of range **maximums**; sum of minimums is often
     ~10× smaller. Both are "true".
   - Precise portfolio values / % gains are always third-party estimates —
     disclosures only contain ranges.
   - E-filed PDFs (text layer) parse with pdfplumber; hand-delivered filings
     (e.g. Khanna's, Pelosi DocIDs starting `2003…`) are scanned images and
     need OCR or manual reading.

Example verified 2026-09-09: Khanna's 9/4/26 filing (DocID 9116328, 18 pages)
— real, ~200 trades, but all SP/DC across six Ahuja/Khanna family trusts,
nearly all $1,001–$15,000 rows.

## Deploying code changes

```bash
cd capitol-trades/azure-function
zip -r /tmp/pelosi-func.zip function_app.py pelosi_core.py host.json requirements.txt
az functionapp deployment source config-zip -g capitol-trades-rg \
  -n pelosi-monitor-nitin --src /tmp/pelosi-func.zip --build-remote true
# then verify:
curl ".../api/pelosi_run?send=0&delay=5&code=$KEY"
```

Change the schedule: edit the `schedule=` NCRONTAB in `function_app.py`
(`{second} {minute} {hour} {day} {month} {day-of-week}`) and redeploy.

## Adding more politicians

`pelosi_core.py` filters on `FILER_LAST` / `FILER_FIRST` constants. To watch
more members, generalize those into a `WATCHLIST` of (first, last) pairs and
loop `gather()` over it (the index download already contains every member —
only the filter changes). Senators are NOT in this index — the Senate
equivalent is efdsearch.senate.gov (session-based, needs different fetching).

## Email notes

- Resend account has **no verified domain**, so mail sends from
  `onboarding@resend.dev` — deliverable **only to the Resend account owner's
  address**. To use a custom from-address (or other recipients), verify a
  domain in Resend and update `EMAIL_FROM`.
- Delivery check: Resend dashboard → Emails (status should be "delivered").

## Files in this directory

- `azure-function/` — the deployed app
  - `function_app.py` — timer + HTTP triggers
  - `pelosi_core.py` — fetch, triple-verify, PDF parse, email, state
  - `host.json`, `requirements.txt`
- `pelosi_monitor.py` — standalone stdlib-only CLI (`check` / `ack`), predates
  the Azure deployment; useful for ad-hoc local runs. Local state in
  `seen_filings.json` (the Azure app uses the blob, NOT this file).

## Troubleshooting

- **No emails arriving:** run `pelosi_run?send=0` — if `new_filings` is empty,
  there's simply nothing new (Pelosi filed only 3 PTRs in all of 2026 so far).
  Check spam for `onboarding@resend.dev`. Check Resend dashboard for bounces.
- **`consistent_across_fetches: false`:** transient source flakiness; the next
  hourly run retries. Persistent = Clerk site issue.
- **Function errors:** App Insights → `pelosi-monitor-nitin` → Failures, or
  Log stream on the function app.
- **Re-send a filing:** delete its DocID from blob
  `pelosi-monitor/seen_filings.json` (storage account `capitoltradesnitin`)
  and run `pelosi_run?send=1`.

## Changelog

- **2026-09-09** — Initial build: standalone CLI checker; interim
  session-based scheduler (since removed). Migrated to Azure Functions
  (`capitol-trades-rg`), tested live end-to-end (27/27 trades parsed across
  Pelosi's three 2026 filings; email delivered). Schedule tightened from
  6-hourly to hourly. Parser hardened: page-break wrapping, exact-amount
  spinoff rows. Baseline state seeded with DocIDs 20033725, 20034836,
  20035143. Cost analysis: ~$1/mo. Added manual fact-check recipe (Khanna
  example).
