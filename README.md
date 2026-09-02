# Trading Suite

> Placeholder repo — work in progress. Not investment advice.

Intraday breakout strategy (ORB + VWAP) with full backtest artifacts, a long-dated
LEAPS strategy, plus standalone Robinhood account tools.

## Layout

| Path | What it is |
|---|---|
| `strategy-spec.md` | **Intraday strategy** — complete platform-independent specification |
| `leaps/` | **LEAPS strategy** — 12-18 month deep-ITM calls: entry, exit, sizing, screened candidates |
| `combined-suite.pine` | TradingView Pine v6 reference implementation (Module 5 = trade engine) |
| `options-bias-entry-exit.pine`, `swing-high-low-sr.pine` | earlier standalone Pine studies |
| `suite-backtest/` | Python backtest engines, raw 1m/5m data, options P&L results |
| `suite-backtest/bt_frac100.py` | $100 fractional-share portfolio backtest (Mode B long-only, 4 tickers) |
| `suite-backtest/bt_trend100.py` | $100 trend-filtered leveraged ETF backtest (TQQQ / 200-SMA) |
| `robinhood-tools/` | Robinhood scripts: multi-account balances, sell-all, option order test |

## Robinhood tools quick start

```
cd robinhood-tools
cp .env.example .env    # fill in credentials (never committed)
./balance_check.sh      # or balance_check.bat on Windows
```

## Key validated results (see strategy-spec.md §8 for methodology)

- ORB 1-min, 29 sessions: 90.3% win, PF 1.90 (84.4% held out)
- All-day mode, 1-min: 90.5% win, PF 1.29
- SPY/VOO: does NOT work (PF < 1 in every test) — trade NVDA/QQQ/TSLA/AAPL-class movers
- $100 accounts: options structurally unviable; fractional underlying or
  trend-filtered leveraged ETF are the viable vehicles (see bt_*100.py)

## LEAPS strategy (`leaps/`)

Separate book, separate timeframe — 12-18 month deep-ITM calls as a leveraged stock
substitute. **Do not mix its sizing or rules with the intraday spec.** Key finding from
the 2026-09-01 screen: higher IV costs *more* to carry AND delivers *less* leverage —
JPM (IV 23%) gives 3.28x at 4.4%/yr while MU (IV 65%) gives 1.92x at 14.2%/yr.

```
cd leaps && python3 screen.py     # reproduces every table in leaps/README.md
```

Note: unlike the intraday spec, the LEAPS screen is a point-in-time cross-sectional
screen on live quotes, **not** a backtested edge. See `leaps/README.md` §9.
