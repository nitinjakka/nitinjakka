#!/usr/bin/env python3
"""Paper-trading bot v4 for Kalshi 15-min crypto markets (9 coins).

Coins: BTC, ETH, SOL, ZEC, BNB, XRP, HYPE, DOGE, NEAR.

Strategy per 15-minute window (all coins share the same close grid):
  - At T-3 minutes: for each coin, compute the gap between spot
    (Coinbase) and the market's target. Require |gap| > 0.05%.
  - Buy the leading side only if its ask is 90-98c.
  - MARKET entry: buy immediately at the ask (taker fee applies).
  - After a fill, monitor every 3s; stop-loss sell if our bid hits 70c.
  - Sizing: 1 qualifying coin -> 50% of cash; 2+ coins -> split
    100% of cash evenly across them. At most 4 concurrent positions.
  - High-priority push notifications via ntfy.sh; timestamps in ET.

PAPER mode: market orders fill at the current ask. No real orders.
"""

import argparse
import csv
import datetime as dt
import os
import subprocess
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
MIN_GAP = 0.0005       # BTC baseline: >0.05% (p90 3-min move 0.07%)
GAP_OVERRIDES = {      # per-coin thresholds ~= p90 of 3-min moves
    "KXETH15M": 0.0010,   # 0.10%
    "KXSOL15M": 0.0010,   # 0.10%
    "KXBNB15M": 0.0010,   # 0.10%
    "KXXRP15M": 0.0010,   # 0.10%
    "KXDOGE15M": 0.0010,  # 0.10%
    "KXHYPE15M": 0.0020,  # 0.20%
    "KXNEAR15M": 0.0025,  # 0.25%
    "KXZEC15M": 0.0025,   # 0.25%
}
ENTRY_MIN, ENTRY_MAX = 0.90, 0.985
STOP_TRIGGER = 0.70
# Sizing is dynamic: 1 coin -> 50% of cash; N>1 coins -> 100%/N each.
MAX_CONCURRENT = 4

NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "nitin-kalshi-bot-x7q2")
HEARTBEAT_TOPIC = os.environ.get("NTFY_HEARTBEAT_TOPIC",
                                 "nitin-kalshi-heartbeat-x7q2")
HEARTBEAT_SECS = 300   # emit a liveness ping every 5 minutes

LIVE = False              # set by --live; when False everything is simulated
live = None               # kalshi_live module, imported only in live mode

lock = threading.Lock()   # guards cash + csv writer
state = {"cash": 0.0}
CASH_FILE = "kalshi_cash.txt"


def save_cash() -> None:
    """Persist current cash so the watchdog can resume correctly.
    Call with lock held."""
    try:
        with open(CASH_FILE, "w") as cf:
            cf.write(f"{state['cash']:.2f}")
    except Exception:
        pass


def fee(p: float) -> float:
    """Taker fee. Maker fills pay no fee (verified from app quotes)."""
    return 0.07 * p * (1.0 - p)


def notify(title: str, body: str, priority: str = "high") -> None:
    try:
        requests.post(f"https://ntfy.sh/{NTFY_TOPIC}", data=body.encode(),
                      headers={"Title": title, "Priority": priority},
                      timeout=10)
    except Exception:
        pass


def heartbeat_loop(mode: str) -> None:
    """Emit a low-priority liveness ping so an external monitor can tell
    the bot is still running. Runs as a daemon thread."""
    while True:
        try:
            with lock:
                cash = state["cash"]
            requests.post(
                f"https://ntfy.sh/{HEARTBEAT_TOPIC}",
                data=f"alive {mode} cash=${cash:.2f} "
                     f"{dt.datetime.now(ET):%I:%M:%S %p ET}".encode(),
                headers={"Title": "kalshi-heartbeat", "Priority": "min",
                         "Tags": "heartbeat"},
                timeout=10)
        except Exception:
            pass
        time.sleep(HEARTBEAT_SECS)


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


def repo_commit() -> str:
    """Current git commit of the repo, or '' if unavailable."""
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            stderr=subprocess.DEVNULL).decode().strip()
    except Exception:
        return ""


def trade_lifecycle(series: str, m: dict, side: str, price: float,
                    contracts: int, gap: float, cts: int,
                    writer, wfile) -> None:
    """Runs in its own thread: stop monitor -> settle.

    Market order: filled immediately at the ask (taker, fee paid);
    cash was already deducted by the caller.
    """
    ticker = m["ticker"]
    coin = coin_name(series)
    cost = contracts * (price + fee(price))

    stopped, exit_px = False, 0.0
    manual = False          # user closed the position from the Kalshi app
    poll = 0
    while time.time() < cts:
        # In live mode, notice if the position was sold manually and
        # stop managing it (don't place a duplicate stop-sell).
        if LIVE and poll % 5 == 0:
            try:
                if live.held_contracts(ticker, side) < contracts:
                    manual = True
                    break
            except Exception:
                pass
        poll += 1
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

    if manual:
        with lock:
            try:
                state["cash"] = live.balance_dollars()
            except Exception:
                pass
            cash_now = state["cash"]
            save_cash()
        result, won, pnl = "manual", False, float("nan")
        log_line(f"{coin}: position closed manually - bot backing off "
                 f"(cash ${cash_now:.2f}) {ticker}")
        notify(f"Kalshi bot: {coin} CLOSED MANUALLY",
               f"You sold it from the app; bot won't re-sell. "
               f"Cash ${cash_now:.2f}")
    elif stopped:
        if LIVE:
            # Sell only what is still held (user may have sold some),
            # a few cents below the trigger to guarantee the fill.
            try:
                held = live.held_contracts(ticker, side)
                if held > 0:
                    live.sell(ticker, side, held,
                              max(1, int(round(exit_px * 100)) - 3))
            except Exception as e:
                log_line(f"{coin}: LIVE stop-sell FAILED: {e}")
                notify(f"Kalshi bot: {coin} STOP-SELL FAILED", str(e))
            with lock:
                try:
                    state["cash"] = live.balance_dollars()
                except Exception:
                    pass
                cash_now = state["cash"]
                save_cash()
            pnl = float("nan")
        else:
            proceeds = contracts * (exit_px - fee(exit_px))
            with lock:
                state["cash"] += proceeds
                cash_now = state["cash"]
                save_cash()
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
        if LIVE:
            time.sleep(5)  # let Kalshi credit the settlement
            with lock:
                try:
                    state["cash"] = live.balance_dollars()
                except Exception:
                    pass
                cash_now = state["cash"]
                save_cash()
            pnl = float("nan")
        else:
            payout = contracts * 1.0 if won else 0.0
            with lock:
                state["cash"] += payout
                cash_now = state["cash"]
                save_cash()
            pnl = payout - cost
        log_line(f"{coin}: result={result} {'WIN' if won else 'LOSS'} "
                 f"pnl ${pnl:+.2f} cash ${cash_now:.2f}")
        notify(f"Kalshi bot: {coin} {'WIN' if won else 'LOSS'}",
               f"pnl ${pnl:+.2f}, cash ${cash_now:.2f}")

    with lock:
        writer.writerow(
            [dt.datetime.now(ET).strftime("%Y-%m-%d %I:%M:%S %p ET"),
             ticker, side, f"{price:.4f}", contracts, f"{cost:.2f}",
             result, won, f"{pnl:.2f}", f"{cash_now:.2f}"])
        wfile.flush()


def main() -> None:
    global LIVE, live
    ap = argparse.ArgumentParser()
    ap.add_argument("--cash", type=float, default=10.0)
    ap.add_argument("--hours", type=float, default=24.0)
    ap.add_argument("--log", default="kalshi_paper_log.csv")
    ap.add_argument("--live", action="store_true",
                    help="place REAL orders (needs Kalshi API key env vars "
                         "and KALSHI_LIVE_CONFIRM=YES)")
    args = ap.parse_args()

    if args.live:
        import kalshi_live as _live
        live = _live
        try:
            summary = live.preflight()
        except Exception as e:
            log_line(f"LIVE preflight FAILED - staying down: {e}")
            notify("Kalshi bot: LIVE START FAILED", str(e))
            return
        LIVE = True
        state["cash"] = live.balance_dollars()
        log_line(f"*** LIVE MODE *** {summary}")
        notify("Kalshi bot: LIVE MODE ON",
               f"Real trading. Starting balance ${state['cash']:.2f}")
    else:
        state["cash"] = args.cash
    save_cash()
    deadline = time.time() + args.hours * 3600
    mode = "LIVE" if LIVE else "paper"
    log_line(f"{mode} bot v4 start: ${state['cash']:.2f}, {args.hours}h, "
             f"{len(COINS)} coins ({', '.join(coin_name(s) for s in COINS)}); "
             f"T-3 market orders, per-coin gaps (BTC 0.05% / mid 0.10% / "
             f"HYPE 0.20% / NEAR+ZEC 0.25%), "
             f"{ENTRY_MIN*100:.0f}c-{ENTRY_MAX*100:.1f}c, "
             f"stop {STOP_TRIGGER:.0%}, size 1coin=50%/2+=split100%, "
             f"max {MAX_CONCURRENT} at once")

    new_log = not os.path.exists(args.log)
    f = open(args.log, "a", newline="")
    writer = csv.writer(f)
    if new_log:
        writer.writerow(["et_time", "ticker", "side", "entry_price",
                        "contracts", "cost", "result", "won",
                        "pnl", "cash_after"])
        f.flush()

    threading.Thread(target=heartbeat_loop, args=(mode,),
                     daemon=True).start()

    boot_commit = repo_commit()
    threads: list[threading.Thread] = []
    while time.time() < deadline:
        # Auto-update: if new code was deployed, exit at this safe point
        # (between windows, no order being placed) so the watchdog
        # restarts us on the new code. Non-daemon trade threads still
        # finish first, so open positions are never abandoned.
        cur = repo_commit()
        if boot_commit and cur and cur != boot_commit:
            log_line(f"new code deployed ({cur[:7]}) - restarting to update")
            notify("Kalshi bot: UPDATING", "New code deployed; restarting.")
            return
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
            min_gap = GAP_OVERRIDES.get(series, MIN_GAP)
            if abs(gap) <= min_gap:
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
        candidates = candidates[:MAX_CONCURRENT]
        # Sizing: 1 coin -> 50% of cash; 2+ coins -> split 100% evenly.
        n_found = len(candidates)
        frac = 0.50 if n_found == 1 else (1.0 / n_found if n_found else 0)
        if LIVE:
            try:
                with lock:
                    state["cash"] = live.balance_dollars()  # source of truth
                    save_cash()
            except Exception as e:
                log_line(f"live balance check failed, skipping window: {e}")
                candidates = []
        with lock:
            window_cash = state["cash"]   # fix the base before deductions
        placed = 0
        for _, gap, series, m, side, ask in candidates:
            unit = ask + fee(ask)  # taker: pay the ask plus fee
            with lock:
                contracts = int(window_cash * frac / unit)
                if contracts < 1:
                    continue
            coin = coin_name(series)

            if LIVE:
                try:
                    live.buy(m["ticker"], side, contracts,
                             int(round(ask * 100)))
                except Exception as e:
                    log_line(f"{coin}: LIVE order REJECTED: {e}")
                    notify(f"Kalshi bot: {coin} ORDER FAILED", str(e))
                    continue
            else:
                with lock:
                    state["cash"] -= contracts * unit
                    save_cash()

            log_line(f"{coin}: {'LIVE' if LIVE else 'PAPER'} BUY "
                     f"{contracts}x {side.upper()} @ {ask:.2f} "
                     f"(gap {gap:+.3%}) cost ${contracts * unit:.2f} "
                     f"{m['ticker']}")
            notify(f"Kalshi bot: {coin} BUY",
                   f"{contracts}x {side.upper()} @ {ask:.2f} "
                   f"(${contracts * unit:.2f}, gap {gap:+.3%}) "
                   f"{m['ticker']}")
            t = threading.Thread(
                target=trade_lifecycle,
                args=(series, m, side, ask, contracts, gap, cts,
                      writer, f),
                daemon=False)
            t.start()
            threads.append(t)
            placed += 1

        if not candidates:
            wtime = f"{dt.datetime.fromtimestamp(cts, ET):%I:%M %p ET}"
            log_line(f"nothing to trade this window ({wtime} close)")
            notify("Kalshi bot: nothing to trade",
                   f"No qualifying coin for the {wtime} window.",
                   priority="low")
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
