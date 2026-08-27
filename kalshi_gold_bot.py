#!/usr/bin/env python3
"""LIVE bot: Kalshi Gold 15-minute markets (KXGOLD15M).

Strategy (Nitin, 2026-08-27):
  - At EXACTLY 30 seconds before each window's expiry, estimate the gold
    price and compare with the window's target (floor_strike).
  - If |gold - target| >= $1.00, send a marketable LIMIT at 99.8c for the
    LEADING side (YES if above target, NO if below), immediate-or-cancel:
    it fills at the current ask, whatever that is (95c, 98c, ...).
  - Only trade when that ask is between 80.0c and 99.8c:
      ask > 99.8c  -> priced out, skip (would not fill anyway)
      ask < 80.0c  -> market strongly disagrees with the signal, skip
        (backtest: every wrong-side signal had an ask of 0-2c; this floor
        filtered out all would-be losses)
  - Size: 100% of available Kalshi balance.
  - Hold to settlement. No stop (entry is ~30s before expiry).

Gold price source:
  Kalshi settles on the Pyth GOLD/USD index. Pyth's historical/latest price
  APIs now require an API key (HTTP 401), so by default the bot uses
  PAXG-USD on Coinbase (tokenized gold, 1:1) and computes the gap by
  DIFFERENCING: gap = (PAXG_now - PAXG_at_window_open) * strike/PAXG_open.
  The strike anchors the absolute level (it IS the Pyth price at window
  open), so the PAXG-vs-Pyth premium cancels; only 15-min tracking noise
  remains. If PYTH_API_KEY is set in the environment, the bot uses the
  real Pyth feed directly instead.

Run:  python3 kalshi_gold_bot.py --live     (requires KALSHI_* env vars)
Without --live it only logs what it would do.
"""

import argparse
import csv
import datetime as dt
import os
import subprocess
import time
from zoneinfo import ZoneInfo

import requests

API = "https://api.elections.kalshi.com/trade-api/v2"
ET = ZoneInfo("America/New_York")
SERIES = "KXGOLD15M"

GAP_MIN = 1.00          # dollars of gold vs target
LIMIT_YES = "0.9980"    # 99.8c limit, YES leg (buy YES)
LIMIT_NO_YESLEG = "0.0020"   # buying NO at 99.8c == selling YES at 0.2c
ASK_MAX = 0.998
ASK_MIN = 0.80
DECIDE_OFFSET = 30      # act exactly 30s before close
SAMPLE_LEAD = 1.5       # start price fetch this many seconds early

PAXG = "https://api.exchange.coinbase.com/products/PAXG-USD/ticker"
PYTH_ID = "fa0f57505be633c026896e15afef2c7ce2cf8ff9a45349d1da737f4f01266b01"
PYTH_KEY = os.environ.get("PYTH_API_KEY", "")

NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "nitin-kalshi-bot-x7q2")
LOG_CSV = "kalshi_gold_log.csv"

LIVE = False
live = None             # kalshi_live module (auth + balance), set in main


def log(msg: str) -> None:
    print(f"[{dt.datetime.now(ET):%I:%M:%S %p ET}] {msg}", flush=True)


_last_low = [0.0]


def notify(title: str, body: str, priority: str = "high") -> None:
    if priority == "low":
        if time.time() - _last_low[0] < 3600:
            return
        _last_low[0] = time.time()
    try:
        requests.post(f"https://ntfy.sh/{NTFY_TOPIC}", data=body.encode(),
                      headers={"Title": title, "Priority": priority},
                      timeout=10)
    except Exception:
        pass


def fee(p: float) -> float:
    return 0.07 * p * (1.0 - p)


def gold_price() -> float | None:
    """Best available live gold price. Pyth (exact settlement feed) if a
    key is configured, else PAXG spot. Retries fast; ~1s budget."""
    if PYTH_KEY:
        for _ in range(2):
            try:
                r = requests.get(
                    "https://hermes.pyth.network/v2/updates/price/latest",
                    params={"ids[]": PYTH_ID, "parsed": "true"},
                    headers={"Authorization": f"Bearer {PYTH_KEY}"},
                    timeout=3)
                if r.ok:
                    p = r.json()["parsed"][0]["price"]
                    return int(p["price"]) * 10 ** p["expo"]
            except Exception:
                pass
    for _ in range(3):
        try:
            r = requests.get(PAXG, timeout=3)
            if r.ok:
                return float(r.json()["price"])
        except Exception:
            time.sleep(0.3)
    return None


def get(path: str, params: dict | None = None) -> dict:
    for attempt in range(4):
        try:
            r = requests.get(API + path, params=params, timeout=10)
            r.raise_for_status()
            return r.json()
        except Exception:
            if attempt == 3:
                return {}
            time.sleep(1.5)
    return {}


def close_ts(m: dict) -> int:
    return int(dt.datetime.fromisoformat(
        m["close_time"].replace("Z", "+00:00")).timestamp())


def current_window() -> dict | None:
    """The open gold market whose 15-min window we are inside of."""
    now = time.time()
    ms = get("/markets", {"series_ticker": SERIES, "status": "open",
                          "limit": 6}).get("markets", [])
    best = None
    for m in ms:
        cts = close_ts(m)
        if now < cts <= now + 900:
            if best is None or cts < close_ts(best):
                best = m
    return best


def place_gold_order(ticker: str, side: str, count: int) -> dict:
    """IOC limit at 99.8c on the chosen side, deci-cent V2 order.
    side 'yes' -> bid YES at 0.9980 ; side 'no' -> ask YES at 0.0020."""
    import uuid
    body = {
        "ticker": ticker,
        "client_order_id": str(uuid.uuid4()),
        "side": "bid" if side == "yes" else "ask",
        "count": str(int(count)),
        "price": LIMIT_YES if side == "yes" else LIMIT_NO_YESLEG,
        "time_in_force": "immediate_or_cancel",
        "self_trade_prevention_type": "taker_at_cross",
    }
    return live._signed("POST", "/portfolio/events/orders", body)


def settle_result(ticker: str, timeout_s: int = 900) -> str:
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        m = get(f"/markets/{ticker}").get("market", {})
        if m.get("result"):
            return m["result"]
        time.sleep(10)
    return ""


def repo_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            stderr=subprocess.DEVNULL).decode().strip()
    except Exception:
        return ""


def main() -> None:
    global LIVE, live
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true")
    args = ap.parse_args()

    import kalshi_live as _live
    live = _live
    if args.live:
        summary = live.preflight()   # raises if creds/confirm missing
        LIVE = True
        bal = live.balance_dollars()
        log(f"*** GOLD BOT LIVE *** {summary}")
        notify("Gold bot: LIVE", f"Gold 15m strategy on. Balance ${bal:.2f}. "
               f"Gap >= ${GAP_MIN:.2f}, limit 99.8c, ask window "
               f"{ASK_MIN:.2f}-{ASK_MAX:.3f}, 100% sizing.")
    else:
        log("GOLD BOT dry-run (no --live): will log decisions only")

    src = "Pyth (keyed)" if PYTH_KEY else "PAXG/Coinbase differencing"
    px = gold_price()
    if px is None:
        log("FATAL: no gold price source reachable")
        notify("Gold bot: START FAILED", "No gold price source reachable.")
        return
    log(f"gold source: {src}; current ~${px:.2f}")

    new_log = not os.path.exists(LOG_CSV)
    f = open(LOG_CSV, "a", newline="")
    w = csv.writer(f)
    if new_log:
        w.writerow(["et_time", "ticker", "strike", "gold_open_ref",
                    "gold_t30", "gap", "side", "ask", "contracts",
                    "filled", "result", "won", "balance_after"])
        f.flush()

    boot = repo_commit()
    window_open_px: dict[int, float] = {}   # close_ts -> PAXG at window open

    while True:
        cur = repo_commit()
        if boot and cur and cur != boot:
            log(f"new code deployed ({cur[:7]}) - restarting")
            notify("Gold bot: UPDATING", "New code deployed; restarting.")
            return

        m = current_window()
        if not m:
            log("no active gold window (market closed?) - sleeping 120s")
            notify("Gold bot: gold market closed",
                   "No active 15-min gold window.", priority="low")
            time.sleep(120)
            continue
        ticker, cts = m["ticker"], close_ts(m)
        strike = m.get("floor_strike")

        # Reference price at window open: sample once, as early in the
        # window as we can. The strike IS the Pyth price at window open,
        # so pairing it with a PAXG sample taken at (nearly) the same
        # moment lets the 15-min CHANGE in PAXG stand in for the change
        # in the settlement index. If we joined the window late (e.g.
        # bot just started), the pair is invalid - skip that window.
        if cts not in window_open_px:
            p0 = gold_price()
            if p0 is None:
                time.sleep(5)
                continue
            opened_ago = 900 - (cts - time.time())
            window_open_px[cts] = (p0, opened_ago)
            log(f"{ticker}: window ref ${p0:.2f} "
                f"(sampled {opened_ago:.0f}s after open) strike={strike}")
        for k in [k for k in window_open_px if k < time.time() - 60]:
            del window_open_px[k]

        # Wait for the decision instant.
        wake = cts - DECIDE_OFFSET - SAMPLE_LEAD
        while time.time() < wake:
            time.sleep(min(5.0, wake - time.time()))

        if not strike:
            m = get(f"/markets/{ticker}").get("market", {})
            strike = m.get("floor_strike")
        p1 = gold_price()
        ref = window_open_px.get(cts)
        p0, ref_age = ref if ref else (None, None)
        if not strike or p1 is None or p0 is None:
            log(f"{ticker}: missing data at t-30 (strike={strike}, "
                f"p0={p0}, p1={p1}) - skip")
        elif ref_age > 120:
            log(f"{ticker}: window ref sampled {ref_age:.0f}s after open "
                f"(joined late) - gap unreliable, skip this window")
        else:
            strike = float(strike)
            gap = (p1 - p0) * (strike / p0)
            est = strike + gap
            if abs(gap) < GAP_MIN:
                log(f"{ticker}: gap ${gap:+.2f} < ${GAP_MIN:.2f} - no trade")
                notify("Gold bot: no trade",
                       f"gap ${gap:+.2f} too small", priority="low")
            else:
                side = "yes" if gap > 0 else "no"
                q = get(f"/markets/{ticker}").get("market", {})
                try:
                    ya = float(q.get("yes_ask_dollars") or 1)
                    yb = float(q.get("yes_bid_dollars") or 0)
                except (TypeError, ValueError):
                    ya, yb = 1.0, 0.0
                ask = ya if side == "yes" else round(1.0 - yb, 3)
                if ask > ASK_MAX:
                    log(f"{ticker}: gap ${gap:+.2f} {side.upper()} but ask "
                        f"{ask:.3f} > 99.8c - priced out, skip")
                elif ask < ASK_MIN:
                    log(f"{ticker}: gap ${gap:+.2f} {side.upper()} but ask "
                        f"{ask:.3f} < 80c - market disagrees, skip")
                    notify("Gold bot: protected skip",
                           f"{side.upper()} gap ${gap:+.2f} but ask only "
                           f"{ask:.2f} - signal/market conflict.")
                else:
                    filled = 0
                    if LIVE:
                        try:
                            bal = live.balance_dollars()
                            contracts = int(bal / (ask + fee(ask)))
                        except Exception as e:
                            log(f"balance check failed: {e}")
                            contracts = 0
                        if contracts < 1:
                            log(f"{ticker}: balance too small for 1 "
                                f"contract at {ask:.3f}")
                            notify("Gold bot: too small",
                                   f"Balance ${bal:.2f} < 1 contract "
                                   f"at {ask:.2f}.")
                        else:
                            try:
                                r = place_gold_order(ticker, side, contracts)
                                filled = int(float(r.get("fill_count", 0)
                                                   or 0))
                            except Exception as e:
                                log(f"{ticker}: ORDER FAILED: {e}")
                                notify("Gold bot: ORDER FAILED", str(e))
                            log(f"{ticker}: LIVE {side.upper()} IOC@99.8 "
                                f"ask~{ask:.3f} sent {contracts}, "
                                f"filled {filled} (gap ${gap:+.2f}, "
                                f"est ${est:.2f} vs strike ${strike:.2f})")
                            if filled:
                                notify(f"Gold bot: BUY {side.upper()}",
                                       f"{filled}x ~{ask:.2f} "
                                       f"(gap ${gap:+.2f}) {ticker}")
                            else:
                                notify("Gold bot: no fill",
                                       f"{side.upper()} ask {ask:.2f}, IOC "
                                       f"canceled unfilled. {ticker}",
                                       priority="low")
                    else:
                        log(f"{ticker}: DRY {side.upper()} would send IOC "
                            f"@99.8 ask~{ask:.3f} (gap ${gap:+.2f})")

                    if filled:
                        res = settle_result(ticker)
                        won = (res == side)
                        time.sleep(5)
                        bal_after = float("nan")
                        try:
                            bal_after = live.balance_dollars()
                        except Exception:
                            pass
                        log(f"{ticker}: result={res or 'timeout'} "
                            f"{'WIN' if won else 'LOSS'} "
                            f"balance ${bal_after:.2f}")
                        notify(f"Gold bot: {'WIN' if won else 'LOSS'}",
                               f"{side.upper()} {filled}x @~{ask:.2f} -> "
                               f"{res}. Balance ${bal_after:.2f}.")
                        w.writerow(
                            [dt.datetime.now(ET).strftime(
                                "%Y-%m-%d %I:%M:%S %p ET"),
                             ticker, f"{strike:.2f}", f"{p0:.2f}",
                             f"{p1:.2f}", f"{gap:+.2f}", side,
                             f"{ask:.3f}", contracts, filled,
                             res, won, f"{bal_after:.2f}"])
                        f.flush()

        # move past this window
        while time.time() < cts + 3:
            time.sleep(1)


if __name__ == "__main__":
    main()
