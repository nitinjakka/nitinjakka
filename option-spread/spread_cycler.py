#!/usr/bin/env python3
"""
spread_cycler.py -- cycle a short vertical CREDIT spread N times in a session.

Per-cycle loop:
  1. Pick a short strike at least MIN_OTM_PCT out of the money whose spread
     mid-credit is closest to this cycle's target credit.
  2. Sell the spread (limit order, price-walked from mid toward natural).
  3. Poll until profit target | stop loss | flatten time.
  4. Buy it back, record the exit price.
  5. Next cycle targets (this cycle's actual credit - CREDIT_STEP).
Repeat until MAX_CYCLES, ENTRY_CUTOFF, the MIN_CREDIT floor, or the loss cap.

READ BEFORE SETTING LIVE=1
  * Credit spreads risk more than they collect. A $1.00-wide spread sold for
    $0.32 risks $68 to make $32 -- you need ~68% wins just to break even.
    CREDIT_STEP makes this WORSE every cycle: by cycle 8 at $0.18 credit you
    risk $82 to make $18 (needs ~82% wins). That is the "open another trade
    with less price" rule as specified. Set CREDIT_STEP=0 to hold it flat.
  * 0DTE assignment: anything open at FLATTEN_TIME is closed with maximum
    price urgency. Do not disable that -- an ITM short call at expiry means
    100 short shares per contract delivered into your account.
  * PDT: 10 cycles = 10 day trades. On a margin account under $25k this will
    flag you as a pattern day trader.
  * robin_stocks uses Robinhood's private API. It is not sanctioned; heavy
    automated order flow carries real account risk.

Kill switch: create a file named STOP next to this script. No new cycles open;
any open spread is still closed by the normal exit rules.
"""
from __future__ import annotations

import csv
import json
import os
import sys
import time
import traceback
from datetime import datetime, date
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
ET = ZoneInfo("America/New_York")
load_dotenv(HERE / "spread_cycler.env")

import robin_stocks.robinhood as rh  # noqa: E402

try:
    import pyotp
except ImportError:  # optional, only for TOTP 2FA
    pyotp = None


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
def _f(name, default):
    return float(os.getenv(name, default))


def _i(name, default):
    return int(os.getenv(name, default))


LIVE = os.getenv("LIVE", "0") == "1"
ACCOUNT = os.getenv("RH_ACCOUNT_NUMBER", "").strip() or None

SYMBOL = os.getenv("SYMBOL", "SPY").upper().strip()
# "call" = bearish call credit spread (short lower strike, long higher).
# "put"  = bullish put credit spread (short higher strike, long lower).
SIDE = os.getenv("SIDE", "call").lower().strip()
WIDTH = _f("WIDTH", "1.0")               # dollars between the two strikes
QUANTITY = _i("QUANTITY", "1")           # contracts per cycle
EXPIRY = os.getenv("EXPIRY", "").strip()  # blank = today (0DTE)

MAX_CYCLES = _i("MAX_CYCLES", "10")
TARGET_CREDIT = _f("TARGET_CREDIT", "0.32")   # cycle 1 target credit/share
CREDIT_STEP = _f("CREDIT_STEP", "0.02")       # subtract per cycle ("less price")
MIN_CREDIT = _f("MIN_CREDIT", "0.10")         # stop cycling below this
MIN_OTM_PCT = _f("MIN_OTM_PCT", "0.10")       # short strike must be this % OTM

PROFIT_PCT = _f("PROFIT_PCT", "50")      # close once this % of credit captured
# Stop loss as a multiple of the credit. 0 = NO STOP: a losing spread is held
# until it becomes profitable or FLATTEN_TIME forces it out. On a 0DTE spread
# "hold until profitable" is not a guarantee -- the contract expires today, so
# the flatten can realize the full max loss. Read the README before using 0.
STOP_MULT = _f("STOP_MULT", "0")
MAX_DAILY_LOSS = _f("MAX_DAILY_LOSS", "200")  # realized-loss kill switch ($)

# How the next cycle's target credit is chosen:
#   below_exit -- must come in UNDER the price the last cycle closed at
#   step       -- previous target minus CREDIT_STEP
ENTRY_RULE = os.getenv("ENTRY_RULE", "below_exit").lower().strip()
HEARTBEAT_MINUTES = _f("HEARTBEAT_MINUTES", "5")

ENTRY_CUTOFF = os.getenv("ENTRY_CUTOFF", "15:00")   # no new cycles after
FLATTEN_TIME = os.getenv("FLATTEN_TIME", "15:45")   # force-close everything
POLL_SECONDS = _i("POLL_SECONDS", "10")
# Give up after this many consecutive failed entry attempts. Without it, a
# chain that has decayed below MIN_CREDIT makes the loop retry forever and
# hammer the API.
MAX_ENTRY_FAILS = _i("MAX_ENTRY_FAILS", "20")
# Floor on the poll interval so a misconfigured POLL_SECONDS=0 can't spin.
MIN_POLL_SECONDS = 2

# Limit-order price walking
ORDER_TIMEOUT = _i("ORDER_TIMEOUT", "90")     # seconds before giving up
REPRICE_SECONDS = _i("REPRICE_SECONDS", "15")  # how often to improve the price
PRICE_STEP = _f("PRICE_STEP", "0.01")         # increment per reprice

STOP_FILE = HERE / "STOP"
STATE_FILE = HERE / "state.json"
TRADE_LOG = HERE / "trades.csv"
LOG_DIR = HERE / "logs"
LOG_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Logging / state
# ---------------------------------------------------------------------------
def log(msg: str) -> None:
    now = datetime.now(ET)
    line = f"[{now:%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    with open(LOG_DIR / f"spread_{now:%Y-%m-%d}.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_state() -> dict:
    st = {}
    if STATE_FILE.exists():
        try:
            st = json.loads(STATE_FILE.read_text())
        except Exception:
            log("state.json unreadable -- starting fresh")
    today = str(date.today())
    if st.get("day") != today:      # new session resets the counters
        st = {"day": today}
    st.setdefault("cycle", 0)
    st.setdefault("realized", 0.0)
    st.setdefault("position", None)
    st.setdefault("next_credit", TARGET_CREDIT)
    st.setdefault("max_credit", None)
    st.setdefault("entry_fails", 0)
    return st


def save_state(st: dict) -> None:
    STATE_FILE.write_text(json.dumps(st, indent=2))


def log_trade(row: dict) -> None:
    new = not TRADE_LOG.exists()
    with open(TRADE_LOG, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[
            "timestamp", "cycle", "symbol", "side", "expiry",
            "short_strike", "long_strike", "qty",
            "entry_credit", "exit_debit", "pnl", "reason", "mode"])
        if new:
            w.writeheader()
        w.writerow(row)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _num(v, default=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _unwrap(data):
    """robin_stocks returns option data as [[{...}]] / [{...}] / {...}."""
    while isinstance(data, list):
        if not data:
            return None
        data = data[0]
    return data if isinstance(data, dict) else None


def _hhmm(s: str) -> tuple[int, int]:
    h, m = s.split(":")
    return int(h), int(m)


def past(clock: str) -> bool:
    now = datetime.now(ET)
    h, m = _hhmm(clock)
    return (now.hour, now.minute) >= (h, m)


def market_open() -> bool:
    now = datetime.now(ET)
    if now.weekday() >= 5:
        return False
    return (9, 30) <= (now.hour, now.minute) < (16, 0)


def rh_login() -> None:
    user, pwd = os.getenv("RH_USERNAME"), os.getenv("RH_PASSWORD")
    if not user or not pwd:
        sys.exit("Missing RH_USERNAME / RH_PASSWORD -- see spread_cycler.env.example")
    secret = os.getenv("RH_MFA_SECRET")
    code = None
    if secret:
        if pyotp is None:
            sys.exit("RH_MFA_SECRET set but pyotp missing -- pip install pyotp")
        code = pyotp.TOTP(secret).now()
    rh.login(username=user, password=pwd, mfa_code=code,
             store_session=True, expiresIn=86400)
    log(f"logged in as {user}  account={ACCOUNT or 'default'}")


def spot_price() -> float | None:
    try:
        p = rh.stocks.get_latest_price(SYMBOL)
        return _num(p[0]) if p else None
    except Exception as exc:
        log(f"quote failed: {exc!r}")
        return None


def expiry_date() -> str:
    return EXPIRY or str(date.today())


# ---------------------------------------------------------------------------
# Option chain / pricing
# ---------------------------------------------------------------------------
def leg_quote(strike: float, exp: str) -> tuple[float, float] | None:
    """(bid, ask) for one option leg, or None if it isn't quotable."""
    try:
        data = _unwrap(rh.options.get_option_market_data(
            SYMBOL, exp, f"{strike:.2f}", SIDE))
    except Exception as exc:
        log(f"market data failed for {strike}: {exc!r}")
        return None
    if not data:
        return None
    bid, ask = _num(data.get("bid_price")), _num(data.get("ask_price"))
    if bid is None or ask is None or ask <= 0:
        return None
    return bid, ask


def spread_prices(short_k: float, long_k: float, exp: str):
    """Return (mid, natural_credit, natural_debit) for the vertical.

    mid            -- fair value of the spread
    natural_credit -- what you'd receive selling immediately (short bid - long ask)
    natural_debit  -- what you'd pay buying immediately (short ask - long bid)
    """
    s = leg_quote(short_k, exp)
    l = leg_quote(long_k, exp)
    if not s or not l:
        return None
    s_bid, s_ask = s
    l_bid, l_ask = l
    mid = ((s_bid + s_ask) / 2) - ((l_bid + l_ask) / 2)
    return round(mid, 2), round(s_bid - l_ask, 2), round(s_ask - l_bid, 2)


def candidate_strikes(spot: float) -> list[float]:
    """Listed strikes far enough OTM, ordered nearest-the-money first."""
    exp = expiry_date()
    try:
        opts = rh.options.find_tradable_options(SYMBOL, exp, optionType=SIDE) or []
    except Exception as exc:
        log(f"chain lookup failed: {exc!r}")
        return []
    strikes = sorted({round(_num(o.get("strike_price"), 0), 2) for o in opts
                      if _num(o.get("strike_price"))})
    if not strikes:
        return []
    if SIDE == "call":
        floor = spot * (1 + MIN_OTM_PCT / 100)
        return [k for k in strikes if k >= floor][:12]
    ceiling = spot * (1 - MIN_OTM_PCT / 100)
    return [k for k in reversed(strikes) if k <= ceiling][:12]


def pick_spread(spot: float, target_credit: float, max_credit: float | None = None):
    """Choose the vertical whose mid-credit sits closest to target_credit.

    max_credit, when set, is a hard ceiling -- used by the 'below_exit' rule so
    a new cycle can never be opened at or above the price the last one closed.
    """
    exp = expiry_date()
    best = None
    for short_k in candidate_strikes(spot):
        long_k = short_k + WIDTH if SIDE == "call" else short_k - WIDTH
        pr = spread_prices(short_k, long_k, exp)
        if not pr:
            continue
        mid, nat_credit, _ = pr
        if mid < MIN_CREDIT or nat_credit <= 0:
            continue
        if mid >= WIDTH:            # nonsense quote, skip
            continue
        if max_credit is not None and mid >= max_credit:
            continue
        gap = abs(mid - target_credit)
        if best is None or gap < best[0]:
            best = (gap, short_k, long_k, mid, nat_credit)
    if not best:
        return None
    _, short_k, long_k, mid, nat = best
    return {"short": short_k, "long": long_k, "mid": mid,
            "natural": nat, "expiry": exp}


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------
def build_legs(short_k: float, long_k: float, exp: str, opening: bool) -> list:
    """Leg dicts for order_option_spread.

    NOTE: robin_stocks' docstring omits 'ratio_quantity' but the function
    reads it -- leaving it out raises KeyError.
    """
    effect = "open" if opening else "close"
    short_action = "sell" if opening else "buy"
    long_action = "buy" if opening else "sell"
    return [
        {"expirationDate": exp, "strike": short_k, "optionType": SIDE,
         "effect": effect, "action": short_action, "ratio_quantity": 1},
        {"expirationDate": exp, "strike": long_k, "optionType": SIDE,
         "effect": effect, "action": long_action, "ratio_quantity": 1},
    ]


def order_fill_price(order_id: str, fallback: float) -> float:
    """Per-share fill price from an option order, falling back to the limit."""
    try:
        info = rh.orders.get_option_order_info(order_id) or {}
    except Exception:
        return fallback
    prem = _num(info.get("processed_premium"))
    qty = _num(info.get("processed_quantity"))
    if prem and qty:
        return round(abs(prem) / (qty * 100), 4)
    return _num(info.get("price"), fallback) or fallback


def work_order(direction: str, legs: list, start: float, limit_floor: float,
               urgent: bool = False):
    """Place a spread limit order and walk the price until it fills.

    direction    -- 'credit' (opening) or 'debit' (closing)
    start        -- first limit price (the mid)
    limit_floor  -- worst acceptable price (natural); walking stops here
    urgent       -- go straight to the natural price (used at flatten time)

    Returns the per-share fill price, or None if nothing filled.
    """
    price = round(limit_floor if urgent else start, 2)
    # credit: we lower the ask to get filled. debit: we raise the bid.
    step = -PRICE_STEP if direction == "credit" else PRICE_STEP
    deadline = time.time() + ORDER_TIMEOUT
    order_id = None

    while time.time() < deadline:
        if not LIVE:
            log(f"PAPER {direction.upper()} spread @ {price:.2f}")
            return price

        try:
            r = rh.orders.order_option_spread(
                direction, price, SYMBOL, QUANTITY, legs,
                account_number=ACCOUNT, timeInForce="gfd")
        except Exception as exc:
            log(f"order error: {exc!r}")
            return None
        if not (isinstance(r, dict) and r.get("id")):
            log(f"order rejected: {r}")
            return None
        order_id = r["id"]
        log(f"LIVE {direction} @ {price:.2f} -> {order_id[:8]}")

        waited = 0
        while waited < REPRICE_SECONDS:
            time.sleep(3)
            waited += 3
            try:
                info = rh.orders.get_option_order_info(order_id) or {}
            except Exception:
                continue
            state = info.get("state")
            if state == "filled":
                fill = order_fill_price(order_id, price)
                log(f"filled @ {fill:.2f}")
                return fill
            if state in ("cancelled", "rejected", "failed"):
                log(f"order {state}")
                order_id = None
                break

        if order_id:                       # not filled -- cancel and reprice
            try:
                rh.orders.cancel_option_order(order_id)
            except Exception:
                pass
            order_id = None

        nxt = round(price + step, 2)
        # don't walk past the natural price (that's the worst we accept)
        if direction == "credit" and nxt < limit_floor:
            nxt = limit_floor
        if direction == "debit" and nxt > limit_floor:
            nxt = limit_floor
        if abs(nxt - price) < 1e-9:
            log("price walk exhausted at natural -- giving up this attempt")
            break
        price = nxt

    if order_id:
        try:
            rh.orders.cancel_option_order(order_id)
        except Exception:
            pass
    return None


# ---------------------------------------------------------------------------
# Cycle mechanics
# ---------------------------------------------------------------------------
def open_cycle(st: dict) -> bool:
    spot = spot_price()
    if spot is None:
        return False
    target = max(st["next_credit"], MIN_CREDIT)
    ceiling = st.get("max_credit")     # set by the 'below_exit' rule
    pick = pick_spread(spot, target, max_credit=ceiling)
    if not pick:
        cap = f" under ${ceiling:.2f}" if ceiling else ""
        log(f"no spread found near ${target:.2f} credit{cap} (spot {spot:.2f})")
        return False
    if pick["mid"] < MIN_CREDIT:
        log(f"best available credit ${pick['mid']:.2f} < floor "
            f"${MIN_CREDIT:.2f} -- stopping")
        st["cycle"] = MAX_CYCLES
        return False

    log(f"cycle {st['cycle'] + 1}/{MAX_CYCLES}: {SYMBOL} {spot:.2f} -> sell "
        f"{pick['short']:.0f}/{pick['long']:.0f} {SIDE} exp {pick['expiry']} "
        f"target ${target:.2f} mid ${pick['mid']:.2f} nat ${pick['natural']:.2f}")

    legs = build_legs(pick["short"], pick["long"], pick["expiry"], opening=True)
    fill = work_order("credit", legs, pick["mid"], pick["natural"])
    if fill is None:
        log("entry did not fill -- will retry next poll")
        return False

    risk = (WIDTH - fill) * 100 * QUANTITY
    log(f"OPENED for ${fill:.2f} credit  (max profit ${fill * 100 * QUANTITY:.0f} "
        f"/ max loss ${risk:.0f})")
    st["cycle"] += 1
    st["entry_fails"] = 0
    st["position"] = {
        "short": pick["short"], "long": pick["long"], "expiry": pick["expiry"],
        "credit": fill, "opened": datetime.now(ET).isoformat(timespec="seconds"),
    }
    save_state(st)
    return True


def close_cycle(st: dict, reason: str, urgent: bool = False) -> bool:
    p = st["position"]
    pr = spread_prices(p["short"], p["long"], p["expiry"])
    if not pr and not urgent:
        return False
    mid, _, nat_debit = pr if pr else (p["credit"], 0, WIDTH)

    legs = build_legs(p["short"], p["long"], p["expiry"], opening=False)
    fill = work_order("debit", legs, mid, nat_debit, urgent=urgent)
    if fill is None:
        log(f"exit did not fill ({reason}) -- retrying next poll")
        return False

    pnl = (p["credit"] - fill) * 100 * QUANTITY
    st["realized"] += pnl
    log(f"CLOSED @ ${fill:.2f} ({reason})  P&L ${pnl:+.2f}  "
        f"session ${st['realized']:+.2f}")

    log_trade({
        "timestamp": datetime.now(ET).isoformat(timespec="seconds"),
        "cycle": st["cycle"], "symbol": SYMBOL, "side": SIDE,
        "expiry": p["expiry"], "short_strike": p["short"],
        "long_strike": p["long"], "qty": QUANTITY,
        "entry_credit": round(p["credit"], 2), "exit_debit": round(fill, 2),
        "pnl": round(pnl, 2), "reason": reason,
        "mode": "LIVE" if LIVE else "PAPER",
    })

    # "open another trade with less price"
    if ENTRY_RULE == "below_exit":
        # The next cycle must come in UNDER the price this one closed at.
        st["max_credit"] = round(fill, 2)
        st["next_credit"] = round(max(fill - CREDIT_STEP, MIN_CREDIT), 2)
        log(f"next cycle must open below ${fill:.2f} "
            f"(targeting ${st['next_credit']:.2f})")
    else:
        # Step down from whichever is lower, the previous target or the fill.
        # Stepping from the fill alone stalls -- it snaps back to the nearest
        # listed strike (~$0.09 apart on $1-wide SPY), so a $0.02 step never
        # reaches a new strike and every cycle re-sells the same credit.
        base = min(st["next_credit"], p["credit"])
        st["next_credit"] = round(max(base - CREDIT_STEP, MIN_CREDIT), 2)
        st["max_credit"] = None
    st["position"] = None
    save_state(st)
    return True


_last_heartbeat = 0.0


def check_exit(st: dict) -> None:
    global _last_heartbeat
    p = st["position"]
    if past(FLATTEN_TIME):
        close_cycle(st, "flatten", urgent=True)
        return
    pr = spread_prices(p["short"], p["long"], p["expiry"])
    if not pr:
        return
    mid = pr[0]
    take = round(p["credit"] * (1 - PROFIT_PCT / 100), 2)

    # A held position is otherwise silent for hours -- say where it stands.
    if time.time() - _last_heartbeat >= HEARTBEAT_MINUTES * 60:
        _last_heartbeat = time.time()
        stop_txt = (f" stop ${p['credit'] * STOP_MULT:.2f}" if STOP_MULT > 0
                    else " no stop")
        log(f"holding {p['short']:.0f}/{p['long']:.0f} sold ${p['credit']:.2f} "
            f"| now ${mid:.2f} | P&L ${(p['credit'] - mid) * 100 * QUANTITY:+.0f} "
            f"| target ${take:.2f}{stop_txt}")

    if mid <= take:
        close_cycle(st, "target")
    elif STOP_MULT > 0 and mid >= round(p["credit"] * STOP_MULT, 2):
        close_cycle(st, "stop")


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
def banner() -> None:
    log("=" * 62)
    log(f"spread_cycler  {'*** LIVE ***' if LIVE else 'PAPER (no real orders)'}")
    log(f"  {SYMBOL} {SIDE} credit spread  width ${WIDTH:.2f}  qty {QUANTITY}")
    log(f"  cycles {MAX_CYCLES}  credit ${TARGET_CREDIT:.2f} step -${CREDIT_STEP:.2f} "
        f"floor ${MIN_CREDIT:.2f}")
    stop_txt = f"stop {STOP_MULT:.1f}x" if STOP_MULT > 0 else "NO STOP LOSS"
    log(f"  take {PROFIT_PCT:.0f}% of credit  {stop_txt}  "
        f"loss cap ${MAX_DAILY_LOSS:.0f}")
    log(f"  entry rule: {ENTRY_RULE}  no entries after {ENTRY_CUTOFF}  "
        f"flatten {FLATTEN_TIME}")
    if STOP_MULT <= 0:
        log(f"  WARNING: losers are held, not stopped. These expire "
            f"{expiry_date()} -- the {FLATTEN_TIME} flatten can realize the "
            f"full ${(WIDTH - MIN_CREDIT) * 100 * QUANTITY:.0f} max loss.")
    if ENTRY_RULE == "below_exit":
        log("  each cycle must open below the previous cycle's exit price, so "
            "the credit ladder falls fast and may hit the floor early")
    log("=" * 62)


def run() -> None:
    banner()
    rh_login()
    st = load_state()
    if st["position"]:
        log(f"resuming open position: {st['position']}")

    while True:
        try:
            if not market_open():
                if st["position"]:
                    log("market closed with a position open -- check manually")
                log("market closed; exiting")
                return

            if st["position"]:
                check_exit(st)
            else:
                if st["cycle"] >= MAX_CYCLES:
                    log(f"all {MAX_CYCLES} cycles done. session P&L "
                        f"${st['realized']:+.2f}")
                    return
                if STOP_FILE.exists():
                    log("STOP file present -- no new cycles")
                    return
                if st["realized"] <= -abs(MAX_DAILY_LOSS):
                    log(f"daily loss cap hit (${st['realized']:+.2f}) -- stopping")
                    return
                if past(ENTRY_CUTOFF):
                    log(f"past {ENTRY_CUTOFF} entry cutoff -- no new cycles")
                    return
                if not open_cycle(st):
                    st["entry_fails"] += 1
                    if st["entry_fails"] >= MAX_ENTRY_FAILS:
                        log(f"{MAX_ENTRY_FAILS} consecutive failed entries -- "
                            f"stopping. Session P&L ${st['realized']:+.2f}")
                        return

            save_state(st)
            time.sleep(max(POLL_SECONDS, MIN_POLL_SECONDS))

        except KeyboardInterrupt:
            log("interrupted by user")
            save_state(st)
            return
        except Exception:
            log("loop error:\n" + traceback.format_exc())
            time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    try:
        run()
    finally:
        try:
            rh.logout()
        except Exception:
            pass
