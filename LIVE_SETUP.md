# Going Live — Setup Guide

The bot places REAL orders only when started with `--live` AND the
correct credentials are present. Read every step.

## 1. Create a Kalshi API key (NOT your email/password)

Kalshi's API authenticates with an API Key ID + RSA private key. Your
account email/password cannot place API orders.

- Log into Kalshi -> Profile/Settings -> **API Keys** -> **Create API Key**.
- Copy the **API Key ID**.
- **Download the RSA private key** (`.pem`). It is shown once — save it.

## 2. Put credentials on the jump server (outside the repo)

```bash
mkdir -p /root/.kalshi
# move the downloaded .pem here (scp it up, or paste its contents):
#   /root/.kalshi/kalshi_key.pem
chmod 600 /root/.kalshi/kalshi_key.pem
```

Never put the key or ID inside /opt/nitinjakka (the repo) — the log
pusher would commit it to GitHub.

## 3. Export the environment variables

```bash
export KALSHI_API_KEY_ID="paste-your-key-id"
export KALSHI_PRIVATE_KEY_PATH="/root/.kalshi/kalshi_key.pem"
export KALSHI_LIVE_CONFIRM="YES"          # required opt-in
export KALSHI_MAX_ORDER_USD="20"          # per-order safety cap (tune this)
export NTFY_TOPIC="nitin-kalshi-bot-x7q2" # keep your phone alerts
pip install cryptography --break-system-packages   # needed for signing
```

## 4. Preflight test (does NOT trade)

```bash
cd /opt/nitinjakka
python3 - <<'PY'
import kalshi_live as k
print(k.preflight())   # prints "live auth OK, account balance $X, max order $Y"
PY
```

If this prints your real balance, auth works. If it errors, fix the
credentials before going further.

## 5. Start live — SMALL first

Start the watchdog pointed at the live bot. Fund the account with a
small amount you are willing to lose and keep KALSHI_MAX_ORDER_USD low
for the first day.

```bash
# stop any paper instance first
pkill -f 'watchdog.sh'; pkill -f 'python3 kalshi_bot'; pkill -f push_logs

# run live directly (foreground, watch the first few trades):
python3 kalshi_bot.py --live --hours 24 --log kalshi_live_log.csv
```

`--cash` is ignored in live mode — starting balance is read from your
real Kalshi account. Watch the first trade fill on Kalshi's app and
confirm the price/size match the notification before walking away.

## Safety rails built in

- Refuses to start unless KALSHI_LIVE_CONFIRM=YES.
- Refuses any single order above KALSHI_MAX_ORDER_USD.
- Buys with a marketable LIMIT at the ask (caps slippage vs a raw
  market order); stop-loss sells a few cents below the trigger to
  guarantee the exit fills.
- On any order rejection it logs, notifies your phone, and skips —
  it never crashes the loop or doubles up.

## Reality check before you scale

Live differs from paper in three ways that cost money: real fills can
be worse than the quoted ask, fees are real, and Kalshi settles on the
CF Benchmarks index (not the Coinbase price the bot reads) — so some
"wins" in paper are losses live. Prove it with tiny size for several
days before increasing KALSHI_MAX_ORDER_USD.
