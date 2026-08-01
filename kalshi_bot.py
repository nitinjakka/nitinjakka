#!/usr/bin/env python3
"""Paper-trading bot for Kalshi 15-min BTC markets.

Spec (Nitin, 2026-07-27):
  - Monitor the BTC 15-minute market (KXBTC15M).
  - With under 2 minutes to expiry, if either side (Up/Down) is priced
    95-98c, buy that side (99c entries lose: they need a 99.07% win
    rate after fees, above the ~98.6% these markets deliver).
  - Invest the entire available balance every trade.
  - Run continuously (default 24 hours).

This bot runs in PAPER mode: it tracks a virtual bankroll and logs
every simulated fill to a CSV. It never sends real orders. (A live
mode would additionally need KALSHI_API_KEY_ID / KALSHI_PRIVATE_KEY_PATH
and the order code in kalshi_trade.py.)

Usage:
  python3 kalshi_bot.py --cash 100 --hours 24 --log kalshi_paper_log.csv
"""

import argparse
import csv
import datetime as dt
import os
import time

import requests

API = "https://api.elections.kalshi.com/trade-api/v2"
SERIES = "KXBTC15M"
ENTRY_WINDOW = 120     # seconds before close to decide
ENTRY_MIN, ENTRY_MAX = 0.95, 0.98
BET_FRACTION = 1.00    # all-in: invest the full balance every trade


def fee(p: float) -> float:
    return 0.07 * p * (1.0 - p)


def get(path: str, params: dict | None = None) -> dict:
    for attempt in range(4):
        try:
            r = requests.get(API + path, params=params, timeout=15)
            r.raise_for_status()
            return r.json()
        except Exception:
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)
    return {}


def next_market() -> dict | None:
    ms = get("/markets", {"series_ticker": SERIES, "status": "open",
                          "limit": 5}).get("markets", [])
    ms = [m for m in ms if close_ts_of(m) > time.time() + 10]
    if not ms:
        return None
    return sorted(ms, key=lambda m: m["close_time"])[0]


def close_ts_of(m: dict) -> int:
    return int(dt.datetime.fromisoformat(
        m["close_time"].replace("Z", "+00:00")).timestamp())


def wait_until(ts: float, deadline: float) -> bool:
    """Sleep until ts (unix). Returns False if deadline passed first."""
    while True:
        now = time.time()
        if now >= ts:
            return True
        if now >= deadline:
            return False
        time.sleep(min(5.0, ts - now))


def settle(ticker: str) -> str:
    """Poll until the market has a result; return 'yes'/'no'."""
    while True:
        m = get(f"/markets/{ticker}").get("market", {})
        if m.get("result"):
            return m["result"]
        time.sleep(10)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cash", type=float, default=100.0)
    ap.add_argument("--hours", type=float, default=24.0)
    ap.add_argument("--log", default="kalshi_paper_log.csv")
    args = ap.parse_args()

    cash = args.cash
    deadline = time.time() + args.hours * 3600
    print(f"[{dt.datetime.now(dt.timezone.utc):%H:%M:%S}] paper bot start: "
          f"${cash:.2f}, running {args.hours}h", flush=True)

    new_log = not os.path.exists(args.log)
    with open(args.log, "a", newline="") as f:
        w = csv.writer(f)
        if new_log:
            w.writerow(["utc_time", "ticker", "side", "entry_price",
                        "contracts", "cost", "result", "won",
                        "pnl", "cash_after"])
        f.flush()

        while time.time() < deadline:
            m = next_market()
            if not m:
                time.sleep(30)
                continue
            cts = close_ts_of(m)
            if not wait_until(cts - ENTRY_WINDOW, deadline):
                break

            # Read prices inside the final minute.
            m = get(f"/markets/{m['ticker']}").get("market", {})
            if not m:
                continue
            try:
                yes_ask = float(m.get("yes_ask_dollars") or 0)
                no_ask = float(m.get("no_ask_dollars") or 0)
            except (TypeError, ValueError):
                continue

            if ENTRY_MIN <= yes_ask <= ENTRY_MAX:
                side, price = "yes", yes_ask
            elif ENTRY_MIN <= no_ask <= ENTRY_MAX:
                side, price = "no", no_ask
            else:
                print(f"[{dt.datetime.now(dt.timezone.utc):%H:%M:%S}] "
                      f"{m['ticker']}: no side in "
                      f"{ENTRY_MIN * 100:.0f}-{ENTRY_MAX * 100:.0f}c "
                      f"(yes {yes_ask:.3f} / no {no_ask:.3f}) - skip",
                      flush=True)
                wait_until(cts + 5, deadline)
                continue

            bet = cash * BET_FRACTION
            contracts = int(bet / (price + fee(price)))
            if contracts < 1:
                print("bankroll too small to trade - stopping", flush=True)
                break
            cost = contracts * (price + fee(price))
            cash -= cost
            print(f"[{dt.datetime.now(dt.timezone.utc):%H:%M:%S}] "
                  f"{m['ticker']}: PAPER BUY {contracts}x {side.upper()} "
                  f"@ {price:.2f} cost ${cost:.2f}", flush=True)

            result = settle(m["ticker"])
            won = (result == side)
            payout = contracts * 1.0 if won else 0.0
            cash += payout
            pnl = payout - cost
            print(f"    -> result={result} {'WIN' if won else 'LOSS'} "
                  f"pnl ${pnl:+.2f} cash ${cash:.2f}", flush=True)
            w.writerow([dt.datetime.now(dt.timezone.utc).isoformat(),
                        m["ticker"], side, f"{price:.4f}", contracts,
                        f"{cost:.2f}", result, won,
                        f"{pnl:.2f}", f"{cash:.2f}"])
            f.flush()

    print(f"[{dt.datetime.now(dt.timezone.utc):%H:%M:%S}] done. "
          f"final cash ${cash:.2f} (started ${args.cash:.2f}, "
          f"{(cash / args.cash - 1):+.1%})", flush=True)


if __name__ == "__main__":
    main()
