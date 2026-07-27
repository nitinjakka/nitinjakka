# Intraday Breakout Strategy — Complete Specification

Version: 1.0 (2026-07-18). Validated on real 1-min and 5-min data for NVDA, QQQ, TSLA, AAPL
(SPY tested and excluded — see §9). This document is self-contained: everything needed to
implement the strategy on any platform (Pine Script, Python, C#, etc.) is defined here.

---

## 1. Purpose and scope

An intraday long-options (or long/short equity) strategy for liquid US large-caps.
It trades **momentum breakouts confirmed by VWAP**, with an asymmetric exit profile:
small fixed profit target, wide structural stop, always flat by the close.
Direction "CALL" = bullish (buy the underlying or a call); "PUT" = bearish.

All times are US/Eastern (ET). Regular session: 09:30–16:00. All signals evaluate on
**completed bar closes** — never on intrabar ticks.

## 2. Data requirements

- OHLCV bars of the underlying at 1-minute resolution (5-minute also works; 1-min tested better).
- Regular-session bars only (exclude pre/post market). Volume is required (VWAP).
- No indicator may use future data. Pivot-based levels are only "known" after their
  confirmation lag (§4.5).

## 3. Session state (reset at 09:30 each day)

- `OR_high`, `OR_low`: highest high / lowest low of the first **5 minutes** (09:30:00–09:34:59).
  The opening range is "formed" from the 09:35 bar onward.
- `day_high`, `day_low`: running session extremes **as of the previous completed bar**
  (exclude the current bar when testing breakouts against them).
- `trades_today`: entry counter, capped (§6).
- `minutes_since_open` = minutes elapsed since 09:30.

## 4. Indicators (standard definitions)

1. **VWAP** — session-anchored: cumulative(typical_price × volume) / cumulative(volume),
   typical_price = (H+L+C)/3, reset each day at 09:30.
2. **ATR(14)** — Wilder smoothing (RMA), on the trading timeframe.
3. **EMA9, EMA21** — on close, trading timeframe (used only by the optional pullback mode).
4. **Pivot S/R levels** — pivot high = a bar whose high is the max of 10 bars on each side
   (pivot low mirrored). A pivot is only CONFIRMED 10 bars after it forms (no lookahead).
   Keep the 3 most recent confirmed levels per side.
   `nearest_res` = lowest confirmed pivot-high above current close;
   `nearest_sup` = highest confirmed pivot-low below current close.

## 5. Entry signals

The strategy has two validated entry modes (run ONE of them; "both" was not tested):

### Mode A — ORB (opening-range breakout): one trade per day
Fire on the FIRST bar close after 09:35 and before 12:00 (minutes_since_open in [5, 150)) where:
- CALL: close > OR_high AND close > VWAP
- PUT:  close < OR_low  AND close < VWAP
Once either fires, no more ORB signals that day (even after the trade closes).

### Mode B — Session breakout (all-day): up to 10 trades per day  [default]
From 09:35 until 15:30 (minutes_since_open in [5, 360)), whenever FLAT, fire on a bar close where:
- CALL: close > day_high (prior-bar running high) AND close > VWAP
- PUT:  close < day_low  (prior-bar running low)  AND close < VWAP
Note: the first Mode-B signal of the day is usually the same as the ORB signal.

### Entry filter (both modes) — room to the nearest level
Skip a CALL if `nearest_res` exists and (nearest_res − close)/close < 0.25%.
Skip a PUT  if `nearest_sup` exists and (close − nearest_sup)/close < 0.25%.
(Don't buy a breakout straight into a confirmed level.)

### Optional Mode B+ — add with-trend pullback entries (coverage, not edge; see §9)
When flat and no breakout signal this bar, also fire:
- CALL: close > VWAP AND EMA9 > EMA21 AND close crosses above EMA9 this bar
  AND min(low of last 11 bars) <= EMA21 (a genuine dip happened) AND close < day_high.
- PUT: mirror image.
Pullback entries use a different stop (§6).

Only one position at a time. Entry price = the signal bar's close.

## 6. Exits (checked every bar, in this priority order)

For a CALL position (PUT is the exact mirror):
1. **STOP** — if bar low <= stop_price → exit at stop_price (at bar open if it gapped through).
2. **TARGET** — if bar high >= target_price → exit at target_price (at open if gapped through).
3. **TIME** — if bars_held >= 390 (a full day of 1-min bars) → exit at close. (Rarely hit; EOD hits first.)
4. **EOD** — if minutes_since_open >= 385 (15:55) → exit at close. Never hold overnight.

Stop and target are FIXED at entry (no trailing):
- **Stop (breakout entries, both modes): the opposite side of the opening range.**
  CALL stop = OR_low; PUT stop = OR_high. (This is the validated stop. An ATR alternative,
  entry ∓ 3.0×ATR, tested slightly worse.)
- **Stop (pullback entries): entry ∓ 2.5 × ATR(14).**
- **Target: entry ± k × ATR(14)**, where k = **0.5 for Mode A (ORB)** and **0.75 for Mode B**.
  Then CAP the target at the nearest confirmed pivot level if it is closer:
  CALL: target = min(target, nearest_res); PUT: target = max(target, nearest_sup).

Conservative backtest fill rule: if one bar spans both stop and target, assume the STOP filled first.

## 7. Option-contract selection (if trading options rather than the underlying)

- Buy-to-open only (long calls / long puts). One contract sizing unit per signal.
- **Expiry: the Friday of the current week** (0–4 days to expiry).
- **Strike: nearest out-of-the-money.** CALL: smallest listed strike >= entry underlying price.
  PUT: largest listed strike <= entry underlying price.
- Exit the option when the underlying hits the §6 exit, market order.
- Real-premium spot check (22 trades, Jul 2026): 73% of trades profitable on premium,
  avg +5.0%/trade raw, +2.9% after ~$0.06 round-trip spread. Premium losers cluster where
  the underlying move is small relative to premium — see §9 practical notes.

## 8. Validated performance (do not expect better than this)

Underlying-move win rates, conservative fills, 5 tickers unless noted:

| Test | Window | Result |
|---|---|---|
| Mode A on 5-min bars | 101 sessions (Feb–Jul 2026) | 85.2% win, PF 1.27; 81.8% win on the 2 months never used for tuning |
| Mode A on 1-min bars | 29 sessions (Jun–Jul 2026) | 90.3% win, PF 1.90 (84.4% win on held-out third) |
| Mode B on 1-min bars | 29 sessions | 90.5% win, PF 1.29, ~8 trades/day/ticker (92.9% held-out) |
| Mode B+ (with pullback) | 29 sessions | 87.8% win, PF 1.19 (86.9% held-out) |

Profile: ~87% small winners (avg ≈ +0.16% underlying), ~13% large losers (avg ≈ −0.7%).
Expectancy is positive but concentrated; skipping signals or widening targets breaks the math.

## 9. Findings an implementer must respect (all empirically tested)

1. **SPY does not work** (74–86% win but PF 0.81–0.94 in every test): its opening ranges are
   too tight for the stop geometry and its moves too small to beat option friction. Trade
   NVDA / QQQ / TSLA / AAPL-class movers.
2. **Counter-trend fades at S/R were tested and FAILED** (54% ≈ coin flip). Do not add
   "rejection at resistance" entries.
3. **Confluence/momentum-indicator entries failed** (EMA/RSI/MACD/ADX vote flips: ≤75% win,
   PF < 1). Indicator votes are context, not entries.
4. **Requiring indicator-bias agreement on breakouts made results worse** — the bias lags
   at 09:35. Do not add it as a filter.
5. **VWAP confirmation matters for direction quality; the 0.25% room filter matters.**
   Keep both.
6. **Pullback entries (Mode B+) are ~86% accurate but ~breakeven expectancy** (PF ~0.9
   standalone). Include only as optional coverage; size them smaller.
7. Bigger targets lower win rate roughly linearly (1.0×ATR ≈ 78–88%); smaller targets
   (0.4×ATR) raise accuracy to ~93% but can thin the profit factor to ~1.0 after costs.
   0.5 (ORB) / 0.75 (all-day) are the tested sweet spots.
8. **Options practicality:** premiums only reliably beat spread+theta when contracts are
   cheap/high-gamma — Thu/Fri of expiry week and bigger movers. Early-week ATM weeklies
   with fat premiums turned several underlying wins into premium losses.
9. Position sizing must assume routine −60%…−70% premium losses on stop-outs (~1 in 7 trades).
   Take every signal; do not cherry-pick.

## 10. Suggested defaults block (for any implementation)

```
timeframe            = 1 minute
session              = 09:30–16:00 ET, regular hours only
or_minutes           = 5
signal_window        = [5, 150) min from open (Mode A) | [5, 360) (Mode B)
vwap_confirm         = true
sr_room_filter_pct   = 0.25
atr_len              = 14
target_atr_mult      = 0.5 (Mode A) | 0.75 (Mode B)
stop                 = opposite side of opening range (breakouts) | 2.5*ATR (pullbacks)
sr_target_cap        = true (3 levels/side, pivot 10/10, 10-bar confirmation lag)
max_trades_per_day   = 1 (Mode A) | 10 (Mode B)
eod_flat_minute      = 385  (15:55 ET)
tickers              = NVDA, QQQ, TSLA, AAPL  (not SPY)
options              = this-week-Friday expiry, nearest OTM strike, long only
```

---
*Backtest artifacts and reproduction scripts: E:\Nitin_Hadoop\Claude\suite-backtest\
(backtest.py = 5-min engine, bt1m.py = 1-min engine + all modes). Reference implementation
in Pine Script v6: E:\Nitin_Hadoop\Claude\combined-suite.pine (Module 5).*
*Not investment advice. Past results, especially over 29–101 sessions, do not guarantee anything.*
