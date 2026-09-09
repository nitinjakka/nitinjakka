# Capitol Trades Monitor — Nancy Pelosi PTR Watcher (Azure-hosted)

Watches for new stock-trade disclosures (Periodic Transaction Reports) filed by
Rep. Nancy Pelosi (CA-11) and emails a summary when one appears.

## Production deployment (Azure)

Azure Functions app, subscription "Subscription 1":

- **Resource group:** `capitol-trades-rg` (centralus)
- **Function app:** `pelosi-monitor-nitin` (Linux consumption plan, Python 3.11)
- **Storage account:** `capitoltradesnitin` (also holds monitor state:
  container `pelosi-monitor`, blob `seen_filings.json`)
- **Email:** Resend API (`RESEND_API_KEY` app setting), from
  `onboarding@resend.dev` to `EMAIL_TO` (nitin.jakka@gmail.com)

Functions (code in `azure-function/`):

- `pelosi_timer` — timer trigger, hourly (`0 0 * * * *`)
- `pelosi_run` — HTTP trigger for manual runs/testing
  (`GET /api/pelosi_run?code=<function key>`; `send=0` = dry run,
  `delay=N` = seconds between verification fetches)

Each run:

1. Fetches the official House Clerk disclosure index **3 separate times**
   (triple verification) — all fetches must agree or the run aborts.
2. Diffs Pelosi PTR filings against the seen-filings blob.
3. For new filings, downloads the official PDF and parses every trade
   (asset, ticker, stock/option, buy/sell/exchange, date, amount, owner,
   description).
4. Emails one summary via Resend.
5. Records filings as seen **only after** the email succeeds, so failures
   retry on the next run.

### Deploying updates

```bash
cd capitol-trades/azure-function
zip -r /tmp/pelosi-func.zip function_app.py pelosi_core.py host.json requirements.txt
az functionapp deployment source config-zip -g capitol-trades-rg \
  -n pelosi-monitor-nitin --src /tmp/pelosi-func.zip --build-remote true
```

### Manual test

```bash
KEY=$(az functionapp function keys list -g capitol-trades-rg \
  -n pelosi-monitor-nitin --function-name pelosi_run --query default -o tsv)
curl "https://pelosi-monitor-nitin.azurewebsites.net/api/pelosi_run?send=0&delay=10&code=$KEY"
```

## Data source

`https://disclosures-clerk.house.gov/public_disc/financial-pdfs/{year}FD.zip`
— the primary source behind capitoltrades.com (which blocks automated access,
so we go straight to the source). Filing type `P` = PTR (stock trades); PTR
PDFs live at
`https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/{year}/{DocID}.pdf`.
Owner `SP` on a trade = spouse.

## Standalone CLI (no Azure required)

- `pelosi_monitor.py check|ack` — stdlib-only checker used before the Azure
  deployment; state in local `seen_filings.json`. Kept for ad-hoc runs.
