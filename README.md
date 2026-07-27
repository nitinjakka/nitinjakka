# Trading Suite

> Placeholder repo — work in progress. Not investment advice.

Intraday breakout strategy (ORB + VWAP) with full backtest artifacts, plus
standalone Robinhood account tools.

## Layout

| Path | What it is |
|---|---|
| `strategy-spec.md` | **The strategy** — complete platform-independent specification |
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
