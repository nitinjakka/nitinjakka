#!/usr/bin/env python3
"""Paper-trading bot v4 for Kalshi 15-min crypto markets (9 coins).

Coins: BTC, ETH, BNB, NEAR, ZEC, HYPE.

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
import math
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
    "KXBNB15M": "BNB-USD",
    "KXNEAR15M": "NEAR-USD",
    "KXZEC15M": "ZEC-USD",
    "KXHYPE15M": "HYPE-USD",
}

ENTRY_WINDOW = 180     # standard decision point (3 minutes before close)
# Entry schedule: (seconds-before-close, coins-allowed-at-that-check).
# Every listed check runs each window; a coin qualifying late still gets
# traded, and a coin already traded this window is never re-entered.
#
# Coins are tiered by volatility / stop-loss history:
#   BTC (EARLY)  - deepest, least volatile. Extra t-5 look (backtest:
#                  99.0% settle-on-gap at 0.10%), plus t-3/2:30/2.
#   BNB (MID)    - traded t-3/2:30/2. (SOL and XRP were removed.)
#   ETH/NEAR/ZEC/HYPE (LATE) - the riskiest coins (ETH is a big stop-loss
#                  offender; NEAR/ZEC/HYPE are thin/volatile). Restricted
#                  to t-1 ONLY - the latest, most-certain check, where
#                  there is minimal time left to reverse, so win rate is
#                  highest and stops least likely. Deliberately OFF the
#                  earlier t-5/t-3/2:30/2 checks. (DOGE was removed
#                  entirely - it caused the most stops and the two worst
#                  losses on the account.)
EARLY_COINS = ("KXBTC15M",)
LATE_COINS = ("KXETH15M", "KXNEAR15M", "KXZEC15M", "KXHYPE15M")
MID_COINS = tuple(c for c in COINS if c not in LATE_COINS)  # BTC, BNB
ENTRY_SCHEDULE = (
    (300, EARLY_COINS),           # t-5: BTC only
    (180, MID_COINS),             # t-3: BTC, BNB
    (150, MID_COINS),             # t-2:30
    (120, MID_COINS),             # t-2
    (60,  LATE_COINS),            # t-1: ETH, NEAR, ZEC, HYPE
)
MIN_GAP = 0.0010       # 0.10% default gap threshold (BTC, ETH, BNB)
# Per-coin gap thresholds. Thin/volatile t-1 coins (NEAR/ZEC/HYPE) need a
# stronger 0.15% signal so low-liquidity noise doesn't trigger a trade.
GAP_OVERRIDES = {
    "KXNEAR15M": 0.0015,
    "KXZEC15M": 0.0015,
    "KXHYPE15M": 0.0015,
}
ENTRY_MIN, ENTRY_MAX = 0.90, 0.985
STOP_TRIGGER = 0.50
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


_last_low_notify = [0.0]   # throttle timestamp for low-priority pings


def notify(title: str, body: str, priority: str = "high") -> None:
    # Throttle low-priority pings (nothing-to-trade / too-small) to at
    # most one per hour. Their volume was getting the server IP rate-
    # limited by ntfy, which silently dropped important trade alerts.
    if priority == "low":
        if time.time() - _last_low_notify[0] < 3600:
            return
        _last_low_notify[0] = time.time()
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

    # Monitor the held side's bid; trigger the stop purely on price.
    # (No position-lookup gating - the reduce_only exit safely no-ops
    # if the position was already closed or sold manually.)
    stopped, exit_px = False, 0.0
    while time.time() < cts:
        mm = get(f"/markets/{ticker}").get("market", {})
        try:
            yb = float(mm.get("yes_bid_dollars") or 0)
            ya = float(mm.get("yes_ask_dollars") or 1)
        except (TypeError, ValueError):
            time.sleep(2)
            continue
        bid = yb if side == "yes" else round(1.0 - ya, 4)
        if 0 < bid <= STOP_TRIGGER:
            exit_px = bid
            stopped = True
            break
        time.sleep(2)

    if stopped:
        # Estimated P&L from known quantities (entry cost + exit proceeds).
        # In live mode cash_now is still read from the real balance below;
        # this pnl is a close estimate for the per-trade log/notification.
        proceeds = contracts * (exit_px - fee(exit_px))
        pnl = proceeds - cost
        if LIVE:
            # Market-exit the whole position. reduce_only means it can
            # only close (never flip), so we sell the original count
            # without depending on a position lookup (which was
            # returning 0 and silently skipping the sell).
            try:
                live.exit_pos(ticker, side, contracts)
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
        else:
            with lock:
                state["cash"] += proceeds
                cash_now = state["cash"]
                save_cash()
        result, won = "stopped", False
        pct_txt = f" ({pnl / cost * 100:+.1f}%)" if (cost and pnl == pnl) else ""
        log_line(f"{coin}: STOP-LOSS sell @ {exit_px:.2f} "
                 f"pnl ${pnl:+.2f}{pct_txt} cash ${cash_now:.2f}")
        notify(f"Kalshi bot: {coin} STOP-LOSS",
               f"Sold @ {exit_px:.2f}, pnl ${pnl:+.2f}{pct_txt}, "
               f"cash ${cash_now:.2f}")
    else:
        result = settle(ticker)
        won = (result == side)
        # Winning contracts pay $1 each; losers pay 0. Entry cost already
        # includes the taker fee and settlement has no exit fee, so this
        # is exact in paper and a close estimate in live (cash_now is
        # still the authoritative real balance below).
        payout = contracts * 1.0 if won else 0.0
        pnl = payout - cost
        if LIVE:
            time.sleep(5)  # let Kalshi credit the settlement
            with lock:
                try:
                    state["cash"] = live.balance_dollars()
                except Exception:
                    pass
                cash_now = state["cash"]
                save_cash()
        else:
            with lock:
                state["cash"] += payout
                cash_now = state["cash"]
                save_cash()
        pct_txt = f" ({pnl / cost * 100:+.1f}%)" if (cost and pnl == pnl) else ""
        log_line(f"{coin}: result={result} {'WIN' if won else 'LOSS'} "
                 f"pnl ${pnl:+.2f}{pct_txt} cash ${cash_now:.2f}")
        notify(f"Kalshi bot: {coin} {'WIN' if won else 'LOSS'}",
               f"pnl ${pnl:+.2f}{pct_txt}, cash ${cash_now:.2f}")

    pct = pnl / cost * 100.0 if (cost and pnl == pnl) else float("nan")
    with lock:
        writer.writerow(
            [dt.datetime.now(ET).strftime("%Y-%m-%d %I:%M:%S %p ET"),
             ticker, side, f"{price:.4f}", contracts, f"{cost:.2f}",
             result, won, f"{pnl:.2f}", f"{pct:.1f}", f"{cash_now:.2f}"])
        wfile.flush()


def main() -> None:
    global LIVE, live
    ap = argparse.ArgumentParser()
    ap.add_argument("--cash", type=float, default=10.0)
    ap.add_argument("--hours", type=float, default=0.0,
                    help="run duration in hours; 0 or less = run forever "
                         "until the process is killed")
    ap.add_argument("--log", default="kalshi_paper_log.csv")
    ap.add_argument("--cash-file", default="kalshi_cash.txt",
                    help="where to persist balance (use a distinct file "
                         "per instance so paper and live don't collide)")
    ap.add_argument("--live", action="store_true",
                    help="place REAL orders (needs Kalshi API key env vars "
                         "and KALSHI_LIVE_CONFIRM=YES)")
    args = ap.parse_args()

    global CASH_FILE
    CASH_FILE = args.cash_file

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
        # Paper mode: resume from the persisted balance across restarts /
        # auto-deploys so cumulative P&L survives; fall back to --cash on
        # a fresh start.
        state["cash"] = args.cash
        if os.path.exists(CASH_FILE):
            try:
                with open(CASH_FILE) as cf:
                    state["cash"] = float(cf.read().strip())
            except Exception:
                pass
    save_cash()
    deadline = float("inf") if args.hours <= 0 else time.time() + args.hours * 3600
    mode = "LIVE" if LIVE else "paper"
    dur = "unlimited (until killed)" if args.hours <= 0 else f"{args.hours}h"
    log_line(f"{mode} bot v4 start: ${state['cash']:.2f}, {dur}, "
             f"{len(COINS)} coins ({', '.join(coin_name(s) for s in COINS)}); "
             f"entry t-5(BTC) t-3/2:30/2(BTC,BNB) "
             f"t-1(ETH,NEAR,ZEC,HYPE), "
             f"gap 0.10% (0.15% NEAR/ZEC/HYPE), "
             f"{ENTRY_MIN*100:.0f}c-{ENTRY_MAX*100:.1f}c, "
             f"stop {STOP_TRIGGER:.0%}, size 1=50%/2=75%/3+=100% "
             f"(all-in single if <$5), "
             f"max {MAX_CONCURRENT} at once")

    new_log = not os.path.exists(args.log)
    f = open(args.log, "a", newline="")
    writer = csv.writer(f)
    if new_log:
        writer.writerow(["et_time", "ticker", "side", "entry_price",
                        "contracts", "cost", "result", "won",
                        "pnl", "pnl_pct", "cash_after"])
        f.flush()

    # Heartbeat disabled: at every 5 min it sent ~288 pings/day, which
    # by itself exceeded ntfy's free daily limit and got the server IP
    # rate-limited (dropping all alerts). Liveness is covered by systemd
    # (Restart=always) and the GitHub log pushes.

    boot_commit = repo_commit()
    threads: list[threading.Thread] = []

    def try_enter(cts, wstate, allowed):
        """One decision pass. Scans coins in `allowed` NOT already traded
        this window, sizes within the running total cap, and places
        orders. Updates wstate in place. Returns (n_new_qualifying,
        n_placed)."""
        candidates = []
        for series, product in COINS.items():
            if series not in allowed:
                continue                      # not eligible at this check
            if series in wstate["traded"]:
                continue                      # already traded this window
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

        # Establish the window-start balance once (first pass).
        if wstate["cash0"] is None:
            if LIVE:
                try:
                    with lock:
                        state["cash"] = live.balance_dollars()
                        save_cash()
                except Exception as e:
                    log_line(f"live balance check failed: {e}")
                    return 0, 0
            with lock:
                wstate["cash0"] = state["cash"]
        cash0 = wstate["cash0"]

        slots = MAX_CONCURRENT - len(wstate["traded"])
        candidates = candidates[:max(0, slots)]
        if not candidates:
            return 0, 0

        if cash0 < 5.0:
            # Recovery: all-in on one coin, once per window.
            if wstate["traded"]:
                return len(candidates), 0
            candidates = candidates[:1]
            budget = cash0
        else:
            # Total per window: 1 coin 50%, 2 coins 75%, 3+ coins 100%.
            n_total = len(wstate["traded"]) + len(candidates)
            total_cap = (0.50 if n_total == 1
                         else 0.75 if n_total == 2 else 1.00)
            budget = cash0 * total_cap - wstate["deployed"]
        if budget <= 0:
            return len(candidates), 0
        per = budget / len(candidates)

        placed = 0
        for _, gap, series, m, side, ask in candidates:
            unit = ask + fee(ask)
            contracts = int(per / unit)
            if contracts < 1:
                continue
            coin = coin_name(series)
            if LIVE:
                try:
                    ya = float(m.get("yes_ask_dollars") or 0)
                    yb = float(m.get("yes_bid_dollars") or 0)
                    yes_ask_c = math.ceil(ya * 100) + 2   # buy YES
                    yes_bid_c = int(yb * 100) - 2          # sell YES (buy NO)
                    resp = live.enter(m["ticker"], side, yes_ask_c,
                                      yes_bid_c, contracts)
                except Exception as e:
                    log_line(f"{coin}: LIVE order REJECTED: {e}")
                    notify(f"Kalshi bot: {coin} ORDER FAILED", str(e))
                    continue
                filled = int(float(resp.get("fill_count", 0) or 0))
                if filled < 1:
                    log_line(f"{coin}: order placed but 0 filled - skip "
                             f"{m['ticker']}")
                    continue
                contracts = filled
            else:
                with lock:
                    state["cash"] -= contracts * unit
                    save_cash()

            wstate["traded"].add(series)
            wstate["deployed"] += contracts * unit
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
        return len(candidates), placed

    def check_update():
        cur = repo_commit()
        if boot_commit and cur and cur != boot_commit:
            log_line(f"new code deployed ({cur[:7]}) - restarting to update")
            notify("Kalshi bot: UPDATING", "New code deployed; restarting.")
            return True
        return False

    while time.time() < deadline:
        if check_update():
            return
        anchor = open_markets("KXBTC15M")
        if not anchor:
            time.sleep(30)
            continue
        cts = min(close_ts_of(m) for m in anchor)

        # Walk the entry schedule (t-5 BTC/ETH, then t-3 / t-2:30 / t-2
        # for all coins). EVERY check runs - a coin qualifying late still
        # gets traded (new coins only; ones already traded this window
        # are skipped).
        wstate = {"cash0": None, "deployed": 0.0, "traded": set()}
        saw_qualifier = False
        for offset, allowed in ENTRY_SCHEDULE:
            while time.time() < cts - offset:
                if time.time() >= deadline:
                    break
                time.sleep(min(2.0, cts - offset - time.time()))
            if time.time() >= deadline:
                break
            # Only restart for a code update if nothing is open yet.
            if not wstate["traded"] and check_update():
                return
            n_found, _ = try_enter(cts, wstate, allowed)
            saw_qualifier = saw_qualifier or n_found > 0

        wtime = f"{dt.datetime.fromtimestamp(cts, ET):%I:%M %p ET}"
        if not wstate["traded"]:
            if not saw_qualifier:
                log_line(f"nothing to trade this window ({wtime} close)")
                notify("Kalshi bot: nothing to trade",
                       f"No qualifying coin for the {wtime} window.",
                       priority="low")
            else:
                log_line(f"qualified but nothing placed - too small "
                         f"({wtime} close)")
                notify("Kalshi bot: too small to trade",
                       f"A coin qualified but the balance was too small "
                       f"for 1 contract ({wtime}).", priority="low")
        # Move past this window before scanning for the next one.
        while time.time() < cts + 5:
            time.sleep(3)
        threads[:] = [t for t in threads if t.is_alive()]

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
