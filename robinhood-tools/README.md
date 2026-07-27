# Robinhood balance tools

A small standalone Python script that logs into Robinhood directly (via the
`robin_stocks` library, no MCP) and prints all of your account balances:
total portfolio value, cash, buying power, equity positions, and crypto.
Structured so you can add buying/selling of stocks and options later.

## Quick start (Windows - easiest)

1. Extract this folder to `E:\Tradeing\robinhood` (or wherever you like).
2. Open `.env` in Notepad and fill in your Robinhood email and password. Save.
3. Double-click **`balance_check.bat`**.

The first run automatically creates a `.venv` folder here and installs
everything into it (needs internet, happens once). Every run after that just
launches the script. Nothing is installed system-wide.

## Quick start (macOS / Linux)

```bash
# edit .env with your credentials first, then:
chmod +x balance_check.sh
./balance_check.sh
```

## Manual setup (if you prefer)

```bash
pip install -r requirements.txt
# edit .env and fill in RH_USERNAME / RH_PASSWORD (and RH_MFA_SECRET if you use app 2FA)
python robinhood_balance.py
```

Example output:

```
============================================
ACCOUNT SUMMARY
============================================
  Total portfolio value : $12,345.67
  Day change            : +$123.45
  Cash                  : $1,000.00
  Buying power          : $1,000.00

============================================
EQUITY POSITIONS
============================================
  AAPL         10 sh        $2,000.00   (1.2%)
  ...
```

## Logs

Every run writes its full output (and any error traceback) to a timestamped
file in the `logs\` folder next to the script, e.g.:

```
logs\balance_2026-07-23_18-45-12.log
```

The folder is created automatically on first run. Old logs are never deleted —
each execution gets its own file, so you can look back at any day's balances.
Delete old files whenever you like; `logs/` is in `.gitignore`.

## A few important notes

- **This uses Robinhood's unofficial/private API.** `robin_stocks` is widely
  used but not sanctioned by Robinhood; endpoints can change and heavy
  automated use could put your account at risk. Use it for personal,
  read-only balance checks and go easy on request volume.
- **MFA:** If you have SMS/email two-factor on, the first run will prompt you
  to type the code. If you use an authenticator app, put the TOTP *secret*
  (the setup key, not the 6-digit code) in `RH_MFA_SECRET` and codes are
  generated automatically.
- **Session token:** After the first successful login a token is cached under
  `~/.tokens`, so you usually won't be re-prompted every run.
- **Keep `.env` private.** It holds your credentials — it's already in
  `.gitignore`.

## Selling an entire position

`sell_all.bat` (Windows) / `sell_all.sh` (macOS/Linux) sells **all** of one
symbol at market price. It checks your crypto positions first, then equities:

```
sell_all.bat SOL
```

**There is no confirmation prompt — running the command places the order
immediately.** It prints an order preview, sends a market order, and if
Robinhood rejects the market order (it often 422s crypto market sells) it
automatically retries as a limit sell ~1% below the current price, which
fills right away. Every run is logged to `logs\sell_SOL_<timestamp>.log`
including Robinhood's raw order response.

**These are real market orders against your real account.** Crypto trades
24/7; stock market orders placed outside market hours sit as pending until
the open.

## Adding more trading later

`trading.py` is a stub wired to the same login. It exposes `buy_market`,
`sell_market`, `buy_limit`, `sell_limit`, etc., each behind a `DRY_RUN` guard
so nothing fires until you set `DRY_RUN = False`. Options order helpers exist
in `robin_stocks.robinhood.orders` too — see the notes at the bottom of
`robinhood_balance.py`.
