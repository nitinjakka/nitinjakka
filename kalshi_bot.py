#!/usr/bin/env python3
"""Paper-trading bot v3 for Kalshi 15-min BTC markets.

Strategy (evidence-based, within Nitin's last-3-minutes constraint):
  - At T-3 minutes: compute the gap between BTC spot (Coinbase) and the
    market's target price. Require |gap| > 0.05%.
  - Buy the leading side only if its ask is 90-98c.
  - MAKER entry: rest a limit 1c below the ask (zero fee). If not
    filled by T-1 min, cancel - no trade.
  - After a fill, monitor every 3s; stop-loss sell if our bid hits 70c.
  - Size each trade at 25% of current cash.
  - Push notifications via ntfy.sh on order, fill, result.

PAPER mode: fills are simulated (a resting bid is considered filled
if the ask later drops to our limit). No real orders.

Usage:
  python3 kalshi_bot.py --cash 10 --hours 24 --log kalshi_paper_log.csv
"""

import argparse
import csv
import datetime as dt
import os
import time
from zoneinfo import ZoneInfo

import requests

ET = ZoneInfo("America/New_York")

API = "https://api.elections.kalshi.com/trade-api/v2"
CB_TICKER = "https://api.exchange.coinbase.com/products/BTC-USD/ticker"
SERIES = "KXBTC15M"

ENTRY_WINDOW = 180     # decide 3 minutes before close
CANCEL_AT = 60         # cancel unfilled maker order 1 min before close
MIN_GAP = 0.0005       # require spot >0.05% away from target
ENTRY_MIN, ENTRY_MAX = 0.90, 0.98
MAKER_IMPROVE = 0.01   # rest 1c below the ask
STOP_TRIGGER = 0.70
BET_FRACTION = 0.25

NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "nitin-kalshi-bot-x7q2")


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
                raise
            time.sleep(2 ** attempt)
    return {}


def btc_spot() -> float | None:
    try:
        r = requests.get(CB_TICKER, timeout=10)
        r.raise_for_status()
        return float(r.json()["price"])
    except Exception:
        return None


def close_ts_of(m: dict) -> int:
    return int(dt.datetime.fromisoformat(
        m["close_time"].replace("Z", "+00:00")).timestamp())


def next_market() -> dict | None:
    ms = get("/markets", {"series_ticker": SERIES, "status": "open",
                          "limit": 5}).get("markets", [])
    ms = [m for m in ms if close_ts_of(m) > time.time() + 10]
    if not ms:
        return None
    return sorted(ms, key=lambda m: m["close_time"])[0]


def wait_until(ts: float, deadline: float) -> bool:
    while True:
        now = time.time()
        if now >= ts:
            return True
        if now >= deadline:
            return False
        time.sleep(min(5.0, ts - now))


def settle(ticker: str) -> str:
    while True:
        m = get(f"/markets/{ticker}").get("market", {})
        if m.get("result"):
            return m["result"]
        time.sleep(10)


def log_line(msg: str) -> None:
    print(f"[{dt.datetime.now(ET):%I:%M:%S %p ET}] {msg}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cash", type=float, default=10.0)
    ap.add_argument("--hours", type=float, default=24.0)
    ap.add_argument("--log", default="kalshi_paper_log.csv")
    args = ap.parse_args()

    cash = args.cash
    deadline = time.time() + args.hours * 3600
    log_line(f"paper bot v3 start: ${cash:.2f}, running {args.hours}h "
             f"(T-3 maker entry, gap>{MIN_GAP:.2%}, "
             f"{ENTRY_MIN:.0%}-{ENTRY_MAX:.0%}, stop {STOP_TRIGGER:.0%}, "
             f"{BET_FRACTION:.0%} of cash per trade)")

    new_log = not os.path.exists(args.log)
    with open(args.log, "a", newline="") as f:
        w = csv.writer(f)
        if new_log:
            w.writerow(["et_time", "ticker", "side", "entry_price",
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

            m = get(f"/markets/{m['ticker']}").get("market", {})
            if not m:
                continue
            ticker = m["ticker"]
            strike = float(m.get("floor_strike") or 0)
            spot = btc_spot()
            if not strike or not spot:
                log_line(f"{ticker}: missing strike/spot - skip")
                wait_until(cts + 5, deadline)
                continue

            gap = (spot - strike) / strike
            if abs(gap) <= MIN_GAP:
                log_line(f"{ticker}: gap {gap:+.3%} too small - skip")
                wait_until(cts + 5, deadline)
                continue
            side = "yes" if gap > 0 else "no"

            try:
                ask = float(m["yes_ask_dollars"] if side == "yes"
                            else m["no_ask_dollars"])
            except (KeyError, TypeError, ValueError):
                wait_until(cts + 5, deadline)
                continue
            if not ENTRY_MIN <= ask <= ENTRY_MAX:
                log_line(f"{ticker}: gap {gap:+.3%} but {side} ask "
                         f"{ask:.2f} outside {ENTRY_MIN:.2f}-{ENTRY_MAX:.2f}"
                         f" - skip")
                wait_until(cts + 5, deadline)
                continue

            limit = round(ask - MAKER_IMPROVE, 2)
            contracts = int(cash * BET_FRACTION / limit)
            if contracts < 1:
                log_line("bankroll too small - stopping")
                break
            log_line(f"{ticker}: MAKER order {contracts}x {side.upper()} "
                     f"@ {limit:.2f} (ask {ask:.2f}, gap {gap:+.3%})")
            notify("Kalshi bot: ORDER PLACED",
                   f"{contracts}x {side.upper()} resting @ {limit:.2f} "
                   f"(ask {ask:.2f}, gap {gap:+.3%}) {ticker}")

            # Wait for a simulated maker fill: ask drops to our limit.
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
                log_line(f"{ticker}: not filled by T-{CANCEL_AT}s - "
                         f"canceled")
                notify("Kalshi bot: NOT FILLED",
                       f"Canceled resting order {ticker}")
                wait_until(cts + 5, deadline)
                continue

            cost = contracts * limit  # maker: no fee
            cash -= cost
            log_line(f"{ticker}: FILLED {contracts}x {side.upper()} "
                     f"@ {limit:.2f} cost ${cost:.2f}")
            notify("Kalshi bot: FILLED (BUY)",
                   f"{contracts}x {side.upper()} @ {limit:.2f} "
                   f"(${cost:.2f}) {ticker}")

            # Monitor for the 70c stop until close.
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
                cash += proceeds
                pnl = proceeds - cost
                result, won = "stopped", False
                log_line(f"  STOP-LOSS sell @ {exit_px:.2f} "
                         f"pnl ${pnl:+.2f} cash ${cash:.2f}")
                notify("Kalshi bot: STOP-LOSS",
                       f"Sold @ {exit_px:.2f}, pnl ${pnl:+.2f}, "
                       f"cash ${cash:.2f}")
            else:
                result = settle(ticker)
                won = (result == side)
                payout = contracts * 1.0 if won else 0.0
                cash += payout
                pnl = payout - cost
                log_line(f"  result={result} {'WIN' if won else 'LOSS'} "
                         f"pnl ${pnl:+.2f} cash ${cash:.2f}")
                notify(f"Kalshi bot: {'WIN' if won else 'LOSS'}",
                       f"pnl ${pnl:+.2f}, cash ${cash:.2f}")
            w.writerow([dt.datetime.now(ET).strftime("%Y-%m-%d %I:%M:%S %p ET"),
                        ticker, side, f"{limit:.4f}", contracts,
                        f"{cost:.2f}", result, won,
                        f"{pnl:.2f}", f"{cash:.2f}"])
            f.flush()

    log_line(f"done. final cash ${cash:.2f} (started ${args.cash:.2f}, "
             f"{(cash / args.cash - 1):+.1%})")
    notify("Kalshi bot: run finished",
           f"Final cash ${cash:.2f} (started ${args.cash:.2f}, "
           f"{(cash / args.cash - 1):+.1%})")


if __name__ == "__main__":
    main()
