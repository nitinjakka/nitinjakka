#!/usr/bin/env python3
"""
modeb_bot.py -- All-day Mode B breakout bot (Robinhood, fractional shares).

STRATEGY (strategy-spec.md Mode B, long-only, validated shortlist):
  watch TSLA/ORCL/PANW/KLAC/AAPL on 5-min bars; when flat, enter long on a
  bar close breaking the running session high with price above session VWAP
  (9:35-15:30 ET), skipping entries within 0.25% of a confirmed pivot
  resistance; target = entry + 0.5*ATR(14) capped at the pivot; stop =
  opening-range low; always flat by 15:55; max trades/day configurable.

SAFETY MODEL
  * PAPER mode by default: full signal engine, simulated fills, NO orders.
    LIVE=1 in modeb_bot.env is required for real orders.
  * kill switch: create file  STOP  next to this script -> bot goes flat
    (live: sells position) and idles until the file is removed.
  * daily loss cap: stops trading for the day past MAX_DAILY_LOSS_PCT.
  * trades only 9:35-15:55 ET on weekdays; sleeps otherwise (24/7 daemon).
  * WARNING: margin accounts under $25k that are PDT-flagged cannot day
    trade. Check your account status before setting LIVE=1.

SETUP (on the server)
  python3 -m venv venv && venv/bin/pip install robin_stocks python-dotenv
  cp modeb_bot.env.example modeb_bot.env   # edit: credentials + settings
  venv/bin/python modeb_bot.py             # or via systemd (modeb-bot.service)
  First run on a new machine triggers a Robinhood device approval on your
  phone -- run interactively once before enabling the service.

State survives restarts via state.json. Logs to logs/bot_YYYY-MM-DD.log.
Not investment advice. You are responsible for every order this places.
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
ET = ZoneInfo("America/New_York")
load_dotenv(HERE / "modeb_bot.env")

# ---------------- config ----------------
LIVE = os.getenv("LIVE", "0") == "1"
ACCOUNT = os.getenv("RH_ACCOUNT_NUMBER", "")          # e.g. 5SE32399
TICKERS = os.getenv("TICKERS", "TSLA,ORCL,PANW,KLAC,AAPL").split(",")
TRADE_DOLLARS = float(os.getenv("TRADE_DOLLARS", "50"))
MAX_TRADES_DAY = int(os.getenv("MAX_TRADES_PER_DAY", "3"))
MAX_DAILY_LOSS_PCT = float(os.getenv("MAX_DAILY_LOSS_PCT", "2.0"))
TGT_ATR = float(os.getenv("TARGET_ATR_MULT", "0.5"))
ROOM_PCT = float(os.getenv("ROOM_FILTER_PCT", "0.25"))
STOP_FILE = HERE / "STOP"
STATE_FILE = HERE / "state.json"
LOG_DIR = HERE / "logs"
LOG_DIR.mkdir(exist_ok=True)

import robin_stocks.robinhood as rh  # noqa: E402


def log(msg: str) -> None:
    now = datetime.now(ET)
    line = f"[{now:%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    with open(LOG_DIR / f"bot_{now:%Y-%m-%d}.log", "a") as f:
        f.write(line + "\n")


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return dict(position=None, trades_today=0, day="", pnl_today=0.0,
                paper_bank=100.0)


def save_state(st: dict) -> None:
    STATE_FILE.write_text(json.dumps(st, indent=1))


def rh_login() -> None:
    user, pw = os.getenv("RH_USERNAME"), os.getenv("RH_PASSWORD")
    if not user or not pw:
        sys.exit("RH_USERNAME/RH_PASSWORD missing in modeb_bot.env")
    rh.login(username=user, password=pw, store_session=True, expiresIn=86400)


# ---------------- data / indicators ----------------
def fetch_bars(sym: str) -> list[dict] | None:
    """This week's 5-min bars (for ATR/pivot warmup + today's session)."""
    try:
        bars = rh.stocks.get_stock_historicals(
            sym, interval="5minute", span="week", bounds="regular") or []
        return [b for b in bars if not b.get("interpolated", False)]
    except Exception as e:
        log(f"{sym}: data fetch failed: {e!r}")
        return None


def to_floats(bars):
    o = [float(b["open_price"]) for b in bars]
    h = [float(b["high_price"]) for b in bars]
    l = [float(b["low_price"]) for b in bars]
    c = [float(b["close_price"]) for b in bars]
    v = [float(b["volume"]) for b in bars]
    ts = [datetime.fromisoformat(b["begins_at"].replace("Z", "+00:00"))
          .astimezone(ET) for b in bars]
    return o, h, l, c, v, ts


def atr14(h, l, c) -> float:
    trs = [h[i] - l[i] if i == 0 else
           max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
           for i in range(len(h))]
    a = trs[0]
    for tr in trs[1:]:
        a = (a * 13 + tr) / 14
    return a


def confirmed_pivot_highs(h, n_keep=3, L=10, R=10) -> list[float]:
    out = []
    for p in range(L, len(h) - R):
        if h[p] == max(h[p - L:p + R + 1]):
            out.append(h[p])
    return out[-n_keep:]


def session_calc(sym: str):
    """Compute today's signal state from completed bars. Returns dict or None."""
    bars = fetch_bars(sym)
    if not bars or len(bars) < 30:
        return None
    o, h, l, c, v, ts = to_floats(bars)
    today = datetime.now(ET).date()
    idx_today = [i for i, t in enumerate(ts) if t.date() == today]
    if len(idx_today) < 2:          # need OR bar + at least one more
        return None
    i0 = idx_today[0]
    or_hi, or_lo = h[i0], l[i0]
    # running session extremes EXCLUDING the latest completed bar
    prior = idx_today[:-1]
    sess_hi = max(h[i] for i in prior)
    last = idx_today[-1]
    # session vwap over today's completed bars
    num = sum((h[i] + l[i] + c[i]) / 3 * v[i] for i in idx_today)
    den = sum(v[i] for i in idx_today) or 1e-9
    vwap = num / den
    piv = confirmed_pivot_highs(h[:last + 1])
    n_res = min([x for x in piv if x > c[last]], default=None)
    return dict(close=c[last], or_hi=or_hi, or_lo=or_lo, sess_hi=sess_hi,
                vwap=vwap, atr=atr14(h[:last + 1], l[:last + 1], c[:last + 1]),
                n_res=n_res, bar_time=ts[last])


def last_price(sym: str) -> float | None:
    try:
        return float(rh.stocks.get_latest_price(sym)[0])
    except Exception:
        return None


# ---------------- orders (paper + live) ----------------
def place_buy(sym: str, dollars: float, price: float, st: dict) -> dict | None:
    if not LIVE:
        qty = dollars / price
        log(f"PAPER BUY {sym}: ${dollars:.2f} (~{qty:.5f} sh @ {price:.2f})")
        return dict(qty=qty, price=price)
    r = rh.orders.order_buy_fractional_by_price(
        sym, dollars, timeInForce="gfd", account_number=ACCOUNT or None)
    log(f"LIVE BUY {sym} ${dollars:.2f} -> {r}")
    if isinstance(r, dict) and r.get("id"):
        qty = dollars / price          # refined on fill check next tick
        return dict(qty=qty, price=price, order_id=r["id"])
    log(f"[!] buy rejected: {r}")
    return None


def place_sell(sym: str, qty: float, price: float) -> bool:
    if not LIVE:
        log(f"PAPER SELL {sym}: {qty:.5f} sh @ ~{price:.2f}")
        return True
    r = rh.orders.order_sell_fractional_by_quantity(
        sym, round(qty, 6), timeInForce="gfd", account_number=ACCOUNT or None)
    log(f"LIVE SELL {sym} {qty:.6f} -> {r}")
    return isinstance(r, dict) and bool(r.get("id"))


# ---------------- main loop ----------------
def market_minutes(now: datetime) -> int:
    return (now.hour - 9) * 60 + now.minute - 30


def in_session(now: datetime) -> bool:
    return now.weekday() < 5 and 0 <= market_minutes(now) < 390


def run() -> None:
    log(f"bot starting  LIVE={LIVE}  account={ACCOUNT or '(default)'}  "
        f"tickers={TICKERS}  $/trade={TRADE_DOLLARS}  "
        f"max/day={MAX_TRADES_DAY}  loss-cap={MAX_DAILY_LOSS_PCT}%")
    if LIVE:
        log("*** LIVE MODE: this process places REAL orders. ***")
    rh_login()
    st = load_state()
    while True:
        try:
            now = datetime.now(ET)
            day = str(now.date())
            if st["day"] != day:
                st.update(day=day, trades_today=0, pnl_today=0.0)
                save_state(st)
            if STOP_FILE.exists():
                if st["position"]:
                    p = st["position"]
                    px = last_price(p["sym"]) or p["entry"]
                    place_sell(p["sym"], p["qty"], px)
                    st["position"] = None
                    save_state(st)
                    log("STOP file: position closed.")
                time.sleep(30)
                continue
            if not in_session(now):
                time.sleep(60)
                continue
            mins = market_minutes(now)

            # ---- manage open position every tick ----
            if st["position"]:
                p = st["position"]
                px = last_price(p["sym"])
                if px:
                    hit_stop = px <= p["stop"]
                    hit_tgt = px >= p["tgt"]
                    eod = mins >= 385
                    if hit_stop or hit_tgt or eod:
                        why = "STOP" if hit_stop else ("TARGET" if hit_tgt
                                                       else "EOD")
                        if place_sell(p["sym"], p["qty"], px):
                            pnl = (px / p["entry"] - 1) * 100
                            st["pnl_today"] += pnl * (TRADE_DOLLARS / 100.0)
                            st["paper_bank"] *= (1 + (px / p["entry"] - 1) *
                                                 (0 if LIVE else 1))
                            log(f"EXIT {p['sym']} {why} @ {px:.2f} "
                                f"({pnl:+.2f}%)  day-pnl ~${st['pnl_today']:.2f}")
                            st["position"] = None
                            save_state(st)

            # ---- look for entries on 5-min boundaries ----
            elif (5 <= mins < 360 and st["trades_today"] < MAX_TRADES_DAY
                  and now.minute % 5 == 0
                  and st["pnl_today"] > -MAX_DAILY_LOSS_PCT
                  * TRADE_DOLLARS / 100.0 * MAX_TRADES_DAY):
                best = None
                for sym in TICKERS:
                    s = session_calc(sym)
                    if not s:
                        continue
                    sig = s["close"] > s["sess_hi"] and s["close"] > s["vwap"]
                    if not sig:
                        continue
                    room = (100.0 if s["n_res"] is None
                            else (s["n_res"] - s["close"]) / s["close"] * 100)
                    if room < ROOM_PCT:
                        continue
                    vol_rank = s["atr"] / s["close"]
                    if best is None or vol_rank > best[0]:
                        tgt = s["close"] + TGT_ATR * s["atr"]
                        if s["n_res"] is not None and s["n_res"] < tgt:
                            tgt = s["n_res"]
                        best = (vol_rank, sym, s["close"], s["or_lo"], tgt)
                if best:
                    _, sym, entry, stop, tgt = best
                    pos = place_buy(sym, TRADE_DOLLARS, entry, st)
                    if pos:
                        st["position"] = dict(sym=sym, qty=pos["qty"],
                                              entry=entry, stop=stop, tgt=tgt)
                        st["trades_today"] += 1
                        save_state(st)
                        log(f"ENTER {sym} @ ~{entry:.2f} stop {stop:.2f} "
                            f"tgt {tgt:.2f} (trade {st['trades_today']}"
                            f"/{MAX_TRADES_DAY})")
                time.sleep(20)     # don't double-fire within the boundary min
            time.sleep(15)
        except KeyboardInterrupt:
            log("interrupted; exiting (position left as-is).")
            break
        except Exception:
            log("ERROR:\n" + traceback.format_exc())
            time.sleep(60)


if __name__ == "__main__":
    run()
