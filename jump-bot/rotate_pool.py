#!/usr/bin/env python3
"""
rotate_pool.py -- weekly satellite-30 rotation for watchlist.txt.

Runs Sunday evening (systemd timer) so the bot's midnight watchlist reload
picks the new pool up for Monday's open. Screens a ~190-name candidate
universe (candidates.txt, minus the core list and retired names) on:
  - price >= $20, 30d avg dollar volume >= $50M   (liquidity/spread floor)
  - close > 50-day SMA                            (uptrend; bot is long-only)
  - 14d avg daily range >= 1%                     (can reach the TP band)
Ranks survivors by 5-day momentum x volume surge (5d vol / 30d vol) and
writes the top 30 into the SATELLITE section of watchlist.txt.

Read-only market data + a text-file write. Places no orders.
"""
from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
ET = ZoneInfo("America/New_York")
load_dotenv(HERE / "modeb_bot.env")
import robin_stocks.robinhood as rh  # noqa: E402

WATCHLIST = HERE / "watchlist.txt"
CANDIDATES = HERE / "candidates.txt"
MARKER = "# --- SATELLITE-30"
N_SAT = 30
MIN_PRICE = 20.0
MIN_ADV_USD = 50e6
MIN_RANGE_PCT = 1.0


def log(msg):
    print(f"[{datetime.now(ET):%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def core_symbols():
    syms = []
    for ln in WATCHLIST.read_text().splitlines():
        if ln.startswith(MARKER):
            break
        if ln.strip() and not ln.strip().startswith("#"):
            syms += [s.strip().upper() for s in ln.split(",") if s.strip()]
    return syms


def screen(sym):
    bars = rh.stocks.get_stock_historicals(
        sym, interval="day", span="3month", bounds="regular") or []
    c = [float(b["close_price"]) for b in bars]
    h = [float(b["high_price"]) for b in bars]
    l = [float(b["low_price"]) for b in bars]
    v = [float(b["volume"]) for b in bars]
    if len(c) < 50:
        return None
    px = c[-1]
    adv = sum(v[-30:]) / 30 * px
    sma50 = sum(c[-50:]) / 50
    rng = sum((hh - ll) / cc for hh, ll, cc in
              zip(h[-14:], l[-14:], c[-14:])) / 14 * 100
    if px < MIN_PRICE or adv < MIN_ADV_USD or px <= sma50 \
            or rng < MIN_RANGE_PCT:
        return None
    mom = (c[-1] / c[-6] - 1) * 100                     # 5-day momentum %
    vsurge = (sum(v[-5:]) / 5) / max(sum(v[-30:]) / 30, 1)
    return mom * max(min(vsurge, 3.0), 0.5)             # clamp surge 0.5-3x


def main():
    user, pw = os.getenv("RH_USERNAME"), os.getenv("RH_PASSWORD")
    rh.login(username=user, password=pw, store_session=True, expiresIn=86400)
    core = core_symbols()
    cands = []
    for ln in CANDIDATES.read_text().splitlines():
        if ln.strip().startswith("#"):
            continue
        cands += [s.strip().upper() for s in ln.split() if s.strip()]
    cands = [s for s in dict.fromkeys(cands) if s not in core]
    log(f"screening {len(cands)} candidates (core={len(core)})...")
    scored = []
    for s in cands:
        try:
            sc = screen(s)
            if sc is not None:
                scored.append((sc, s))
        except Exception as e:
            log(f"{s}: skip ({e!r})")
        time.sleep(0.3)
    scored.sort(reverse=True)
    top = [s for _, s in scored[:N_SAT]]
    log(f"passed screen: {len(scored)}; selected top {len(top)}: {top}")

    lines = WATCHLIST.read_text().splitlines()
    keep = []
    for ln in lines:
        keep.append(ln)
        if ln.startswith(MARKER):
            break
    keep.append(f"# rotated {datetime.now(ET):%Y-%m-%d %H:%M} ET")
    for i in range(0, len(top), 10):
        keep.append(", ".join(top[i:i + 10]))
    WATCHLIST.write_text("\n".join(keep) + "\n")
    log("watchlist.txt satellite section updated")


if __name__ == "__main__":
    main()
