#!/usr/bin/env python3
"""
LEAPS candidate screener — reproduces every table in README.md §7 and §8.

Data source
-----------
SNAPSHOT below was pulled 2026-09-01 (close) via the Robinhood MCP tools:

    get_equity_fundamentals(symbols=[...])           -> 52w range, P/E, market cap
    get_equity_quotes(symbols=[...])                 -> spot (close.price)
    get_option_chains(underlying_symbol=SYM)         -> confirm 2028-01-21 is listed
    get_option_instruments(chain_symbol=SYM,
        expiration_dates='2028-01-21', type='call',
        strike_price=K)                              -> instrument id
    get_option_quotes(instrument_ids=[...])          -> mark, IV, delta, OI, bid/ask
    get_equity_technical_indicators(symbol=SYM,
        type='sma', period=200, interval='day')      -> 200-day SMA

Equity spot and option marks are both taken from the 2026-09-01 session so the
greeks are consistent with the underlying price they were computed against.

To re-screen: replace SNAPSHOT with fresh values, keep the columns identical.
Strikes were chosen at ~78-80% of spot, which lands delta 0.78-0.89 in practice.

Usage:  python3 screen.py
"""

import datetime as dt

EXPIRY = dt.date(2028, 1, 21)
AS_OF  = dt.date(2026, 9, 2)

# sym, spot, strike, mark, iv, delta, oi, bid, ask, sma200, pe, wk52_lo, wk52_hi
SNAPSHOT = [
    ("QQQ",   707.64, 560, 199.750, .2804, .8527,  260, 197.50, 202.00, 656.08,  34.6, 555.60,  748.65),
    ("JPM",   354.95, 280,  96.400, .2296, .8898,  114,  94.30,  98.50, 317.52,  15.3, 279.10,  366.50),
    ("UNH",   396.30, 310, 113.350, .2681, .8684,  309, 110.05, 116.65, 350.38,  25.0, 255.97,  461.62),
    ("AAPL",  325.13, 260,  92.575, .3094, .8299, 2283,  91.35,  93.80, 283.07,  36.3, 225.95,  344.57),
    ("MSFT",  501.02, 400, 145.200, .3227, .8250, 3357, 143.50, 146.90, 431.12,  28.3, 349.20,  553.72),
    ("GOOGL", 335.02, 260, 106.850, .3707, .8240,  457, 104.70, 109.00, 335.05,  16.8, 206.20,  408.61),
    ("AMZN",  254.92, 200,  81.775, .3941, .8103, 3248,  80.75,  82.80, 238.79,  20.9, 196.00,  287.20),
    ("NVDA",  217.44, 170,  71.200, .4084, .8086, 3647,  69.70,  72.70, 196.08,  27.9, 164.07,  236.54),
    ("SMH",   545.22, 430, 176.000, .4076, .8037,   31, 173.50, 178.50, 474.20,  42.4, 281.74,  671.83),
    ("TSM",   414.00, 330, 131.275, .4063, .7977,  340, 129.50, 133.05, 370.77,  30.0, 225.63,  479.00),
    ("AVGO",  369.68, 290, 127.275, .4656, .7944,  432, 125.50, 129.05, 369.55,  61.5, 287.17,  495.00),
    ("META",  578.54, 460, 189.175, .4324, .7933,   77, 186.60, 191.75, 622.30,  21.6, 520.26,  790.80),
    ("TSLA",  356.09, 280, 126.675, .5022, .7880,  406, 125.75, 127.60, 400.20, 341.9, 297.38,  498.83),
    ("ORCL",  141.32, 110,  54.575, .5791, .7860,  651,  53.45,  55.70, 169.79,  25.6, 114.50,  345.72),
    ("AMD",   459.61, 360, 174.725, .5681, .7841,  609, 172.55, 176.90, 337.72, 120.8, 149.22,  584.73),
    ("MU",    933.44, 740, 377.625, .6524, .7767,  211, 371.25, 384.00, 595.45,  21.7, 114.25, 1255.00),
]

# Every 200-day SMA above was fetched via get_equity_technical_indicators
# (type='sma', period=200, interval='day') for the 2026-09-01 bar. None are estimated.

# Ranked-ten universe (README §7.1). The rest are the §7.3 exclusions.
RANKED = ["MSFT", "AAPL", "JPM", "QQQ", "UNH", "AMZN", "NVDA", "TSM", "GOOGL", "META"]

# --- §2 universe filters ---------------------------------------------------
MAX_IV, MIN_OI, MAX_SPREAD, MAX_EXTENSION = 0.45, 100, 5.0, 20.0

T = (EXPIRY - AS_OF).days / 365.25


def metrics(row):
    sym, S, K, M, iv, d, oi, bid, ask, sma, pe, lo, hi = row
    intrinsic = max(S - K, 0.0)
    extrinsic = M - intrinsic
    return dict(
        sym=sym, spot=S, strike=K, mark=M, iv=iv * 100, delta=d, oi=oi,
        extrinsic=extrinsic,
        ext_pct_spot=extrinsic / S * 100,          # total time-premium as % of notional
        carry=extrinsic / S * 100 / T,             # annualised hurdle, %/yr
        leverage=d * S / M,                        # delta-dollars per premium dollar
        breakeven=(K + M - S) / S * 100,           # % move needed to flat at expiry
        spread=(ask - bid) / M * 100,
        trend=(S / sma - 1) * 100,
        cap_saved=(1 - M / S) * 100,
        rng52=(S - lo) / (hi - lo) * 100,
        dd=(S / hi - 1) * 100,
        pe=pe,
    )


def filters(m):
    """§2 hard filters (3, 5, 6). Returns list of failure reasons.

    Filter 4 (spread) is reported here too, but README §7.2 treats it as a cost to be
    managed with limit orders rather than a veto — see UNH at rank 5.
    """
    f = []
    if m["iv"] > MAX_IV * 100:  f.append(f"IV {m['iv']:.0f}%>45%")
    if m["oi"] < MIN_OI:        f.append(f"OI {m['oi']}<100")
    if m["spread"] > MAX_SPREAD:f.append(f"spread {m['spread']:.1f}%>5%")
    if m["trend"] < 0:          f.append(f"{m['trend']:.1f}% below 200DMA")
    elif m["trend"] > MAX_EXTENSION:
        f.append(f"{m['trend']:.0f}% extended >200DMA")
    return f


def nrm(x, lo, hi):
    return max(0.0, min(100.0, 100 * (x - lo) / (hi - lo)))


def score(m):
    """40% carry / 25% liquidity / 20% trend / 15% leverage."""
    cost = nrm(15.0 - m["carry"], 3.0, 11.0)
    lev  = nrm(m["leverage"], 1.9, 3.35)
    liq  = 0.5 * nrm(min(m["oi"], 4000) ** 0.5, 5, 63) + 0.5 * nrm(6.5 - m["spread"], 0.5, 4.5)
    tr   = 0.0 if m["trend"] < 0 else nrm(m["trend"], 0, 15)
    return .40 * cost + .15 * lev + .25 * liq + .20 * tr


def bar(title):
    print(f"\n{title}\n{'=' * len(title)}")


def main():
    rows = [metrics(r) for r in SNAPSHOT]
    by = {m["sym"]: m for m in rows}

    print(f"LEAPS screen — Jan-{EXPIRY.year} ({EXPIRY}), {T:.2f} yr out, quotes as of 2026-09-01")
    print(f"Strike selection: ~78-80% of spot (targets delta 0.75-0.85)")

    bar("§7.1  RANKED TEN")
    h = (f"{'#':>2} {'SYM':<6}{'K':>6}{'MARK':>9}{'IV%':>7}{'Δ':>6}{'CARRY/y':>9}"
         f"{'LEV':>6}{'SPR%':>6}{'OI':>6}{'v200DMA':>9}{'P/E':>7}{'SCORE':>7}")
    print(h); print("-" * len(h))
    ranked = sorted((by[s] for s in RANKED), key=lambda m: -score(m))
    for i, m in enumerate(ranked, 1):
        flag = "" if not filters(m) else "  <-- FAILS: " + ", ".join(filters(m))
        print(f"{i:>2} {m['sym']:<6}{m['strike']:>6}{m['mark']:>9.2f}{m['iv']:>7.1f}"
              f"{m['delta']:>6.2f}{m['carry']:>8.1f}%{m['leverage']:>6.2f}{m['spread']:>6.1f}"
              f"{m['oi']:>6}{m['trend']:>8.1f}%{m['pe']:>7.1f}{score(m):>7.1f}{flag}")

    bar("§7.3  EXCLUDED — high IV")
    h2 = f"{'SYM':<6}{'IV%':>7}{'CARRY/y':>9}{'LEV':>6}{'BE%':>7}{'P/E':>7}  REASON"
    print(h2); print("-" * (len(h2) + 20))
    for m in sorted((m for m in rows if m["sym"] not in RANKED), key=lambda m: -m["iv"]):
        why = ", ".join(filters(m)) or "IV elevated; revisit below 45%"
        print(f"{m['sym']:<6}{m['iv']:>7.1f}{m['carry']:>8.1f}%{m['leverage']:>6.2f}"
              f"{m['breakeven']:>7.1f}{m['pe']:>7.1f}  {why}")

    bar("§1.1  CARRY vs LEVERAGE — the inverse relationship")
    print("Higher IV costs MORE to hold and delivers LESS leverage:\n")
    print(f"{'SYM':<7}{'IV%':>7}{'CARRY/y':>10}{'LEVERAGE':>10}")
    print("-" * 34)
    for m in sorted(rows, key=lambda m: m["iv"]):
        print(f"{m['sym']:<7}{m['iv']:>7.1f}{m['carry']:>9.1f}%{m['leverage']:>10.2f}")
    lo, hi = min(rows, key=lambda m: m["iv"]), max(rows, key=lambda m: m["iv"])
    print(f"\n{lo['sym']} (IV {lo['iv']:.0f}%) vs {hi['sym']} (IV {hi['iv']:.0f}%): "
          f"{hi['carry']/lo['carry']:.1f}x the carry cost for "
          f"{(1 - hi['leverage']/lo['leverage'])*100:.0f}% LESS leverage.")

    bar("§3.2  WHY DEEP ITM BEATS ATM — NVDA, same chain")
    S = by["NVDA"]["spot"]
    print(f"{'CONTRACT':<18}{'MARK':>9}{'EXTRINSIC':>11}{'CARRY/y':>9}{'LEV':>7}{'BREAKEVEN':>11}")
    print("-" * 65)
    for K, M, d in ((170, 71.20, .8086), (220, 44.30, .6302)):
        ext = M - max(S - K, 0)
        print(f"NVDA Jan-28 ${K}C{'':<3}{M:>9.2f}{ext:>11.2f}"
              f"{ext/S*100/T:>8.1f}%{d*S/M:>7.2f}{(K+M-S)/S*100:>10.1f}%")
    print("\nATM buys 25% more leverage for 86% more carry and 2x the breakeven.")

    bar("§8  PAYOFF — MSFT Jan-2028 $400C")
    m = by["MSFT"]
    S0, K, M = m["spot"], m["strike"], m["mark"]
    print(f"Spot ${S0:.2f}, premium ${M * 100:,.0f}/contract, "
          f"{m['delta'] * 100:.1f} delta-shares vs {int(M * 100 // S0)} shares outright\n")
    print(f"{'AT EXPIRY':>11}{'MOVE':>8}{'VALUE':>10}{'OPT P&L':>10}{'STOCK':>8}{'RATIO':>8}")
    print("-" * 55)
    for pct in (-40, -20, -10, 0, 10, 20, 40, 50):
        S = S0 * (1 + pct / 100)
        v = max(S - K, 0)
        op = (v - M) / M * 100
        r = f"{op/pct:>8.2f}" if pct else f"{'—':>8}"
        print(f"{S:>11.2f}{pct:>7}%{v:>10.2f}{op:>9.0f}%{pct:>7}%{r}")
    print(f"\nFlat stock = {(max(S0-K,0)-M)/M*100:.0f}%. True breakeven = "
          f"{m['breakeven']:+.1f}% on the underlying.")
    print("Losses are levered ~5x at -20%; gains only ~1.9x at +20%.")
    print("The §6.4 covered-call overlay is what fixes the flat-stock row.")


if __name__ == "__main__":
    main()
