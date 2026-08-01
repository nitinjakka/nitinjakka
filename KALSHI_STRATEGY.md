# Kalshi 15-Min Crypto Strategy

Status: **PLANNING ONLY — do not place live orders.** Next step is the
backtest (rule 7). Drafted 2026-07-27.

## Core rules (Nitin's)

1. **Markets**: Crypto 15-minute expiry markets only (e.g. `KXBTC15M`).
2. **Timing**: Enter only in the last ~5 minutes before expiry
   (changed from 3 minutes on 2026-07-27).
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

17. **Partial fills: re-place the remainder.** If an order executes
    only partially (e.g. $100 intended, $39.50 filled), immediately
    place a new order for the remaining ~$60 — but only if the entry
    conditions (95%+ odds, inside the time window) still hold at that
    moment; otherwise let the remainder go.

## Key math (rules 8, 10, 12 — discussed in detail)

### Fees (8)
- Kalshi fee = `0.07 x price x (1 - price)` per contract at execution.
- At 95c entry: fee ~0.33c/contract -> net win ~4.67c (not 5c).
- $25 order at 95c = ~26 contracts: win nets ~$1.21 after fees.
- Breakeven win rate held-to-settlement: **~95.7%** (not 95%).

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

## Bot v3 strategy validation (2026-08-01)

Rules: T-3min entry, spot gap >0.05% from target, leading side's ask
90-98c, stop 70c. 7 days / 5 coins / 652 qualifying trades (~93/day):

- Taker bound (pay ask + fee): **+0.11c/contract — positive even
  before maker savings**, unlike plain T-3 (-0.15c). The gap+odds
  combo works at T-3.
- Maker-adjusted (rest 1c below ask, no fee): **~+1.21c/contract,
  ~+1.27% per trade cycle** — pending live fill-rate data.
- BTC only: 104 trades, +1.54c/ct even as taker.
- Win rate 96.17% at avg 95.0c entry; 85 stop exits (71 whipsaw);
  11 gap-through zeros.
- Deployed as paper bot v3 (25% of cash per trade, ntfy alerts).

## Backtest v2: distance-based strategy (2026-07-27)

Rules tested (`kalshi_backtest_v2.py`): at T-5min, enter the leading
side if the underlying is > 0.05% away from the target (either
direction); close the position if the distance shrinks to <= 0.03%;
otherwise hold to settlement. Underlying = Coinbase 1-min candles as
a proxy for CF Benchmarks RTI (target recomputed from the same series
to avoid exchange-basis error).

7 days / 5 coins, 1,997 qualifying trades:

- As specified: avg entry 89.6c, side won 90.19%, net **-0.36c per
  contract after fees. Negative overall.**
- The 0.03% exit fired on 20.7% of trades; 251 of 414 exits would
  have won anyway (whipsaw cost dominates).
- 33 trades lost without ever triggering the exit (price gapped
  through 0.03% between minutes) — the exit rule alone does not
  remove disaster risk.
- By entry odds bucket:
    <80c: -1.88c | 80-90c: -2.53c | 90-95c: **+1.13c** | 95c+: +0.39c
- **Key finding: the distance signal only makes money when the
  market also agrees (odds >= 90c).** Distance + odds >= 90c
  combined: ~1,300 trades at **~+0.65c/contract** — the best
  configuration tested so far (v1 T-5min was +0.46c).

Same caveats as v1: one week of data, ask-price fills assumed, and
the Coinbase proxy adds noise near the 0.03-0.05% thresholds.

## Backtest update: T-5min entry (2026-07-27)

Re-run over 7 days / 5 series with entry moved from T-3min to T-5min
(883 qualifying entries at >= 95c):

- Avg entry 97.6c; the side won **98.64%** — about 1 point better
  than the price paid. **First positive configuration.**
- Net P&L **+0.46c per contract after fees** (+0.47% return per
  trade cycle). At T-3min the same week was -0.15c.
- Stops: 44 (5.0%), of which 32 whipsaws; still zero hold-to-zero.
- Per series: ETH +1.76c, SOL +0.72c, BTC +0.06c, DOGE +0.05c,
  XRP -0.17c.
- Caveats: edge is ~2 standard errors — real but thin; one week of
  data, one market regime; assumes taker fills at the ask and stop
  fills at 65c. Validate on more weeks before going live.

Interpretation: 5 minutes out, heavy favorites are still slightly
underpriced; by 3 minutes out the market has converged to fair value
minus fees.

## Backtest results (2026-07-27, rule 7, T-3min entry — superseded)

Run: `kalshi_backtest.py`, 3 days, 5 series (BTC/ETH/SOL/XRP/DOGE),
1,439 settled markets, 442 qualifying entries at >= 95c at T-3min.

- Avg entry 97.8c; the side won 97.74% of the time — i.e. **the market
  price almost exactly equals the true probability. No free edge.**
- Base strategy (95–99c entry, stop 70c -> 65c fill): **-0.12c per
  contract after fees.** Breakeven, slightly negative.
- Variants tested: entry 95–97c (-0.08c), 97–99c (-0.01c),
  90–95c (-1.56c — clearly worse); stop at 50c (-0.40c), stop at 30c
  (-0.21c), no stop (-0.23c, with 10 total-loss trades).
- Only optimistic assumption (stop fills exactly at 70c, no slippage)
  turns positive: +0.19c/ct — inside noise, and depends on fill luck.
- The 70c stop IS the best stop level tested (whipsaw at tighter
  stops costs more than it saves), and it eliminated all 10
  hold-to-zero disasters. Keep it. It just doesn't create edge.

**Conclusion: as specified, the strategy is a coin-flip minus fees.
Do not go live on these rules alone.** Two paths that could create
real edge, to test next:

1. **Maker entries.** Post a resting bid instead of lifting the ask —
   saves ~1c of spread per trade, which is larger than the entire
   current deficit. Trade-off: not all orders fill.
(A cushion/volatility filter was considered as rule 10 but removed
from the strategy on 2026-07-27.)

## Open questions for next session

- Backtest the maker-entry variant (the main remaining candidate
  for real edge).
- Decide whether concurrent slots spread across coins (BTC/ETH/SOL are
  correlated — 4 crypto orders ~= 1 big bet) or across successive
  15-min windows.
- Paper-trade the stop-loss loop before any live order.

## Tooling

- `kalshi_trade.py` — quote odds, check balance, build/place limit
  orders (dry-run by default; `--live` + typed confirmation required
  to submit).
