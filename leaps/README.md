# LEAPS Strategy — Complete Specification

Version 1.0 (2026-09-02). Long-dated single-leg call strategy for liquid US large-caps.
Companion to `../strategy-spec.md` (intraday breakout). **These two do not interact** — this
one holds 12–18 months, that one is flat by 15:55 every day. Do not mix their sizing or rules.

All market data in §7 is a **live snapshot from 2026-09-01 close** (option marks and greeks)
pulled via the Robinhood API. Prices move; the *method* is the durable part. Re-run
`screen.py` before acting on any number here.

---

## 1. Purpose and scope

Buy deep in-the-money long-dated calls as a **leveraged stock substitute** on companies you
would be willing to own outright for two years. This is not a directional-bet strategy and
not a lottery-ticket strategy. The edge, such as it is, comes from three things:

1. **Financing cheaply.** A 0.80-delta LEAPS gives ~2.5–3.3× exposure per dollar for a
   carry cost that is currently 4.4–8.8%/yr on the quality names (§7).
2. **Buying vol when it is cheap** relative to the name's own history and to peers.
3. **Capping the downside at the premium** while keeping most of the upside slope.

The failure mode is equally specific: you pay the carry, the stock goes sideways, and you
lose 30% while a shareholder loses nothing. §6 exists to keep that from becoming -100%.

### 1.1 The central finding

The screen in §7 produced one result worth stating up front, because it inverts what most
people assume:

> **The high-IV "exciting" names give you LESS leverage AND cost MORE to hold.**

| | Hurdle (carry %/yr) | Leverage |
|---|---|---|
| JPM (IV 23.0) | **4.4%** | **3.28×** |
| MSFT (IV 32.3) | 6.4% | 2.85× |
| AMD (IV 56.8) | 11.8% | 2.06× |
| MU (IV 65.2) | **14.2%** | **1.92×** |

Higher IV inflates the premium, which *simultaneously* raises the carry cost and shrinks the
delta-dollars you control per premium dollar. Buying MU LEAPS instead of JPM LEAPS gets you
**37% less leverage for 3.2× the carrying cost.** If you want more risk, the correct lever is
*position size on a cheap-vol name*, never *a higher-vol underlying*.

---

## 2. Universe filter (a name must pass ALL of these)

| # | Filter | Threshold | Why |
|---|---|---|---|
| 1 | Market cap | ≥ $200B | LEAPS on smaller names have unusable spreads |
| 2 | Jan-2028 chain exists | listed & tradable | Confirms LEAPS cycle support |
| 3 | Open interest at target strike | ≥ 100 contracts | Exit liquidity in 12 months, not just today |
| 4 | Quoted spread | ≤ 5% of mark | You pay ~half of this twice |
| 5 | IV at target strike | ≤ 45% | Above this the carry hurdle exceeds ~9%/yr |
| 6 | Price vs 200-day SMA | **above it, by ≤ 20%** | Never finance a downtrend for 16 months — and never buy a 57%-extended one (see MU, §7.3) |
| 7 | Profitable, positive FCF | yes | You cannot roll out of a broken balance sheet |
| 8 | No binary event risk | no pending litigation/FDA/deal | LEAPS cannot be hedged cheaply |

Filters 5 and 6 do most of the work. Filter 6 is the one people skip and regret — see META
and ORCL in §7, which fail on trend alone.

Filters 3, 5 and 6 are **hard** — a fail is a no. Filter 4 (spread) is a **cost**, not a veto:
a name that misses it is tradable with patient limit orders but never with a market order.
See UNH at rank 5.

---

## 3. Contract selection (the entry, part 1 — *what* to buy)

### 3.1 Expiry
**Buy the January expiry 14–18 months out.** Today that is **2028-01-21** (16.6 months).

- Never buy under 12 months — theta acceleration begins around 9 months and is brutal under 6.
- Never buy over 24 months — you pay for time you will not use, and OI thins badly.
- Use **January** expiries specifically. They are the standard LEAPS cycle and carry
  materially more open interest than the Jun/Sep/Dec long-dated series.

### 3.2 Strike
**Hard floor: delta ≥ 0.70. Target 0.75–0.85. In practice: strike ≈ 78–80% of spot.**

Verified across all 17 contracts screened — 78–80% moneyness landed delta 0.78–0.89 every time.

**The delta rule is asymmetric, and the reason matters.** Delta means two different things
depending on which way you are comparing:

- **Within one name**, delta is the leverage dial. Deeper ITM = lower carry, lower breakeven,
  *less* leverage per dollar. The 0.75–0.85 target is the balance point.
- **Across names at the same moneyness**, a high delta just means *low IV* — which is better
  on every axis. JPM prints **0.89** at 79% of spot and is simultaneously the cheapest carry
  (4.4%/yr) and the highest leverage (3.28×) on the board.

So: **fail below 0.70, never fail above.** A hard 0.85 ceiling would have rejected JPM and
UNH — the two best trades in §7. Above ~0.90, just note that you are approaching a stock
substitute and check whether a higher strike gives more leverage per dollar.

Ranked ten, sorted by delta — the monotonic ordering is the whole argument:

| Sym | Δ | Leverage | Carry/yr | Breakeven |
|---|---|---|---|---|
| JPM | 0.89 | **3.28×** | **4.4%** | +6.0% |
| UNH | 0.87 | 3.03× | 4.9% | +6.8% |
| QQQ | 0.85 | 3.02× | 5.3% | +7.4% |
| MSFT | 0.82 | 2.85× | 6.4% | +8.8% |
| NVDA | 0.81 | 2.47× | 7.9% | +10.9% |
| META | 0.79 | **2.43×** | **8.8%** | +12.2% |

Why not ATM, concretely (NVDA, both real quotes from the same chain):

| Contract | Mark | Extrinsic | Carry/yr | Leverage | Breakeven move |
|---|---|---|---|---|---|
| **Jan-28 $170C** (0.81Δ) | $71.20 | $23.76 | **7.9%** | 2.47× | **+10.9%** |
| Jan-28 $220C (0.63Δ) | $44.30 | $44.30 | **14.7%** | 3.09× | **+21.6%** |

The ATM strike buys you 25% more leverage for **86% more carry** and **double the breakeven**.
That is a bad trade at every horizon. Deep ITM is not the conservative choice here — it is the
mathematically better one.

### 3.3 Never
- Never buy OTM LEAPS. All extrinsic, delta below 0.50, and you need a huge move just to flat.
- Never buy LEAPS on a name you would not buy shares of.
- Never buy the front-month to "test" the thesis — different instrument, different math.

---

## 4. Entry timing (the entry, part 2 — *when* to buy)

Three conditions. **All three must hold on a weekly close.**

1. **Trend** — Weekly close above the 200-day SMA, by no more than 20%. Both tails fail:
   below the line is a downtrend you would be financing; far above it (MU at +56.8%) is an
   extension you would be buying at the top of.
2. **Vol** — IV at the target strike ≤ 45%, and in the lower half of the name's own 1-year
   IV range. You are buying vega; buying it rich is the single most common LEAPS error.
3. **Location** — Price 5–20% below the 52-week high. Not at the high (paying up), not
   40%+ below it (that is a falling knife, and filter 6 usually already caught it).

### 4.1 Scaling in
Do not buy the full position in one order.

- **50%** on signal.
- **25%** on a 7–10% pullback that holds the 200-day SMA.
- **25%** on a second such pullback, or on a confirmed breakout to new highs.
- If neither pullback comes within 3 months, buy the remaining 50% and move on.

### 4.2 Order handling
LEAPS quotes are wide and thin. This matters more than it does on weeklies.

- **Always a limit order. Never market.** The NVDA $170C spread is $3.00 — a market order
  round-trip donates ~4% of premium.
- Start at the mid. Work up in $0.05 increments. Do not chase past mid + 25% of the spread.
- Trade 09:45–15:30 ET only. Opening and closing auctions have the worst LEAPS quotes.
- Size the order to the displayed bid size. If you need 10 contracts and the bid shows 6,
  split the order across days.

---

## 5. Position sizing

| Rule | Value |
|---|---|
| Max premium per position | **5%** of portfolio |
| Max total LEAPS premium | **20–25%** of portfolio |
| Max positions | 5–8 names, ≥3 distinct sectors |
| Correlated-cluster cap | **10%** in any one theme (AI/semis is ONE theme) |

Size on the assumption that **each position can go to zero.** That is not pessimism — a
0.80-delta LEAPS goes to zero if the stock is down 20% at expiry, and a 20% drawdown over
16 months is an ordinary event for every name in §7.

With a 5% cap and 5 positions, a simultaneous total loss on all of them costs 25% of the
portfolio. That is the actual worst case and you should be able to state it out loud before
you enter.

**On the semiconductor concentration in §7:** NVDA, TSM, MSFT, AAPL, AMZN, QQQ and META are
all substantially exposed to the same AI capex cycle. Treating them as seven independent
positions is the mistake this table is most likely to invite. Cap the cluster at 10%.

---

## 6. Exits

This is where most LEAPS positions are lost — not on entry selection but on having no exit
plan. Check these **weekly**, in this priority order.

### 6.1 Hard exits (mechanical, no discretion)

| # | Trigger | Action |
|---|---|---|
| **E1** | **DTE < 270 days (9 months)** | Roll out to the next January, or close. **Non-negotiable.** |
| **E2** | Premium −50% from cost | Close. Full stop. |
| **E3** | Weekly close below 200-day SMA | Close, or cut to half and set a hard 30-day re-test |
| **E4** | Thesis break (guidance cut, moat event, accounting) | Close on the news. Do not wait for the chart. |

**E1 is the most important rule in this document.** Theta on a 0.80-delta LEAPS is
approximately −$0.05/day today (real quote: MSFT $400C theta = −0.079). Inside 6 months it
accelerates by roughly 3–4×, and delta starts collapsing toward a binary. You are giving up
the entire structural advantage of the position. Roll at 9 months whether you are up or down.

### 6.2 Profit-taking (discretionary but pre-committed)

| # | Trigger | Action |
|---|---|---|
| **P1** | Premium +100% | Sell **half**. The remaining half is now house money. |
| **P2** | Delta ≥ 0.92 | Roll up to a fresh 0.80Δ strike, same expiry. Frees capital, resets leverage. |
| **P3** | Premium +200% | Sell **half of what remains** (25% of original). |
| **P4** | IV spike +15 vol points above entry | Consider closing. You are now short a rich vol position you bought cheap. |

P2 is the underrated one. A 0.95-delta LEAPS is a stock position with an expiry date attached —
all of the drawback, none of the leverage. Roll it back down to 0.80Δ and take capital off.

### 6.3 The roll (mechanics)

Roll as a **single spread order** (sell the near, buy the far, one ticket) — never as two
legs. Two legs on a wide LEAPS spread costs meaningfully more and leaves you naked between fills.

At the roll, re-run the §2 filters. **If the name no longer passes, do not roll it — close it.**
A roll is a fresh 16-month entry decision, not an administrative renewal. This is the single
most common way a disciplined LEAPS book turns into a bag of broken theses.

### 6.4 Income overlay (optional — poor man's covered call)

Once a position is up and DTE > 12 months, you may sell a 30–45 DTE call against it at
delta ≤ 0.25 and a strike above your LEAPS strike + net debit paid.

- Collect ~1–2%/month against the long premium, which directly offsets the §7 carry hurdle.
- **Never** sell a short strike below `long_strike + debit_paid` — that locks a structural loss.
- Close the short at 50% of max profit; do not manage it into expiry week.
- Stop the overlay entirely when the LEAPS hits E1 (9 months).

This is the highest-leverage improvement available to the strategy: on MSFT it can convert a
6.4%/yr carry cost into roughly break-even carry, which changes the flat-stock scenario in
§8 from −30% to roughly −5%.

---

## 7. Screen results — 2026-09-01 close

Universe: 17 large-caps + ETFs. Contract: **Jan-2028, strike ≈ 78–80% of spot.**
Score = 40% carry cost + 25% liquidity + 20% trend + 15% leverage. All figures are real quotes.

### 7.1 The ranked ten

| # | Sym | Contract (Jan-28) | Mark | IV | Δ | Carry/yr | Lev | Spr | OI | vs 200DMA | P/E | Score |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | **MSFT** | $400C | $145.20 | 32.3% | 0.83 | 6.4% | 2.85× | 2.3% | 3357 | +16.2% | 28.3 | **80.8** |
| 2 | **AAPL** | $260C | $92.58 | 30.9% | 0.83 | 6.1% | 2.91× | 2.6% | 2283 | +14.9% | 36.3 | **79.5** |
| 3 | **JPM** | $280C | $96.40 | 23.0% | 0.89 | **4.4%** | **3.28×** | 4.4% | 114 | +11.8% | **15.3** | **74.5** |
| 4 | **QQQ** | $560C | $199.75 | 28.0% | 0.85 | 5.3% | 3.02× | 2.3% | 260 | +7.9% | 34.6 | **69.6** |
| 5 | **UNH** | $310C | $113.35 | 26.8% | 0.87 | 4.9% | 3.04× | 5.8% | 309 | +13.1% | 25.0 | **67.9** |
| 6 | **AMZN** | $200C | $81.78 | 39.4% | 0.81 | 7.6% | 2.53× | 2.5% | 3248 | +6.8% | 20.9 | **59.6** |
| 7 | **NVDA** | $170C | $71.20 | 40.8% | 0.81 | 7.9% | 2.47× | 4.2% | 3647 | +10.9% | 27.9 | **58.5** |
| 8 | **TSM** | $330C | $131.28 | 40.6% | 0.80 | 8.2% | 2.52× | 2.7% | 340 | +11.7% | 30.0 | **53.9** |
| 9 | GOOGL | $260C | $106.85 | 37.1% | 0.82 | 6.9% | 2.58× | 4.0% | 457 | **−0.0%** | **16.8** | 42.5 |
| 10 | META | $460C | $189.18 | 43.2% | 0.79 | 8.8% | 2.43× | 2.7% | **77** | **−7.0%** | 21.6 | 32.4 |

### 7.2 Reading the table

**Tier 1 — buy now (ranks 1–4).** MSFT, AAPL, JPM and QQQ pass every §2 filter. Carry under
6.5%/yr, comfortably above the 200-day, real exit liquidity. MSFT and AAPL have the two best
liquidity profiles in the whole screen (OI 3357 / 2283, spreads 2.3% / 2.6%) and are the two
positions to open first. JPM has the cheapest carry on the board at 4.4%/yr and the highest
leverage at 3.28×, but note its OI of 114 is thin — scale in over several days.

**Rank 5 — UNH — best economics, worst execution.** Carry of 4.9%/yr and 3.04× leverage put
it second-best on pure economics. It **fails filter 4**: the quoted spread is 5.8% of mark
against a 5% limit. That is not disqualifying the way a trend break is, but it is a real cost
— a careless round trip donates ~6% of premium. Trade it only with patient mid-price limit
orders, and if you cannot fill within 2% of mid, skip it. Do not market-order this one.

**Tier 2 — buy on a pullback (ranks 6–8).** AMZN, NVDA and TSM are sound and pass all filters,
but 7.6–8.2%/yr carry means entry price matters much more. Wait for §4's 7–10% pullback rather
than paying up. NVDA at a 27.9 P/E is not expensive on earnings — the cost here is vol, not
valuation.

**Rank 9 — GOOGL — the most interesting name on the board.** Cheapest quality in the screen at
a 16.8 P/E, 18% off its high, moderate 6.9% carry. It scores low on exactly **one** input: it
closed at $335.02 against a 200-day SMA of $335.05 — sitting on the line to within four cents.
That is an inflection, not a downtrend. **It becomes a buy on the first weekly close that
reclaims the 200-day with conviction.** Its low score is a timing artifact, not a verdict on
the business. If it breaks down instead, filter 6 just saved you 16 months of carry.

**Rank 10 — META — do not buy yet, despite the temptation.** A 21.6 P/E and 26.8% off the high
looks like the value opportunity of the group. It fails two hard filters: 7.0% *below* its
200-day SMA (filter 6) and OI of just 77 contracts at the target strike (filter 3) — the
thinnest in the screen. You would be financing a downtrend for 16 months in a contract you may
struggle to exit. Revisit on a 200-day reclaim.

### 7.3 Explicitly excluded — high IV, and why

These were screened and rejected. They are the names retail LEAPS buyers gravitate toward.

| Sym | IV | Carry/yr | Lev | vs 200DMA | P/E | Verdict |
|---|---|---|---|---|---|---|
| MU | 65.2% | **14.2%** | 1.92× | **+56.8%** | 21.7 | Worst carry AND worst leverage in the screen, and 57% extended above its 200-day after an ~8× run off the 52-wk low |
| ORCL | 57.9% | 11.9% | 2.04× | **−16.8%** | 25.6 | −59% from its high and below the 200-day. Falling knife; fails filter 6 |
| AMD | 56.8% | 11.8% | 2.06× | +36.1% | 120.8 | P/E 120.8, 36% extended, and an 11.8%/yr hurdle on top |
| TSLA | 50.2% | 10.3% | 2.22× | **−11.0%** | 341.9 | P/E 341.9 and below the 200-day. Fails filter 6 |
| AVGO | 46.6% | 9.3% | 2.31× | **+0.0%** | 61.5 | Marginal IV miss (46.6% vs 45%), and — like GOOGL — sitting exactly on its 200-day ($369.68 vs $369.55). Worth a revisit if it reclaims trend *and* IV drops below 45% |
| SMH | 40.8% | 8.0% | 2.49× | +15.0% | 42.4 | Passes on vol and trend but has **31 contracts** of OI at the strike. Use QQQ for index exposure instead |

**MU needs +14.2% per year just to break even on carry.** JPM needs +4.4%. That is the whole
argument, and MU being 57% above its own 200-day is the second half of it.

## 8. What the payoff actually looks like

Worked example: **MSFT Jan-2028 $400C @ $145.20**, spot $501.02, $14,520 per contract.

| MSFT at expiry | Move | Option value | Option P&L | Stock P&L | Ratio |
|---|---|---|---|---|---|
| $300.61 | −40% | $0.00 | **−100%** | −40% | 2.50 |
| $400.82 | −20% | $0.82 | **−99%** | −20% | 4.97 |
| $450.92 | −10% | $50.92 | −65% | −10% | 6.49 |
| **$501.02** | **0%** | **$101.02** | **−30%** | **0%** | — |
| $551.12 | +10% | $151.12 | +4% | +10% | 0.41 |
| $601.22 | +20% | $201.22 | +39% | +20% | 1.93 |
| $701.43 | +40% | $301.43 | +108% | +40% | 2.69 |
| $751.53 | +50% | $351.53 | +142% | +50% | 2.84 |

Three things to internalise before trading this:

1. **Flat stock = −30%.** Doing nothing for 16 months costs you a third of the premium.
   That is the carry, and it is the real cost of the leverage.
2. **The loss ratio is worse than the gain ratio.** At −20% you lose 5× the shareholder's
   loss; at +20% you make only 1.9× their gain. Leverage is asymmetric *against* you in
   the middle of the distribution. It only pays above roughly +25%.
3. **+10% on the stock is roughly break-even.** Your true hurdle is not zero, it is +9–11%.

The §6.4 covered-call overlay is the main lever that improves row 4, which is why it is
worth the operational effort.

---

## 9. Findings an implementer must respect

1. **IV is the dominant variable, not the ticker.** Carry ranged 4.4%–14.2%/yr across the
   screen. Nothing else in the analysis moved outcomes as much.
2. **High IV reduces leverage.** Verified across all 17 contracts. Confirmed inverse
   relationship. This is the opposite of the common intuition.
3. **Deep ITM beats ATM on every metric that matters** — carry, breakeven, and decay —
   losing only on raw leverage, which you can restore with size.
4. **The 200-day SMA filter is not optional.** It removed three names that looked
   attractive on other dimensions: META (21.6 P/E, 27% off its high), ORCL (25.6 P/E,
   59% off its high) and TSLA. It also flagged the opposite failure mode — MU at **+56.8%
   above** its 200-day, which is not a trend confirmation but an extension warning. The
   filter wants price *above* the line and within ~15% of it, not far from it in either
   direction.
5. **Open interest at the strike is the binding liquidity constraint**, not the underlying's
   ADV. META trades 15.9M shares/day and has 77 contracts of OI at the Jan-28 $460 strike;
   SMH has 31. Meanwhile MSFT and AAPL carry 3357 and 2283. Check OI at the exact strike,
   never infer it from the stock's volume.
6. **Roll at 9 months, not 3.** Theta and delta decay both accelerate hard inside 6 months.
7. **Never mix this with the intraday spec.** `../strategy-spec.md` §9 notes that its
   options results depend on cheap high-gamma weeklies. That is the exact opposite instrument.
8. **Delta needs a floor, not a ceiling.** The 0.75–0.85 target is a within-name balance
   point, not a cross-name filter. Applied as a hard band it rejects JPM (0.89) and UNH
   (0.87) — which are the cheapest-carry, highest-leverage contracts in the screen. High
   delta at fixed moneyness is a *symptom of low IV*, and low IV is what you want.
   `evaluate.py` enforces the floor and only notes the ceiling.
9. **Spread is a cost, not a veto — but only if you respect it.** UNH has the second-best
   economics in the screen and a 5.8% spread. Tradable with limit orders; value-destroying
   without them.
10. **This screen has not been backtested.** Unlike `../strategy-spec.md` (101 sessions,
   walk-forward validated), §7 is a point-in-time cross-sectional screen on live quotes.
   The reasoning is sound and the data is real, but no historical edge has been demonstrated.
   Treat the rankings as a structured starting point for research, not a validated signal.

---

## 10. Defaults block

```
expiry              = January, 14-18 months out   (currently 2028-01-21)
delta_floor         = 0.70                        (hard)
target_delta        = 0.75 - 0.85                 (soft, no upper veto)
target_moneyness    = strike ~= 78-80% of spot
max_iv              = 45%
min_open_interest   = 100 contracts at strike
max_spread          = 5% of mark
trend_filter        = 0% < (price/200DMA - 1) <= 20%    (hard, both tails)
entry_location      = 5-20% below 52-week high
scale_in            = 50% / 25% / 25%
order_type          = LIMIT only, start at mid, cap at mid + 25% of spread
max_premium_per_pos = 5% of portfolio
max_total_premium   = 20-25% of portfolio
max_theme_cluster   = 10%  (AI/semis counts as ONE theme)
roll_trigger        = DTE < 270 days                    (hard)
stop_loss           = -50% premium                      (hard)
trend_stop          = weekly close < 200-day SMA        (hard)
profit_take         = +100% -> sell half; delta >= 0.92 -> roll up
review_cadence      = weekly
```

---

## 11. Doing this yourself

You do not need this repo, a screener, or an API. Six numbers off any option chain and
four divisions decide it. The tooling below just saves you the arithmetic.

### 11.1 The six inputs (all on one screen in any broker)

Pull up the option chain, select the **January expiry 14–18 months out**, and read off the
row nearest **79% of spot**:

| Input | Where |
|---|---|
| Spot | the quote |
| Strike | pick the row nearest `spot × 0.79` |
| Bid / Ask | the chain; `mark = (bid + ask) / 2` |
| Implied volatility | the chain (often a toggleable column) |
| Delta | the chain (enable greeks if hidden) |
| Open interest | the chain — **at that strike**, not the stock's volume |
| 200-day SMA | any chart with a 200-period MA on daily bars |

### 11.2 The four divisions

```
extrinsic  = mark − max(spot − strike, 0)
carry/yr   = extrinsic ÷ spot ÷ years_to_expiry     → want ≤ 6.5%, reject > 9%
leverage   = delta × spot ÷ mark                    → want ≥ 2.5×
breakeven  = (strike + mark − spot) ÷ spot          → want ≤ +10%
```

That is the entire quantitative core. **Carry is the one that decides it** — it is what you
pay per year to hold the leverage, and it ranged 4.4%–14.2% across the screen in §7.

### 11.3 The entry gate

Enter only if **all** of these hold:

- [ ] Delta ≥ 0.70
- [ ] IV ≤ 45%
- [ ] Open interest ≥ 100 at the strike
- [ ] 0% < (spot ÷ 200-day SMA − 1) ≤ 20%  — above the line, not extended above it
- [ ] Carry ≤ 9%/yr
- [ ] 12–18 months to expiry
- [ ] You would happily own the shares for two years

Any single failure is a no. Spread > 5% is not a veto but means limit orders only.

### 11.4 Write the exit down *at entry*

This is the step that separates a plan from a hope. Before you place the order, compute and
record four numbers — they never change afterward:

| | Formula | Meaning |
|---|---|---|
| **Roll date** | `expiry − 270 days` | Hard. Roll or close, up or down. |
| **Stop price** | `mark × 0.50` | Hard. Close if the mark prints below it. |
| **Trend stop** | the 200-day SMA value | Hard. Close on a *weekly* close below it. |
| **Take-half** | `mark × 2.00` | Sell half at +100%. The rest is house money. |

Then check, **once a week, in this order** — it takes two minutes:

1. Is DTE < 270? → roll or close. Not a judgment call.
2. Is the mark below the stop? → close.
3. Did it close the week below the 200-day? → close.
4. Is delta ≥ 0.92? → roll up to a fresh ~0.80 strike, take capital off.
5. Is it up 100%? → sell half.
6. Otherwise → do nothing. Close the laptop.

Step 6 is most weeks, and doing nothing is the correct action. The failure mode of a
16-month position is not missing an exit; it is fiddling with it.

### 11.5 Let the tool do it

```bash
cd leaps

python3 evaluate.py --preset msft   # replay a worked example, no setup
python3 evaluate.py --manual        # type the six numbers from ANY broker
python3 evaluate.py MSFT            # live, reuses robinhood-tools/.env
python3 evaluate.py MSFT --strike 400

python3 screen.py                   # rebuild the §7 ranking table
```

`evaluate.py` prints the four numbers, every filter as PASS/FAIL/COST, a bid ceiling, and a
pre-computed **exit card** with the actual dollar levels and dates from §11.4. `--manual`
needs no credentials and no network — it works with numbers read off a screenshot.

> Note: `--manual` and `--preset` are tested. **Live mode is not** — this environment has no
> Robinhood credentials, so the `robin_stocks` path has never been executed. Check its first
> output against your broker's chain before trusting it.

---

## 12. Reproducing the tables

```bash
cd leaps
python3 screen.py          # recomputes every metric in §7 from the embedded snapshot
```

`screen.py` carries the 2026-09-01 quotes inline so the table is reproducible as-is. To
re-screen against live quotes, replace the `SNAPSHOT` block with fresh values — the
Robinhood MCP calls that produced it are documented in the file header.

---

*Not investment advice. §7 is a point-in-time screen, not a backtested edge — see §9.10.
LEAPS can and do expire worthless; size per §5 and assume every position can go to zero.*
