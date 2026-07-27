#!/usr/bin/env python3
"""Backtest v2: distance-based strategy for Kalshi 15-min crypto markets.

Rules under test (Nitin, 2026-07-27):
  - At T-5 minutes before expiry, look at the underlying price vs the
    market's target ("TO BEAT") price.
  - Enter only if the difference is MORE than 0.05% in either
    direction; buy the side that is ahead (Up if above, Down if below).
  - If the difference later shrinks to 0.03% or less, close the
    position at the market (accept whatever it costs).
  - Otherwise hold to settlement.
  - Fees: 0.07 * p * (1-p) per contract on every fill.

Underlying prices come from Coinbase Exchange 1-minute candles as a
proxy for CF Benchmarks' RTI. To avoid exchange-basis error, the
target is recomputed from the same Coinbase series (price at window
open) rather than using Kalshi's floor_strike.

Usage:
  python3 kalshi_backtest_v2.py --days 7
"""

import argparse
import concurrent.futures as cf
import datetime as dt
import time

import requests

API = "https://api.elections.kalshi.com/trade-api/v2"
CB = "https://api.exchange.coinbase.com"

COINS = {  # kalshi series -> coinbase product
    "KXBTC15M": "BTC-USD",
    "KXETH15M": "ETH-USD",
    "KXSOL15M": "SOL-USD",
    "KXXRP15M": "XRP-USD",
    "KXDOGE15M": "DOGE-USD",
}

ENTRY_T = 300          # decide 5 minutes before close
ENTRY_DIFF = 0.0005    # need > 0.05% distance to enter
EXIT_DIFF = 0.0003     # close if distance shrinks to <= 0.03%
LAST_EXIT_BEFORE = 60  # no exits inside the final 60 s (settlement window)


def fee(p: float) -> float:
    return 0.07 * p * (1.0 - p)


def settled_markets(series: str, days: int) -> list[dict]:
    out, cursor = [], None
    min_close = int(time.time()) - days * 86400
    while True:
        params = {"series_ticker": series, "status": "settled",
                  "limit": 1000, "min_close_ts": min_close}
        if cursor:
            params["cursor"] = cursor
        d = requests.get(f"{API}/markets", params=params, timeout=30).json()
        out += d.get("markets", [])
        cursor = d.get("cursor")
        if not cursor or not d.get("markets"):
            return out


def coinbase_closes(product: str, days: int) -> dict[int, float]:
    """Minute-candle closes keyed by candle START timestamp."""
    end = int(time.time())
    start = end - days * 86400 - 1800
    closes: dict[int, float] = {}
    t = start
    while t < end:
        chunk_end = min(t + 300 * 60, end)
        r = requests.get(
            f"{CB}/products/{product}/candles",
            params={"granularity": 60,
                    "start": dt.datetime.fromtimestamp(
                        t, dt.timezone.utc).isoformat(),
                    "end": dt.datetime.fromtimestamp(
                        chunk_end, dt.timezone.utc).isoformat()},
            timeout=30)
        r.raise_for_status()
        for ts, _lo, _hi, _op, close, _vol in r.json():
            closes[int(ts)] = float(close)
        t = chunk_end
        time.sleep(0.15)  # stay under public rate limits
    return closes


def kalshi_candles(series: str, ticker: str, close_ts: int) -> list[dict]:
    for attempt in range(4):
        try:
            d = requests.get(
                f"{API}/series/{series}/markets/{ticker}/candlesticks",
                params={"start_ts": close_ts - 900, "end_ts": close_ts,
                        "period_interval": 1},
                timeout=30).json()
            return d.get("candlesticks", [])
        except Exception:
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)
    return []


def price_at(closes: dict[int, float], ts: int) -> float | None:
    """Underlying price AT time ts = close of the candle starting ts-60."""
    return closes.get(ts - 60)


def simulate(series: str, m: dict, closes: dict[int, float]) -> dict | None:
    close_ts = int(dt.datetime.fromisoformat(
        m["close_time"].replace("Z", "+00:00")).timestamp())
    open_ts = close_ts - 900

    target = price_at(closes, open_ts)
    p_entry = price_at(closes, close_ts - ENTRY_T)
    if target is None or p_entry is None:
        return None

    diff = (p_entry - target) / target
    if abs(diff) <= ENTRY_DIFF:
        return None
    side = "yes" if diff > 0 else "no"

    cs = kalshi_candles(series, m["ticker"], close_ts)
    by_ts = {c["end_period_ts"]: c for c in cs}
    ec = by_ts.get(close_ts - ENTRY_T)
    if not ec:
        return None
    if side == "yes":
        entry = float(ec["yes_ask"]["close_dollars"])
    else:
        entry = round(1.0 - float(ec["yes_bid"]["close_dollars"]), 4)
    if not 0.01 <= entry <= 0.99:
        return None

    # Scan the following minutes for the 0.03% exit condition.
    exited, exit_px = False, 0.0
    t = close_ts - ENTRY_T + 60
    while t <= close_ts - LAST_EXIT_BEFORE:
        p = price_at(closes, t)
        if p is not None and abs((p - target) / target) <= EXIT_DIFF:
            c = by_ts.get(t)
            if c:
                if side == "yes":
                    exit_px = float(c["yes_bid"]["close_dollars"])
                else:
                    exit_px = round(
                        1.0 - float(c["yes_ask"]["close_dollars"]), 4)
                exited = True
                break
        t += 60

    won = (m["result"] == side)
    if exited:
        pnl = exit_px - entry - fee(entry) - fee(exit_px)
    elif won:
        pnl = 1.0 - entry - fee(entry)
    else:
        pnl = -entry - fee(entry)

    return {"series": series, "ticker": m["ticker"], "side": side,
            "diff": diff, "entry": entry, "won": won,
            "exited": exited, "pnl": pnl}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    args = ap.parse_args()

    trades: list[dict] = []
    for series, product in COINS.items():
        closes = coinbase_closes(product, args.days)
        ms = settled_markets(series, args.days)
        print(f"{series}: {len(ms)} markets, "
              f"{len(closes)} underlying candles")
        failed = 0
        with cf.ThreadPoolExecutor(max_workers=8) as ex:
            futs = [ex.submit(simulate, series, m, closes) for m in ms]
            for f in cf.as_completed(futs):
                try:
                    r = f.result()
                except Exception:
                    failed += 1
                    continue
                if r:
                    trades.append(r)
        if failed:
            print(f"  warning: {failed} markets skipped on API errors")

    if not trades:
        print("No qualifying trades.")
        return

    n = len(trades)
    exits = [t for t in trades if t["exited"]]
    whip = [t for t in exits if t["won"]]
    dead = [t for t in trades if not t["won"] and not t["exited"]]
    avg_entry = sum(t["entry"] for t in trades) / n
    pnl = sum(t["pnl"] for t in trades)

    print(f"\n=== v2 distance strategy: enter |diff|>{ENTRY_DIFF:.2%} at "
          f"T-{ENTRY_T // 60}min, exit |diff|<={EXIT_DIFF:.2%} ===")
    print(f"trades                    : {n}  ({args.days} days, "
          f"{len(COINS)} coins)")
    print(f"avg entry price           : {avg_entry * 100:.1f}c")
    print(f"raw win rate of side      : {sum(t['won'] for t in trades) / n:.2%}")
    print(f"early exits (0.03% rule)  : {len(exits)}  ({len(exits) / n:.2%})"
          f"  of which would-have-won: {len(whip)}")
    print(f"held-to-zero losses       : {len(dead)}")
    print(f"avg P&L per contract      : {pnl / n * 100:+.2f}c (after fees)")
    print(f"return on capital deployed: {pnl / sum(t['entry'] for t in trades):+.2%}")

    per: dict[str, list] = {}
    for t in trades:
        per.setdefault(t["series"], []).append(t)
    print("\nper series:")
    for s, ts in sorted(per.items()):
        p = sum(t["pnl"] for t in ts)
        print(f"  {s:11s} trades={len(ts):4d} "
              f"win={sum(t['won'] for t in ts) / len(ts):.2%} "
              f"exits={sum(t['exited'] for t in ts):3d} "
              f"zeros={sum(1 for t in ts if not t['won'] and not t['exited']):3d} "
              f"pnl/ct={p / len(ts) * 100:+.2f}c")

    print("\nentry-odds buckets:")
    buckets = [(0.0, 0.80), (0.80, 0.90), (0.90, 0.95), (0.95, 1.0)]
    for lo, hi in buckets:
        ts = [t for t in trades if lo <= t["entry"] < hi]
        if not ts:
            continue
        p = sum(t["pnl"] for t in ts)
        print(f"  entry {lo * 100:3.0f}-{hi * 100:3.0f}c: n={len(ts):4d} "
              f"win={sum(t['won'] for t in ts) / len(ts):.2%} "
              f"pnl/ct={p / len(ts) * 100:+.2f}c")


if __name__ == "__main__":
    main()
