#!/usr/bin/env python3
"""
modeb_bot.py v2 -- "auto-trade-watchlist" strategy (STRATEGY_SPEC.md 2026-07-30).

Long-only intraday momentum, per the user's spec:
  * 18-symbol watchlist; SOFI auto-retires after its first profitable exit.
  * Entries (evaluated EVERY MINUTE, no daily cap, long only):
      - session breakout: price > session high (prior completed bars) AND > VWAP
      - bias flip: 6-vote confluence (EMA9>21, close>EMA50, RSI>50, MACD hist>0,
        +DI>-DI, HTF 60m close>EMA50) flips to >= +2 with ADX >= 20
      - skip if nearest pivot-high resistance is within 0.25%
  * Sizing: market buy of buying_power / POSITION_FRACTION dollars per entry;
    multiple concurrent positions allowed.
  * Exits -- tiered, NEVER at a loss:
      trailing armed at +2% (sell at peak * 0.99); quick take-profit in
      [+0.5%, +1%); everything else HOLD -- losses are held indefinitely.
  * 15:58 ET sweep: sell every ACCOUNT position in profit (vs avg cost),
    hold losers overnight.
  * Runs 04:00-20:00 ET weekdays (orders only fill in regular hours).

DEVIATION FROM SPEC: Robinhood serves no 1-min history; indicators use 5-min
bars + hourly HTF, while entries/exits are checked every minute on live quotes.

SAFETY NOTES (read before LIVE=1): NO STOP-LOSS by design -- losing positions
ride down indefinitely. Margin accounts accrue interest on held losers. The
+0.5% take-profit creates frequent same-day round trips (PDT risk on flagged
margin accounts under $25k). Kill switch: create file STOP next to this
script -> no new entries (exits continue per rules; never at a loss).
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
ET = ZoneInfo("America/New_York")
load_dotenv(HERE / "modeb_bot.env")

LIVE = os.getenv("LIVE", "0") == "1"
ACCOUNT = os.getenv("RH_ACCOUNT_NUMBER", "") or None
TICKERS = os.getenv(
    "TICKERS",
    "NVDA,AAPL,MSFT,AMZN,GOOGL,GOOG,AVGO,META,TSLA,PLTR,NFLX,SOFI,SPY,ORCL,"
    "SMCI,AMD,ARM,SPMO").split(",")
POSITION_FRACTION = int(os.getenv("POSITION_FRACTION", "10"))
ROOM_PCT = float(os.getenv("ROOM_FILTER_PCT", "0.25"))
TRAIL_ARM = float(os.getenv("TRAIL_ARM_PCT", "2.0")) / 100
TRAIL_GIVEBACK = float(os.getenv("TRAIL_GIVEBACK_PCT", "1.0")) / 100
TP_LO = float(os.getenv("TP_BAND_LO_PCT", "0.5")) / 100
TP_HI = float(os.getenv("TP_BAND_HI_PCT", "1.0")) / 100
ADX_MIN = float(os.getenv("ADX_THRESHOLD", "20"))
SCORE_MIN = int(os.getenv("SCORE_THRESHOLD", "2"))
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
    st = {}
    if STATE_FILE.exists():
        st = json.loads(STATE_FILE.read_text())
    st.setdefault("positions", {})
    # migrate v1 single-position format
    if st.get("position"):
        p = st.pop("position")
        st["positions"][p["sym"]] = dict(entry=p["entry"], qty=p["qty"],
                                         peak=p["entry"], trailing=False)
        log(f"migrated v1 position: {p['sym']}")
    st.setdefault("retired", [])
    st.setdefault("prev_bias", {})
    st.setdefault("sweep_done", "")
    st.setdefault("day", "")
    return st


def save_state(st: dict) -> None:
    STATE_FILE.write_text(json.dumps(st, indent=1))


def rh_login() -> None:
    user, pw = os.getenv("RH_USERNAME"), os.getenv("RH_PASSWORD")
    if not user or not pw:
        sys.exit("RH_USERNAME/RH_PASSWORD missing in modeb_bot.env")
    rh.login(username=user, password=pw, store_session=True, expiresIn=86400)


# ---------------- indicators (5-min bars; TradingView-style seeds) ----------
def ema_series(vals, n):
    out = []
    e = None
    for i, v in enumerate(vals):
        if i + 1 < n:
            out.append(None)
        elif i + 1 == n:
            e = sum(vals[:n]) / n
            out.append(e)
        else:
            e = (v - e) * (2 / (n + 1)) + e
            out.append(e)
    return out


def rma(vals, n):
    out = []
    r = None
    for i, v in enumerate(vals):
        if i + 1 < n:
            out.append(None)
        elif i + 1 == n:
            r = sum(vals[:n]) / n
            out.append(r)
        else:
            r = (r * (n - 1) + v) / n
            out.append(r)
    return out


def rsi14(closes):
    if len(closes) < 15:
        return None
    ups = [max(closes[i] - closes[i - 1], 0) for i in range(1, len(closes))]
    dns = [max(closes[i - 1] - closes[i], 0) for i in range(1, len(closes))]
    au, ad = rma(ups, 14)[-1], rma(dns, 14)[-1]
    if au is None or ad is None:
        return None
    return 100.0 if ad == 0 else 100 - 100 / (1 + au / ad)


def macd_hist(closes):
    if len(closes) < 35:
        return None
    f = ema_series(closes, 12)
    s = ema_series(closes, 26)
    line = [a - b for a, b in zip(f, s) if a is not None and b is not None]
    if len(line) < 9:
        return None
    sig = ema_series(line, 9)[-1]
    return None if sig is None else line[-1] - sig


def dmi_adx(h, l, c, n=14):
    if len(h) < 2 * n + 1:
        return None, None, None
    pdm, mdm, trs = [], [], []
    for i in range(1, len(h)):
        up, dn = h[i] - h[i - 1], l[i - 1] - l[i]
        pdm.append(up if up > dn and up > 0 else 0.0)
        mdm.append(dn if dn > up and dn > 0 else 0.0)
        trs.append(max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])))
    atr = rma(trs, n)
    pd_, md_ = rma(pdm, n), rma(mdm, n)
    dxs = []
    for a, p, m in zip(atr, pd_, md_):
        if a and p is not None and m is not None and (p + m) > 0:
            pdi, mdi = 100 * p / a, 100 * m / a
            dxs.append(100 * abs(pdi - mdi) / (pdi + mdi))
    if not dxs or len(dxs) < n:
        return None, None, None
    adx = rma(dxs, n)[-1]
    pdi = 100 * pd_[-1] / atr[-1]
    mdi = 100 * md_[-1] / atr[-1]
    return pdi, mdi, adx


# ---------------- data ----------------
def fetch_bars(sym):
    try:
        bars = rh.stocks.get_stock_historicals(
            sym, interval="5minute", span="week", bounds="regular") or []
        return [b for b in bars if not b.get("interpolated", False)]
    except Exception as e:
        log(f"{sym}: bars fetch failed {e!r}")
        return None


def fetch_htf_bull(sym):
    try:
        bars = rh.stocks.get_stock_historicals(
            sym, interval="hour", span="month", bounds="regular") or []
        closes = [float(b["close_price"]) for b in bars]
        if len(closes) < 50:
            return 0
        e50 = ema_series(closes, 50)[-1]
        return 1 if closes[-1] > e50 else -1
    except Exception:
        return 0


def latest_prices(syms):
    try:
        px = rh.stocks.get_latest_price(syms)
        return {s: float(p) for s, p in zip(syms, px) if p}
    except Exception as e:
        log(f"quote fetch failed {e!r}")
        return {}


def symbol_context(sym, htf_vote):
    """Indicators + session levels from completed 5-min bars."""
    bars = fetch_bars(sym)
    if not bars or len(bars) < 60:
        return None
    h = [float(b["high_price"]) for b in bars]
    l = [float(b["low_price"]) for b in bars]
    c = [float(b["close_price"]) for b in bars]
    v = [float(b["volume"]) for b in bars]
    ts = [datetime.fromisoformat(b["begins_at"].replace("Z", "+00:00"))
          .astimezone(ET) for b in bars]
    today = datetime.now(ET).date()
    idx = [i for i, t in enumerate(ts) if t.date() == today]
    sess_hi = max(h[i] for i in idx) if idx else None
    if idx:
        num = sum((h[i] + l[i] + c[i]) / 3 * v[i] for i in idx)
        den = sum(v[i] for i in idx) or 1e-9
        vwap = num / den
    else:
        vwap = None
    piv = []
    for p in range(10, len(h) - 10):
        if h[p] == max(h[p - 10:p + 11]):
            piv.append(h[p])
    piv = piv[-3:]
    e9 = ema_series(c, 9)[-1]
    e21 = ema_series(c, 21)[-1]
    e50 = ema_series(c, 50)[-1]
    rsi = rsi14(c)
    mh = macd_hist(c)
    pdi, mdi, adx = dmi_adx(h, l, c)
    if None in (e9, e21, e50, rsi, mh, pdi, mdi, adx):
        bias = 0
    elif adx < ADX_MIN:
        bias = 0
    else:
        score = ((1 if e9 > e21 else -1) + (1 if c[-1] > e50 else -1)
                 + (1 if rsi > 50 else -1) + (1 if mh > 0 else -1)
                 + (1 if pdi > mdi else -1) + htf_vote)
        bias = 1 if score >= SCORE_MIN else (-1 if score <= -SCORE_MIN else 0)
    return dict(sess_hi=sess_hi, vwap=vwap, pivots=piv, bias=bias)


# ---------------- account / orders ----------------
def buying_power() -> float:
    try:
        prof = rh.profiles.load_account_profile(account_number=ACCOUNT) or {}
        return float(prof.get("buying_power") or 0)
    except Exception:
        return 0.0


def place_buy(sym, dollars, price):
    if dollars < 1.0:
        return None
    if not LIVE:
        log(f"PAPER BUY {sym} ${dollars:.2f} @ ~{price:.2f}")
        return dollars / price
    r = rh.orders.order_buy_fractional_by_price(
        sym, round(dollars, 2), timeInForce="gfd", account_number=ACCOUNT)
    ok = isinstance(r, dict) and r.get("id")
    log(f"LIVE BUY {sym} ${dollars:.2f} -> "
        f"{'accepted ' + r['id'][:8] if ok else r}")
    return dollars / price if ok else None


def place_sell(sym, qty, price, why):
    if not LIVE:
        log(f"PAPER SELL {sym} {qty:.5f} @ ~{price:.2f} ({why})")
        return True
    r = rh.orders.order_sell_fractional_by_quantity(
        sym, round(qty, 6), timeInForce="gfd", account_number=ACCOUNT)
    ok = isinstance(r, dict) and r.get("id")
    log(f"LIVE SELL {sym} {qty:.6f} ({why}) -> "
        f"{'accepted ' + r['id'][:8] if ok else r}")
    return bool(ok)


def eod_sweep(st):
    """15:58: sell every ACCOUNT position in profit; hold losers."""
    try:
        positions = rh.account.get_open_stock_positions(
            account_number=ACCOUNT) or []
    except Exception as e:
        log(f"sweep: positions fetch failed {e!r}")
        return
    for p in positions:
        try:
            qty = float(p.get("quantity") or 0)
            if qty <= 0:
                continue
            sym = rh.stocks.get_symbol_by_url(p.get("instrument"))
            avg = float(p.get("average_buy_price") or 0)
            px = float(rh.stocks.get_latest_price(sym)[0])
            if avg > 0 and px > avg:
                if place_sell(sym, qty, px, "EOD_SWEEP"):
                    ret = (px / avg - 1) * 100
                    log(f"sweep sold {sym}: {ret:+.2f}%")
                    if sym == "SOFI" and ret > 0 and sym not in st["retired"]:
                        st["retired"].append(sym)
                        log("SOFI retired permanently (profitable exit)")
                    st["positions"].pop(sym, None)
            else:
                log(f"sweep holding {sym} (red: {px:.2f} vs avg {avg:.2f})")
        except Exception as e:
            log(f"sweep error on position: {e!r}")
    save_state(st)


# ---------------- main loop ----------------
def run():
    log(f"bot v2 starting  LIVE={LIVE}  account={ACCOUNT or '(default)'}  "
        f"{len(TICKERS)} tickers  size=BP/{POSITION_FRACTION}  "
        f"TP[{TP_LO*100:.1f}%,{TP_HI*100:.1f}%)  trail@{TRAIL_ARM*100:.0f}%"
        f"/-{TRAIL_GIVEBACK*100:.0f}%  NO-STOP-LOSS mode")
    if LIVE:
        log("*** LIVE MODE: places REAL orders; losers are HELD, never sold red ***")
    rh_login()
    st = load_state()
    ctx_cache = {}
    ctx_time = {}
    htf_cache = {}
    htf_time = {}
    while True:
        try:
            now = datetime.now(ET)
            day = str(now.date())
            if st["day"] != day:
                st["day"] = day
                save_state(st)
            hm = now.hour * 60 + now.minute
            if now.weekday() >= 5 or not (240 <= hm < 1200):  # 04:00-20:00
                time.sleep(120)
                continue
            regular = 570 <= hm < 960          # 09:30-16:00
            active = [s for s in TICKERS if s not in st["retired"]]
            prices = latest_prices(active)

            # ---- exits, every minute ----
            for sym in list(st["positions"].keys()):
                px = prices.get(sym)
                if not px:
                    continue
                p = st["positions"][sym]
                unreal = px / p["entry"] - 1
                if p.get("trailing"):
                    p["peak"] = max(p["peak"], px)
                    if px <= p["peak"] * (1 - TRAIL_GIVEBACK) and regular:
                        if place_sell(sym, p["qty"], px, "TRAIL"):
                            log(f"EXIT {sym} TRAIL {unreal*100:+.2f}%")
                            if sym == "SOFI" and unreal > 0:
                                st["retired"].append(sym)
                                log("SOFI retired permanently")
                            st["positions"].pop(sym)
                elif unreal >= TRAIL_ARM:
                    p["trailing"] = True
                    p["peak"] = px
                    log(f"{sym}: trailing armed at {unreal*100:+.2f}%")
                elif TP_LO <= unreal < TP_HI and regular:
                    if place_sell(sym, p["qty"], px, "TAKE_PROFIT"):
                        log(f"EXIT {sym} TP {unreal*100:+.2f}%")
                        if sym == "SOFI" and unreal > 0:
                            st["retired"].append(sym)
                            log("SOFI retired permanently")
                        st["positions"].pop(sym)
                # else: HOLD (includes all losses -- by design)
            save_state(st)

            # ---- EOD profit sweep at 15:58 ----
            if hm >= 958 // 1 and now.hour == 15 and now.minute >= 58 \
                    and st["sweep_done"] != day:
                st["sweep_done"] = day
                save_state(st)
                eod_sweep(st)

            # ---- entries, every minute (regular hours; no STOP file) ----
            if regular and hm < 955 and not STOP_FILE.exists():
                bp = buying_power() if LIVE else 1000.0
                size = bp / POSITION_FRACTION
                for sym in active:
                    if sym in st["positions"]:
                        continue
                    px = prices.get(sym)
                    if not px:
                        continue
                    # refresh context every 5 minutes per symbol
                    if (sym not in ctx_time
                            or (now - ctx_time[sym]).seconds >= 300):
                        if (sym not in htf_time
                                or (now - htf_time[sym]).seconds >= 3600):
                            htf_cache[sym] = fetch_htf_bull(sym)
                            htf_time[sym] = now
                        ctx_cache[sym] = symbol_context(sym, htf_cache[sym])
                        ctx_time[sym] = now
                    ctx = ctx_cache.get(sym)
                    if not ctx or ctx["sess_hi"] is None or ctx["vwap"] is None:
                        continue
                    breakout = px > ctx["sess_hi"] and px > ctx["vwap"]
                    prev = st["prev_bias"].get(sym, 0)
                    flip = ctx["bias"] == 1 and prev != 1
                    st["prev_bias"][sym] = ctx["bias"]
                    if not (breakout or flip):
                        continue
                    n_res = min([x for x in ctx["pivots"] if x > px],
                                default=None)
                    if n_res and (n_res - px) / px * 100 < ROOM_PCT:
                        continue
                    qty = place_buy(sym, size, px)
                    if qty:
                        st["positions"][sym] = dict(entry=px, qty=qty,
                                                    peak=px, trailing=False)
                        why = "breakout" if breakout else "bias-flip"
                        log(f"ENTER {sym} @ ~{px:.2f} ${size:.2f} ({why}) "
                            f"[{len(st['positions'])} open]")
                        save_state(st)
            time.sleep(60 - datetime.now(ET).second % 60)
        except KeyboardInterrupt:
            log("interrupted; positions left as-is.")
            break
        except Exception:
            log("ERROR:\n" + traceback.format_exc())
            time.sleep(60)


if __name__ == "__main__":
    run()
