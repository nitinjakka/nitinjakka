# spread_cycler — repeat-cycle credit spread bot

Sells a short vertical credit spread, buys it back at a profit target, logs the
exit price, then re-opens at a lower target credit. Repeats up to `MAX_CYCLES`
times per session. Built to run on the jump server under `/opt/option_spread`.

**This places real multi-leg option orders when `LIVE=1`. Read the risk
section before you flip it.**

## Quick start

```bash
cd /opt/option_spread
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp spread_cycler.env.example spread_cycler.env   # fill in credentials
.venv/bin/python spread_cycler.py                # PAPER by default
```

Paper mode simulates fills at the spread mid and writes the same logs as live,
so you can run a full session and read `trades.csv` before risking anything.

## How a cycle works

1. **Pick** — scan listed strikes at least `MIN_OTM_PCT` out of the money and
   choose the vertical whose mid-credit is closest to this cycle's target.
2. **Sell** — limit order at the mid, re-priced by `PRICE_STEP` every
   `REPRICE_SECONDS` toward the natural price until filled or `ORDER_TIMEOUT`.
3. **Hold** — poll the spread's mid every `POLL_SECONDS`.
4. **Close** on whichever comes first:
   - **target** — mid ≤ credit × (1 − `PROFIT_PCT`/100)
   - **stop** — mid ≥ credit × `STOP_MULT`
   - **flatten** — clock reaches `FLATTEN_TIME`, closed at natural price
5. **Step down** — next target = min(previous target, achieved credit) −
   `CREDIT_STEP`, floored at `MIN_CREDIT`.

Every close appends a row to `trades.csv` with both prices, the P&L, and the
reason. State lives in `state.json` and resets each calendar day, so a restart
mid-session resumes rather than double-counting.

## Why "open below the last exit" can't reach 10 cycles

With `ENTRY_RULE=below_exit`, each cycle must open under the price the previous
one closed at. Taking profit at `PROFIT_PCT` means the exit is roughly
`credit × (1 − PROFIT_PCT/100)` — so **the credit shrinks by that factor every
cycle**. At the default 50%, it halves:

| Cycle | 1 | 2 | 3 | 4 |
|---|---|---|---|---|
| Credit | $0.32 | $0.16 | $0.08 | $0.04 |

It hits `MIN_CREDIT` on cycle 3 or 4 and stops. Reaching ten cycles from $0.32
would need a starting credit of about $164 on a $1-wide spread, which cannot
exist — max value is $1.00.

The number of cycles you actually get is:

```
cycles ≈ log(MIN_CREDIT / TARGET_CREDIT) / log(1 − PROFIT_PCT/100) + 1
```

To get ten cycles from $0.32 down to a $0.10 floor you need `PROFIT_PCT≈12` —
taking only 12% of each credit, about $3.90 on cycle 1 falling to $1.35 on
cycle 10. That's ten round trips and ten day trades for roughly $25 of gross
profit before commissions and slippage. Set `ENTRY_RULE=step` if you want the
cycle count to be the thing you control instead.

## Holding losers (`STOP_MULT=0`)

The default is now **no stop loss**: a spread that moves against you is held
until it becomes profitable. On a 0DTE contract that is not a guarantee of
recovery — the option expires the same day, so `FLATTEN_TIME` closes it at
whatever it's worth, which can be the full max loss (~$89 on a $1-wide spread
sold for $0.11). "Never close at a loss" only works when you can wait
indefinitely, and a 0DTE position cannot. Set `STOP_MULT=2.0` to cap each
trade's loss near one credit instead.

## Risk — read this

**The economics get worse every cycle.** A $1.00-wide spread sold for $0.32
risks $68 to make $32 — you need ~68% wins just to break even. `CREDIT_STEP`
lowers the credit each cycle while max loss stays at $100 minus the credit:

| Cycle | Credit | Risk | Reward | Break-even win rate |
|---|---|---|---|---|
| 1 | $0.32 | $68 | $32 | 68% |
| 4 | $0.24 | $76 | $24 | 76% |
| 7 | $0.16 | $84 | $16 | 84% |
| 10 | $0.11 | $89 | $11 | 89% |

By cycle 10 you need to be right ~9 times out of 10 to break even. Set
`CREDIT_STEP=0` to hold the ratio flat, or raise `MIN_CREDIT`.

**Other things that will bite you:**

- **0DTE assignment.** Anything still open at `FLATTEN_TIME` is closed with
  maximum urgency. If an ITM short call reaches expiry you get 100 short
  shares per contract. Never disable the flatten.
- **PDT.** Ten cycles is ten day trades. On a margin account under $25k this
  will flag you as a pattern day trader.
- **Ten cycles may not be reachable.** Theta burns the whole chain through the
  day; once the nearest tradable spread pays less than `MIN_CREDIT`, the bot
  stops. Getting ten sellable entries usually needs the underlying to keep
  moving, not a quiet drift.
- **Strike granularity.** SPY's $1-wide strikes step credit by roughly $0.09.
  A `CREDIT_STEP` much smaller than that won't reach a different strike — the
  target has to accumulate across cycles before the pick moves.
- **Unofficial API.** `robin_stocks` uses Robinhood's private endpoints. It is
  not sanctioned, and heavy automated order flow carries real account risk.

## Safety controls

| Control | What it does |
|---|---|
| `LIVE=0` | Default. Simulated fills, no orders sent. |
| `STOP` file | `touch /opt/option_spread/STOP` — no new cycles; open positions still exit normally. |
| `MAX_DAILY_LOSS` | Session realized-loss cap; stops opening once breached. |
| `STOP_MULT` | Per-trade stop loss. |
| `FLATTEN_TIME` | Hard close-everything deadline. |
| `ENTRY_CUTOFF` | No new cycles after this time. |
| `MAX_ENTRY_FAILS` | Gives up after N consecutive failed entries instead of retrying forever. |

## Running it on a schedule

`option-spread.service` runs one session and exits. Pair it with a timer that
fires on weekday mornings:

```bash
sudo systemctl enable --now option-spread.timer
sudo journalctl -u option-spread -f      # watch a live session
```

## Files

| File | Purpose |
|---|---|
| `spread_cycler.py` | The bot |
| `spread_cycler.env` | Credentials and tuning (gitignored) |
| `trades.csv` | One row per closed cycle |
| `state.json` | Resume state, resets daily |
| `logs/` | Per-day run logs |

*Not investment advice. Paper-trade a full session before going live.*
