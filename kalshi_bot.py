#!/usr/bin/env python3
"""Paper-trading bot v4 for Kalshi 15-min crypto markets (9 coins).

Coins: BTC, ETH, SOL, ZEC, BNB, XRP, HYPE, DOGE, NEAR.

Strategy per 15-minute window (all coins share the same close grid):
  - At T-3 minutes: for each coin, compute the gap between spot
    (Coinbase) and the market's target. Require |gap| > 0.05%.
  - Buy the leading side only if its ask is 90-98c.
  - MAKER entry: rest a limit 1c below the ask (zero fee). Cancel if
    not filled by T-1 min.
  - After a fill, monitor every 3s; stop-loss sell if our bid hits 70c.
  - Size each order at 25% of cash; at most 4 concurrent positions.
  - High-priority push notifications via ntfy.sh; timestamps in ET.

PAPER mode: fills are simulated (resting bid fills if the ask later
drops to the limit). No real orders.
"""

import argparse
import csv
import datetime as dt
import os
import threading
import time
from zoneinfo import ZoneInfo

import requests

API = "https://api.elections.kalshi.com/trade-api/v2"
CB = "https://api.exchange.coinbase.com"
ET = ZoneInfo("America/New_York")

COINS = {
    "KXBTC15M": "BTC-USD",
    "KXETH15M": "ETH-USD",
    "KXSOL15M": "SOL-USD",
    "KXZEC15M": "ZEC-USD",
    "KXBNB15M": "BNB-USD",
    "KXXRP15M": "XRP-USD",
    "KXHYPE15M": "HYPE-USD",
    "KXDOGE15M": "DOGE-USD",
    "KXNEAR15M": "NEAR-USD",
}

ENTRY_WINDOW = 180     # decide 3 minutes before close
CANCEL_AT = 60         # cancel unfilled maker order 1 min before close
MIN_GAP = 0.0005       # require spot >0.05% away from target
ENTRY_MIN, ENTRY_MAX = 0.90, 0.98
MAKER_IMPROVE = 0.01   # rest 1c below the ask
STOP_TRIGGER = 0.70
BET_FRACTION = 0.25
MAX_CONCURRENT = 4

NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "nitin-kalshi-bot-x7q2")

lock = threading.Lock()   # guards cash + csv writer
state = {"cash": 0.0}


def fee(p: float) -> float:
    """Taker fee. Maker fills pay no fee (verified from app quotes)."""
    return 0.07 * p * (1.0 - p)


def notify(title: str, body: str) -> None:
    try:
        requests.post(f"https://ntfy.sh/{NTFY_TOPIC}", data=body.encode(),
                      headers={"Title": title, "Priority": "high"},
                      timeout=10)
    except Exception:
        pass


def get(path: str, params: dict | None = None) -> dict:
    for attempt in range(4):
        try:
            r = requests.get(API + path, params=params, timeout=15)
            r.raise_for_status()
            return r.json()
        except Exception:
            if attempt == 3:
                return {}
            time.sleep(2 ** attempt)
    return {}


def spot(product: str) -> float | None:
    try:
        r = requests.get(f"{CB}/products/{product}/ticker", timeout=10)
        r.raise_for_status()
        return float(r.json()["price"])
    except Exception:
        return None


def close_ts_of(m: dict) -> int:
    return int(dt.datetime.fromisoformat(
        m["close_time"].replace("Z", "+00:00")).timestamp())


def open_markets(series: str) -> list[dict]:
    ms = get("/markets", {"series_ticker": series, "status": "open",
                          "limit": 5}).get("markets", [])
    return [m for m in ms if close_ts_of(m) > time.time() + 10]


def log_line(msg: str) -> None:
    print(f"[{dt.datetime.now(ET):%I:%M:%S %p ET}] {msg}", flush=True)


def settle(ticker: str) -> str:
    while True:
        m = get(f"/markets/{ticker}").get("market", {})
        if m.get("result"):
            return m["result"]
        time.sleep(10)


def coin_name(series: str) -> str:
    return COINS[series].split("-")[0]


def trade_lifecycle(series: str, m: dict, side: str, limit: float,
                    contracts: int, gap: float, cts: int,
                    writer, wfile) -> None:
    """Runs in its own thread: fill-wait -> stop monitor -> settle."""
    ticker = m["ticker"]
    coin = coin_name(series)
    reserve = contracts * limit
    filled = False
    while time.time() < cts - CANCEL_AT:
        mm = get(f"/markets/{ticker}").get("market", {})
        try:
            cur_ask = float(mm["yes_ask_dollars"] if side == "yes"
                            else mm["no_ask_dollars"])
        except (KeyError, TypeError, ValueError):
            time.sleep(3)
            continue
        if cur_ask <= limit:
            filled = True
            break
        time.sleep(3)

    if not filled:
        with lock:
            state["cash"] += reserve  # refund reservation
        log_line(f"{coin}: not filled by T-{CANCEL_AT}s - canceled "
                 f"({ticker})")
        notify(f"Kalshi bot: {coin} NOT FILLED",
               f"Canceled resting order {ticker}")
        return

    cost = reserve  # maker: no fee
    log_line(f"{coin}: FILLED {contracts}x {side.upper()} @ {limit:.2f} "
             f"cost ${cost:.2f} ({ticker})")
    notify(f"Kalshi bot: {coin} FILLED (BUY)",
           f"{contracts}x {side.upper()} @ {limit:.2f} (${cost:.2f}) "
           f"{ticker}")

    stopped, exit_px = False, 0.0
    while time.time() < cts:
        mm = get(f"/markets/{ticker}").get("market", {})
        try:
            yb = float(mm.get("yes_bid_dollars") or 0)
            ya = float(mm.get("yes_ask_dollars") or 1)
        except (TypeError, ValueError):
            time.sleep(3)
            continue
        bid = yb if side == "yes" else round(1.0 - ya, 4)
        if 0 < bid <= STOP_TRIGGER:
            exit_px = bid
            stopped = True
            break
        time.sleep(3)

    if stopped:
        proceeds = contracts * (exit_px - fee(exit_px))
        with lock:
            state["cash"] += proceeds
            cash_now = state["cash"]
        pnl = proceeds - cost
        result, won = "stopped", False
        log_line(f"{coin}: STOP-LOSS sell @ {exit_px:.2f} "
                 f"pnl ${pnl:+.2f} cash ${cash_now:.2f}")
        notify(f"Kalshi bot: {coin} STOP-LOSS",
               f"Sold @ {exit_px:.2f}, pnl ${pnl:+.2f}, "
               f"cash ${cash_now:.2f}")
    else:
        result = settle(ticker)
        won = (result == side)
        payout = contracts * 1.0 if won else 0.0
        with lock:
            state["cash"] += payout
            cash_now = state["cash"]
        pnl = payout - cost
        log_line(f"{coin}: result={result} {'WIN' if won else 'LOSS'} "
                 f"pnl ${pnl:+.2f} cash ${cash_now:.2f}")
        notify(f"Kalshi bot: {coin} {'WIN' if won else 'LOSS'}",
               f"pnl ${pnl:+.2f}, cash ${cash_now:.2f}")

    with lock:
        writer.writerow(
            [dt.datetime.now(ET).strftime("%Y-%m-%d %I:%M:%S %p ET"),
             ticker, side, f"{limit:.4f}", contracts, f"{cost:.2f}",
             result, won, f"{pnl:.2f}", f"{cash_now:.2f}"])
        wfile.flush()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cash", type=float, default=10.0)
    ap.add_argument("--hours", type=float, default=24.0)
    ap.add_argument("--log", default="kalshi_paper_log.csv")
    args = ap.parse_args()

    state["cash"] = args.cash
    deadline = time.time() + args.hours * 3600
    log_line(f"paper bot v4 start: ${args.cash:.2f}, {args.hours}h, "
             f"{len(COINS)} coins ({', '.join(coin_name(s) for s in COINS)}); "
             f"T-3 maker, gap>{MIN_GAP:.2%}, {ENTRY_MIN:.0%}-{ENTRY_MAX:.0%}, "
             f"stop {STOP_TRIGGER:.0%}, {BET_FRACTION:.0%}/trade, "
             f"max {MAX_CONCURRENT} at once")

    new_log = not os.path.exists(args.log)
    f = open(args.log, "a", newline="")
    writer = csv.writer(f)
    if new_log:
        writer.writerow(["et_time", "ticker", "side", "entry_price",
                        "contracts", "cost", "result", "won",
                        "pnl", "cash_after"])
        f.flush()

    threads: list[threading.Thread] = []
    while time.time() < deadline:
        anchor = open_markets("KXBTC15M")
        if not anchor:
            time.sleep(30)
            continue
        cts = min(close_ts_of(m) for m in anchor)
        while time.time() < cts - ENTRY_WINDOW:
            if time.time() >= deadline:
                break
            time.sleep(min(5.0, cts - ENTRY_WINDOW - time.time()))
        if time.time() >= deadline:
            break

        # Decision pass across all coins for this window.
        candidates = []
        for series, product in COINS.items():
            ms = [m for m in open_markets(series)
                  if close_ts_of(m) == cts]
            if not ms:
                continue
            m = get(f"/markets/{ms[0]['ticker']}").get("market", {})
            if not m:
                continue
            strike = float(m.get("floor_strike") or 0)
            px = spot(product)
            if not strike or not px:
                continue
            gap = (px - strike) / strike
            if abs(gap) <= MIN_GAP:
                log_line(f"{coin_name(series)}: gap {gap:+.3%} too small"
                         f" - skip")
                continue
            side = "yes" if gap > 0 else "no"
            try:
                ask = float(m["yes_ask_dollars"] if side == "yes"
                            else m["no_ask_dollars"])
            except (KeyError, TypeError, ValueError):
                continue
            if not ENTRY_MIN <= ask <= ENTRY_MAX:
                log_line(f"{coin_name(series)}: gap {gap:+.3%} but "
                         f"{side} ask {ask:.2f} out of range - skip")
                continue
            candidates.append((abs(gap), gap, series, m, side, ask))

        candidates.sort(reverse=True, key=lambda c: c[0])
        placed = 0
        for _, gap, series, m, side, ask in candidates:
            if placed >= MAX_CONCURRENT:
                break
            limit = round(ask - MAKER_IMPROVE, 2)
            with lock:
                contracts = int(state["cash"] * BET_FRACTION / limit)
                if contracts < 1:
                    continue
                state["cash"] -= contracts * limit  # reserve
            coin = coin_name(series)
            log_line(f"{coin}: MAKER order {contracts}x {side.upper()} "
                     f"@ {limit:.2f} (ask {ask:.2f}, gap {gap:+.3%}) "
                     f"{m['ticker']}")
            notify(f"Kalshi bot: {coin} ORDER PLACED",
                   f"{contracts}x {side.upper()} resting @ {limit:.2f} "
                   f"(ask {ask:.2f}, gap {gap:+.3%}) {m['ticker']}")
            t = threading.Thread(
                target=trade_lifecycle,
                args=(series, m, side, limit, contracts, gap, cts,
                      writer, f),
                daemon=False)
            t.start()
            threads.append(t)
            placed += 1

        if not candidates:
            log_line("no qualifying coins this window")
        # Move past this window before scanning for the next one.
        while time.time() < cts + 5:
            time.sleep(3)
        threads = [t for t in threads if t.is_alive()]

    for t in threads:
        t.join(timeout=1200)
    with lock:
        cash = state["cash"]
    log_line(f"done. final cash ${cash:.2f} (started ${args.cash:.2f}, "
             f"{(cash / args.cash - 1):+.1%})")
    notify("Kalshi bot: run finished",
           f"Final cash ${cash:.2f} (started ${args.cash:.2f}, "
           f"{(cash / args.cash - 1):+.1%})")
    f.close()


if __name__ == "__main__":
    main()
