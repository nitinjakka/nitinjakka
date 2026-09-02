#!/usr/bin/env python3
"""
evaluate.py — decide a single LEAPS candidate yourself, in about 60 seconds.

Answers two questions the README states as rules but does not compute for you:
    1. ENTRY  — does this specific contract pass, and at what price do I bid?
    2. EXIT   — what are the actual dollar levels and dates, decided NOW?

The point of (2): exits fail because they are written as rules ("stop at -50%")
instead of as numbers ("close if the mark prints below $72.60"). This prints the
numbers. Write them down at entry; you will not have to think again.

Two modes
---------
  MANUAL (works with any broker, no credentials, no dependencies):
      python3 evaluate.py --manual
      python3 evaluate.py --manual --preset msft     # replay a worked example

  LIVE (reuses robinhood-tools/.env credentials):
      python3 evaluate.py MSFT
      python3 evaluate.py MSFT --strike 400

Only six numbers are needed, all visible on any option chain:
    spot, strike, mark (or bid+ask), delta, open interest, 200-day SMA.

See README.md for where each threshold comes from.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys

# --- thresholds: keep in lockstep with README.md §2 and §10 ----------------
MAX_IV_PCT      = 45.0
MIN_OI          = 100
MAX_SPREAD_PCT  = 5.0      # a COST, not a veto — see README §7.2 (UNH)
MIN_DELTA       = 0.70     # HARD floor: below this, extrinsic and breakeven explode
TARGET_DELTA    = (0.75, 0.85)
SOFT_DELTA_MAX  = 0.90     # above this you own a stock substitute, not leverage
MIN_TREND_PCT   = 0.0      # must be above the 200-day
MAX_TREND_PCT   = 20.0     # ...but not extended far above it (see MU)
MIN_DTE_ENTRY   = 365      # never open inside 12 months
MAX_DTE_ENTRY   = 550      # ~18 months
ROLL_DTE        = 270      # hard roll trigger, README §6.1 E1
STOP_PCT        = 0.50     # close at -50% of premium
TAKE_1, TAKE_2  = 2.00, 3.00   # +100% -> half off; +200% -> half of the rest
ROLLUP_DELTA    = 0.92

PRESETS = {
    # name: spot, strike, mark, iv%, delta, oi, bid, ask, sma200, expiry
    "msft":  ("MSFT", 501.02, 400, 145.200, 32.3, .825, 3357, 143.50, 146.90, 431.12, "2028-01-21"),
    "jpm":   ("JPM",  354.95, 280,  96.400, 23.0, .890,  114,  94.30,  98.50, 317.52, "2028-01-21"),
    "meta":  ("META", 578.54, 460, 189.175, 43.2, .793,   77, 186.60, 191.75, 622.30, "2028-01-21"),
    "mu":    ("MU",   933.44, 740, 377.625, 65.2, .777,  211, 371.25, 384.00, 595.45, "2028-01-21"),
}

G, R, Y, B, D = "\033[32m", "\033[31m", "\033[33m", "\033[1m", "\033[0m"


def _c(txt, col, on):
    return f"{col}{txt}{D}" if on else txt


class Verdict:
    def __init__(self):
        self.checks = []          # (label, ok, detail, hard)

    def add(self, label, ok, detail, hard=True):
        self.checks.append((label, ok, detail, hard))
        return ok

    @property
    def hard_fails(self):
        return [c for c in self.checks if not c[1] and c[3]]

    @property
    def soft_fails(self):
        return [c for c in self.checks if not c[1] and not c[3]]


def evaluate(sym, spot, strike, mark, iv, delta, oi, bid, ask, sma200,
             expiry, color=True):
    today = dt.date.today()
    dte   = (expiry - today).days
    yrs   = dte / 365.25

    intrinsic = max(spot - strike, 0.0)
    extrinsic = mark - intrinsic
    carry     = extrinsic / spot * 100 / yrs if yrs > 0 else float("inf")
    leverage  = delta * spot / mark
    be_price  = strike + mark
    be_pct    = (be_price - spot) / spot * 100
    spread    = (ask - bid) / mark * 100 if mark else float("inf")
    trend     = (spot / sma200 - 1) * 100
    moneyness = strike / spot * 100

    v = Verdict()
    # Delta has a HARD floor and only a SOFT ceiling, and the reason is subtle:
    #   Within one name, delta is the leverage dial — deeper ITM means lower carry
    #   and lower breakeven but LESS leverage per dollar.
    #   Across names at the same moneyness, a high delta just means low IV, which is
    #   better on every axis. JPM prints 0.89 at 79% of spot and is the cheapest,
    #   highest-leverage trade on the board. A hard 0.85 cap would reject it.
    # So: fail low, note high.
    if delta < MIN_DELTA:
        v.add("Delta >= 0.70", False,
              f"{delta:.2f} — too close to ATM; extrinsic and breakeven explode")
    elif delta > SOFT_DELTA_MAX:
        v.add("Delta <= 0.90", False,
              f"{delta:.2f} — near a stock substitute; a higher strike may give "
              f"more leverage per dollar", hard=False)
    else:
        inband = TARGET_DELTA[0] <= delta <= TARGET_DELTA[1]
        v.add("Delta in range", True,
              f"{delta:.2f}  (strike is {moneyness:.0f}% of spot)"
              + ("" if inband else "  — outside the 0.75-0.85 target but acceptable"))
    v.add("DTE 12-18 months", MIN_DTE_ENTRY <= dte <= MAX_DTE_ENTRY,
          f"{dte} days ({yrs:.2f} yr) to {expiry}")
    v.add("IV <= 45%", iv <= MAX_IV_PCT, f"{iv:.1f}%")
    v.add("Open interest >= 100", oi >= MIN_OI, f"{oi} contracts at this strike")
    v.add("Above 200-day SMA", trend >= MIN_TREND_PCT,
          f"{trend:+.1f}%  (spot {spot:.2f} vs SMA {sma200:.2f})")
    v.add("Not >20% extended", trend <= MAX_TREND_PCT, f"{trend:+.1f}% above 200DMA")
    v.add("Spread <= 5% of mark", spread <= MAX_SPREAD_PCT,
          f"{spread:.1f}%  (${ask - bid:.2f} wide)", hard=False)

    w = 78
    print("\n" + "=" * w)
    print(f"  {sym}  ${strike:g}C  exp {expiry}   —   mark ${mark:.2f}  "
          f"(${mark * 100:,.0f} per contract)")
    print("=" * w)

    print(f"\n{_c('THE FOUR NUMBERS', B, color)}   (everything else is commentary)\n")
    print(f"  Extrinsic paid    ${extrinsic:>8.2f}   = mark - intrinsic "
          f"(${mark:.2f} - ${intrinsic:.2f})")
    print(f"  Carry cost        {carry:>8.1f}%/yr = extrinsic / spot / years")
    print(f"  Leverage          {leverage:>8.2f}x   = delta x spot / mark")
    print(f"  Breakeven         {be_pct:>+8.1f}%   = stock must reach ${be_price:.2f} by expiry")

    if carry <= 6.5:   note = _c("cheap carry — this is the good end of the range", G, color)
    elif carry <= 9.0: note = _c("moderate carry — entry price matters, wait for a pullback", Y, color)
    else:              note = _c("EXPENSIVE — you are paying too much for vol", R, color)
    print(f"\n  -> {note}")

    print(f"\n{_c('ENTRY CHECKS', B, color)}\n")
    for label, ok, detail, hard in v.checks:
        tag = _c(" PASS ", G, color) if ok else (
              _c(" FAIL ", R, color) if hard else _c(" COST ", Y, color))
        print(f"  [{tag}] {label:<24} {detail}")

    print(f"\n{_c('VERDICT', B, color)}\n")
    if v.hard_fails:
        print("  " + _c("DO NOT ENTER", R, color) + " — hard filter(s) failed:")
        for label, _, detail, _ in v.hard_fails:
            print(f"     - {label}: {detail}")
        print("\n  Hard filters are not judgment calls. Re-check when they clear.")
        return
    if v.soft_fails:
        print("  " + _c("ENTER WITH CARE", Y, color) +
              " — all hard filters pass, but execution will cost you:")
        for label, _, detail, _ in v.soft_fails:
            print(f"     - {label}: {detail}")
        print("  Limit orders only. If you cannot fill within 2% of mid, skip it.")
    else:
        print("  " + _c("ENTER", G, color) + " — all filters pass.")

    mid = (bid + ask) / 2
    print(f"\n{_c('HOW TO BID', B, color)}\n")
    print(f"  Mid ${mid:.2f}.  Start there. Work up in $0.05 steps.")
    print(f"  Hard cap ${mid + 0.25 * (ask - bid):.2f} (mid + 25% of spread). Never market-order.")
    print(f"  Trade 09:45-15:30 ET only.")
    print(f"  Scale in 50/25/25: first tranche now, then on 7-10% pullbacks that hold the 200DMA.")

    roll_by  = expiry - dt.timedelta(days=ROLL_DTE)
    print(f"\n{_c('EXIT CARD  — write these down now', B, color)}\n")
    print(f"  {'ROLL BY (hard)':<22} {roll_by}   ({(roll_by - today).days} days from today)")
    print(f"  {'STOP  (hard)':<22} close if mark < ${mark * STOP_PCT:>8.2f}   (-50% of premium)")
    print(f"  {'TREND STOP (hard)':<22} close on a WEEKLY close below ${sma200:.2f}")
    print(f"  {'TAKE HALF':<22} mark >= ${mark * TAKE_1:>8.2f}   (+100%)")
    print(f"  {'TAKE HALF AGAIN':<22} mark >= ${mark * TAKE_2:>8.2f}   (+200%)")
    print(f"  {'ROLL UP':<22} when delta >= {ROLLUP_DELTA} (roughly spot "
          f"> ${strike / 0.62:,.0f})")
    print(f"\n  Max loss ${mark * 100:,.0f}/contract — the whole premium — if {sym} "
          f"< ${strike:g} ({(strike / spot - 1) * 100:+.0f}%) at expiry.")
    print(f"  Size so that outcome costs <= 5% of the portfolio.")

    print(f"\n{_c('WHAT IT PAYS', B, color)}\n")
    print(f"  {'STOCK':>9}{'MOVE':>8}{'OPTION':>10}{'STOCK':>9}")
    print(f"  {'-' * 36}")
    for pct in (-30, -20, -10, 0, 10, 20, 30, 50):
        s = spot * (1 + pct / 100)
        op = (max(s - strike, 0) - mark) / mark * 100
        col = R if op < 0 else G
        print(f"  {s:>9.2f}{pct:>7}%{_c(f'{op:>9.0f}%', col, color)}{pct:>8}%")
    flat = (max(spot - strike, 0) - mark) / mark * 100
    print(f"\n  Flat stock = {_c(f'{flat:.0f}%', R, color)}. That is the carry. "
          f"You need {be_pct:+.1f}% just to flat.")
    print("=" * w + "\n")


def ask_float(prompt, default=None):
    while True:
        raw = input(f"  {prompt}" + (f" [{default}]" if default is not None else "") + ": ").strip()
        if not raw and default is not None:
            return float(default)
        try:
            return float(raw.replace("$", "").replace("%", "").replace(",", ""))
        except ValueError:
            print("    ...that is not a number, try again")


def manual(preset=None):
    if preset:
        p = PRESETS[preset]
        print(f"\nReplaying preset '{preset}' (2026-09-01 quotes).")
        return evaluate(p[0], p[1], p[2], p[3], p[4], p[5], p[6], p[7], p[8], p[9],
                        dt.date.fromisoformat(p[10]))
    print("\nRead these off your broker's option chain. Pick the January expiry")
    print("14-18 months out, then the strike nearest 79% of spot.\n")
    sym    = input("  Ticker: ").strip().upper() or "???"
    spot   = ask_float("Spot price")
    print(f"    -> aim for a strike near ${spot * 0.79:,.2f}")
    strike = ask_float("Strike")
    bid    = ask_float("Bid")
    ask_   = ask_float("Ask")
    mark   = (bid + ask_) / 2
    print(f"    -> mark = ${mark:.2f}")
    iv     = ask_float("Implied volatility %")
    delta  = ask_float("Delta")
    oi     = ask_float("Open interest")
    sma    = ask_float("200-day SMA of the stock")
    exp    = input("  Expiry (YYYY-MM-DD) [2028-01-21]: ").strip() or "2028-01-21"
    evaluate(sym, spot, strike, mark, iv, delta, int(oi), bid, ask_, sma,
             dt.date.fromisoformat(exp))


def live(sym, strike=None, expiry=None):
    """Fetch everything from Robinhood, reusing robinhood-tools/.env."""
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "..", "robinhood-tools"))
    try:
        import robin_stocks.robinhood as rh
        from robinhood_balance import login
    except ImportError as e:
        sys.exit(f"Live mode needs the robinhood-tools deps: {e}\n"
                 f"  cd robinhood-tools && pip install -r requirements.txt\n"
                 f"Or use:  python3 evaluate.py --manual")

    login()
    try:
        spot = float(rh.stocks.get_latest_price(sym)[0])

        if expiry is None:                       # nearest January 14-18 months out
            today = dt.date.today()
            cands = [dt.date(y, 1, 21) for y in (today.year + 1, today.year + 2)]
            cands = [d for d in cands if MIN_DTE_ENTRY <= (d - today).days <= MAX_DTE_ENTRY]
            if not cands:
                sys.exit("No January expiry in the 12-18 month window.")
            expiry = cands[0]

        # snap to a real listed expiry near that January
        chain  = rh.options.get_chains(sym) or {}
        listed = sorted(dt.date.fromisoformat(d)
                        for d in chain.get("expiration_dates", []))
        if listed:
            expiry = min(listed, key=lambda d: abs((d - expiry).days))

        opts = rh.options.find_options_by_expiration(
            sym, expirationDate=expiry.isoformat(), optionType="call") or []
        if not opts:
            sys.exit(f"No calls listed for {sym} {expiry}.")

        target = strike if strike is not None else spot * 0.79
        best   = min(opts, key=lambda o: abs(float(o["strike_price"]) - target))
        strike = float(best["strike_price"])

        md = best if best.get("delta") else (
            rh.options.get_option_market_data_by_id(best["id"]) or [{}])[0]

        bid, ask_ = float(md["bid_price"]), float(md["ask_price"])
        hist = rh.stocks.get_stock_historicals(sym, interval="day", span="year")
        closes = [float(b["close_price"]) for b in hist][-200:]
        sma200 = sum(closes) / len(closes)
        if len(closes) < 200:
            print(f"  ! only {len(closes)} daily bars available — SMA is over "
                  f"{len(closes)} days, not 200. Treat the trend check as approximate.")

        evaluate(sym.upper(), spot, strike, (bid + ask_) / 2,
                 float(md["implied_volatility"]) * 100, float(md["delta"]),
                 int(md["open_interest"]), bid, ask_, sma200, expiry)
    finally:
        rh.logout()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Evaluate one LEAPS candidate.")
    ap.add_argument("symbol", nargs="?", help="ticker (live mode)")
    ap.add_argument("--manual", action="store_true", help="type numbers from any broker")
    ap.add_argument("--preset", choices=sorted(PRESETS), help="replay a worked example")
    ap.add_argument("--strike", type=float, help="override strike (live mode)")
    ap.add_argument("--expiry", help="override expiry YYYY-MM-DD (live mode)")
    a = ap.parse_args()

    if a.manual or a.preset:
        manual(a.preset)
    elif a.symbol:
        live(a.symbol.upper(), a.strike,
             dt.date.fromisoformat(a.expiry) if a.expiry else None)
    else:
        ap.print_help()
        print("\nQuick start:  python3 evaluate.py --preset msft")
