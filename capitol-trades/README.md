# Capitol Trades Monitor — Nancy Pelosi PTR Watcher

Watches for new stock-trade disclosures (Periodic Transaction Reports) filed by
Rep. Nancy Pelosi (CA-11) and emails a summary when one appears.

## Data source

The official House Clerk financial-disclosure index:
`https://disclosures-clerk.house.gov/public_disc/financial-pdfs/{year}FD.zip`

This is the primary source that capitoltrades.com and similar sites are built
on. (capitoltrades.com itself blocks automated access, so we go straight to
the source.)

## How it works

1. A scheduled Claude Code Routine runs every few hours.
2. It runs `pelosi_monitor.py check`, which downloads the disclosure index
   **3 separate times** and only reports filings when all 3 fetches agree
   (triple verification). New filings are anything not in `seen_filings.json`.
3. If there are new filings, the session re-runs the check two more times,
   spaced minutes apart, downloads the filing PDF, extracts every trade
   (asset, ticker, buy/sell, trade date, amount range, owner), and emails a
   summary to the account owner via Gmail.
4. Only after the email sends successfully does it run
   `pelosi_monitor.py ack` and commit the updated `seen_filings.json` back to
   this branch — so a failed email is retried on the next run.

## Files

- `pelosi_monitor.py` — stdlib-only checker (`check` / `ack` subcommands)
- `seen_filings.json` — DocIDs of filings already processed and emailed

## Manual usage

```bash
python3 pelosi_monitor.py check --delay 30   # 3 verified fetches, prints new filings as JSON
python3 pelosi_monitor.py ack                # mark everything currently published as seen
```

Filing type reference: `P` = Periodic Transaction Report (the stock trades);
owner `SP` on a trade = spouse. PTR PDFs live at
`https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/{year}/{DocID}.pdf`.
