# Kalshi 15-Min Crypto Strategy

Status: **PLANNING ONLY — do not place live orders.** Next step is the
backtest (rule 7). Drafted 2026-07-27.

## Core rules (Nitin's)

1. **Markets**: Crypto 15-minute expiry markets only (e.g. `KXBTC15M`).
2. **Timing**: Enter only in the last ~3 minutes before expiry.
3. **Entry**: Only buy the side priced at **95%+ odds** (ask >= 95c).
4. **Sizing**: Split available cash into 4 equal parts, one part per
   order (e.g. $100 -> $25 per order).
5. **Concurrency**: Up to 4 orders open at once — up to 100% of cash
   deployed ($25 + $25 + $25 + $25).
6. **Stop-loss**: If odds on the held side fall to **70%**, sell
   immediately and accept the loss.

## Adopted additions

7. **Backtest first.** Use Kalshi historical candlesticks + settled
   results to measure: of all markets at 95c with 3 min left, how often
   did that side win? Compare against the fee-adjusted breakeven before
   any live trading.
9. **Limit orders only, never market orders.** Books are thin late in
   the window; a market order can fill at 97–98c and erase the edge.
11. **No entries inside the final ~75 seconds.** Settlement is the
    average of the last 60 seconds of the CF Benchmarks index — inside
    that window the outcome is partly locked, spreads widen, and the
    stop-loss becomes unexecutable.
13. **Daily circuit breaker.** Stop for the day after 2 stop-outs or a
    25% drawdown. One 95c loss erases ~6+ wins; two in a day means
    conditions are wrong.
15. **Skip scheduled-news windows.** Fed, CPI, and similar events are
    when 95% favorites flip. Maintain a simple calendar filter.
16. **Log every trade.** Ticker, entry time, entry odds, cushion to
    target, exit price, P&L. The realized win rate at 95c is the number
    that decides whether to continue, resize, or stop.

## Key math (rules 8, 10, 12 — discussed in detail)

### Fees (8)
- Kalshi fee = `0.07 x price x (1 - price)` per contract at execution.
- At 95c entry: fee ~0.33c/contract -> net win ~4.67c (not 5c).
- $25 order at 95c = ~26 contracts: win nets ~$1.21 after fees.
- Breakeven win rate held-to-settlement: **~95.7%** (not 95%).

### Distance/volatility filter (10)
- A 95c price can be safe (big cushion, quiet market) or fragile
  (small cushion, fast market). The displayed odds lag the price.
- Rule: compute recent per-minute range from the last 3–5 one-minute
  candles; require **cushion >= 2–3x recent per-minute range**,
  otherwise skip even at 95c+.

### Stop-loss reality (12)
- Kalshi has no native stop order — a script must watch and react.
- Odds gap down fast (95 -> 88 -> 74 -> 61); expect exit fills around
  60–65c, not 70c. Budget each stop-out at **~30–35c/contract loss**
  (~$8–9 on a $25 position).
- On trigger, send an aggressive limit sell ~5c below the current bid
  to guarantee the fill.
- With a working stop, breakeven win rate drops from ~95.7% to
  **~87–88%** — the stop is the most valuable risk rule in the plan.
- After a stop-out, do not re-enter the same 15-min window.

## Open questions for next session

- Run the backtest (rule 7) and compute the realized win rate at
  95c / T-3min, after fees.
- Decide whether concurrent slots spread across coins (BTC/ETH/SOL are
  correlated — 4 crypto orders ~= 1 big bet) or across successive
  15-min windows.
- Paper-trade the stop-loss loop before any live order.

## Tooling

- `kalshi_trade.py` — quote odds, check balance, build/place limit
  orders (dry-run by default; `--live` + typed confirmation required
  to submit).
