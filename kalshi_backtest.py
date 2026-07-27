#!/usr/bin/env python3
"""Backtest the 15-min crypto strategy against Kalshi historical data.

Strategy under test (see KALSHI_STRATEGY.md):
  - At T-5 minutes before close, if one side's ask is >= 95c (and <= 99c),
    buy that side.
  - Stop-loss: if the held side's bid trades down to 70c before close,
    exit; we assume a realistic fill at 65c (slippage budget).
  - Fees: 0.07 * price * (1 - price) per contract, on entry and on a
    stop-loss exit. Winning settlement has no exit fee.

Usage:
  python3 kalshi_backtest.py --days 3 --series KXBTC15M KXETH15M KXSOL15M
"""

import argparse
import concurrent.futures as cf
import datetime as dt
import time

import requests

API = "https://api.elections.kalshi.com/trade-api/v2"

ENTRY_MIN = 0.95   # only buy at >= 95c ...
ENTRY_MAX = 0.99   # ... and <= 99c (at 1.00 there is nothing to earn)
ENTRY_T = 300      # decide 5 minutes (300 s) before close
STOP_TRIGGER = 0.70
STOP_FILL = 0.65   # assumed real fill after slippage


def fee(price: float) -> float:
    return 0.07 * price * (1.0 - price)


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


def candles(series: str, ticker: str, close_ts: int) -> list[dict]:
    d = requests.get(
        f"{API}/series/{series}/markets/{ticker}/candlesticks",
        params={"start_ts": close_ts - 900, "end_ts": close_ts,
                "period_interval": 1},
        timeout=30,
    ).json()
    return d.get("candlesticks", [])


def simulate(series: str, m: dict) -> dict | None:
    """Return a trade record if the strategy would have entered, else None."""
    close_ts = int(dt.datetime.fromisoformat(
        m["close_time"].replace("Z", "+00:00")).timestamp())
    try:
        cs = candles(series, m["ticker"], close_ts)
    except Exception:
        return None
    by_ts = {c["end_period_ts"]: c for c in cs}
    entry_candle = by_ts.get(close_ts - ENTRY_T)
    if not entry_candle:
        return None

    yes_ask = float(entry_candle["yes_ask"]["close_dollars"])
    yes_bid = float(entry_candle["yes_bid"]["close_dollars"])
    no_ask = round(1.0 - yes_bid, 4)  # buy No by lifting 1 - yes_bid

    if ENTRY_MIN <= yes_ask <= ENTRY_MAX:
        side, entry = "yes", yes_ask
    elif ENTRY_MIN <= no_ask <= ENTRY_MAX:
        side, entry = "no", no_ask
    else:
        return None

    won = (m["result"] == side)

    # Stop-loss check over the candles after entry.
    stopped = False
    for c in cs:
        if c["end_period_ts"] <= close_ts - ENTRY_T:
            continue
        if side == "yes":
            held_bid_low = float(c["yes_bid"]["low_dollars"])
        else:  # our bid for No = 1 - yes_ask; its low = 1 - yes_ask.high
            held_bid_low = round(1.0 - float(c["yes_ask"]["high_dollars"]), 4)
        if held_bid_low <= STOP_TRIGGER:
            stopped = True
            break

    # P&L per contract, after fees.
    if stopped:
        pnl = STOP_FILL - entry - fee(entry) - fee(STOP_FILL)
    elif won:
        pnl = 1.0 - entry - fee(entry)
    else:
        pnl = -entry - fee(entry)  # held to zero (stop never printed)

    return {"series": series, "ticker": m["ticker"], "side": side,
            "entry": entry, "won": won, "stopped": stopped, "pnl": pnl}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=3)
    p.add_argument("--series", nargs="+",
                   default=["KXBTC15M", "KXETH15M", "KXSOL15M",
                            "KXXRP15M", "KXDOGE15M"])
    args = p.parse_args()

    jobs = []
    for s in args.series:
        ms = settled_markets(s, args.days)
        print(f"{s}: {len(ms)} settled markets in last {args.days}d")
        jobs += [(s, m) for m in ms]

    trades = []
    with cf.ThreadPoolExecutor(max_workers=12) as ex:
        futs = [ex.submit(simulate, s, m) for s, m in jobs]
        for f in cf.as_completed(futs):
            r = f.result()
            if r:
                trades.append(r)

    if not trades:
        print("No qualifying trades found.")
        return

    n = len(trades)
    wins = [t for t in trades if t["won"] and not t["stopped"]]
    stops = [t for t in trades if t["stopped"]]
    dead = [t for t in trades if not t["won"] and not t["stopped"]]
    whipsaw = [t for t in stops if t["won"]]  # stopped out but side won anyway
    avg_entry = sum(t["entry"] for t in trades) / n
    total_pnl = sum(t["pnl"] for t in trades)

    print(f"\n=== {n} qualifying entries (>= {ENTRY_MIN:.0%} at "
          f"T-{ENTRY_T // 60}min) "
          f"across {len(args.series)} series, {args.days} days ===")
    print(f"avg entry price          : {avg_entry * 100:.1f}c")
    print(f"raw win rate of the side : {sum(t['won'] for t in trades) / n:.2%}")
    print(f"clean wins (no stop)     : {len(wins)}  ({len(wins) / n:.2%})")
    print(f"stop-outs                : {len(stops)}  ({len(stops) / n:.2%})"
          f"  of which would-have-won (whipsaw): {len(whipsaw)}")
    print(f"held-to-zero (no stop hit): {len(dead)}")
    print(f"avg P&L per contract     : {total_pnl / n * 100:+.2f}c (after fees)")
    print(f"total P&L per contract-set: ${total_pnl:+.2f} "
          f"(1 contract per trade)")
    ret = total_pnl / (avg_entry * n)
    print(f"return on capital deployed: {ret:+.2%}")

    per: dict[str, list] = {}
    for t in trades:
        per.setdefault(t["series"], []).append(t)
    print("\nper series:")
    for s, ts in sorted(per.items()):
        pnl = sum(t["pnl"] for t in ts)
        wr = sum(t["won"] for t in ts) / len(ts)
        st = sum(t["stopped"] for t in ts)
        print(f"  {s:11s} trades={len(ts):4d} raw-win={wr:.2%} "
              f"stops={st:3d} pnl/contract={pnl / len(ts) * 100:+.2f}c")


if __name__ == "__main__":
    main()
