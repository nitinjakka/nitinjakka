"""Wide-universe scan: original all-day Mode B strategy, last 30 days.

Same rules as bt_20day.py (session hi/lo break + VWAP, both directions,
OR-opposite stop, 0.75*ATR target capped at pivots, 0.25% room filter,
<=10/day, EOD flat, conservative fills), array-optimized for speed.
Prints every ticker with a POSITIVE 30-day return, flagging >= +10%.
"""
import numpy as np
import pandas as pd
from pathlib import Path

HERE = Path(__file__).parent
COST_RT = 0.0002
CUT = pd.Timestamp("2026-06-27").date()
LAST_DAY = pd.Timestamp("2026-07-24").date()


def rma(s, n):
    return s.ewm(alpha=1 / n, adjust=False).mean()


def run_one(sym):
    df = pd.read_csv(HERE / f"{sym}_5m_60d.csv", index_col=0, parse_dates=True)
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    df.index = df.index.tz_convert("America/New_York")
    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
    dates_all = pd.Series(df.index.date, index=df.index)
    df = df[dates_all <= LAST_DAY]
    o = df.Open.values
    h = df.High.values
    l = df.Low.values
    c = df.Close.values
    v = df.Volume.values
    tr = pd.concat([df.High - df.Low, (df.High - df.Close.shift()).abs(),
                    (df.Low - df.Close.shift()).abs()], axis=1).max(axis=1)
    atr = rma(tr, 14).values
    dates = np.array([d for d in df.index.date])
    mins = (df.index.hour - 9) * 60 + (df.index.minute - 30)
    mins = np.asarray(mins)
    tp = (df.High + df.Low + df.Close) / 3
    dser = pd.Series(dates)
    vwap = ((tp.values * v) / 1).copy()
    vwap = pd.Series(tp.values * v).groupby(dser).cumsum().values / \
        np.maximum(pd.Series(v).groupby(dser).cumsum().values, 1e-9)
    n = len(df)
    L = R = 10
    piv_hi = np.full(n, np.nan)
    piv_lo = np.full(n, np.nan)
    for i in range(L + R, n):
        p = i - R
        wh = h[p - L:p + R + 1]
        wl = l[p - L:p + R + 1]
        if h[p] == wh.max():
            piv_hi[i] = h[p]
        if l[p] == wl.min():
            piv_lo[i] = l[p]

    bank = 100.0
    trades = []
    res, sup = [], []
    or_hi = or_lo = sess_hi = sess_lo = np.nan
    tt = 0
    cur = None
    pos = None
    for i in range(1, n):
        d = dates[i]
        new_day = d != cur
        if new_day:
            cur = d
            or_hi, or_lo = h[i], l[i]
            sess_hi, sess_lo = h[i], l[i]
            tt = 0
        if not np.isnan(piv_hi[i]):
            res.append(piv_hi[i])
            res = res[-3:]
        if not np.isnan(piv_lo[i]):
            sup.append(piv_lo[i])
            sup = sup[-3:]
        last_bar = (i + 1 >= n) or (dates[i + 1] != d)
        if pos is not None and not new_day:
            dirn, entry, stop, tgt = pos
            exit_px = None
            stop_hit = (l[i] <= stop) if dirn == 1 else (h[i] >= stop)
            tgt_hit = (h[i] >= tgt) if dirn == 1 else (l[i] <= tgt)
            if stop_hit:
                gap = (o[i] < stop) if dirn == 1 else (o[i] > stop)
                exit_px = o[i] if gap else stop
            elif tgt_hit:
                gap = (o[i] > tgt) if dirn == 1 else (o[i] < tgt)
                exit_px = o[i] if gap else tgt
            elif last_bar:
                exit_px = c[i]
            if exit_px is not None:
                ret = (exit_px / entry - 1) * dirn - COST_RT
                bank *= 1 + ret
                trades.append(ret * 100)
                pos = None
        if (pos is None and not new_day and not last_bar and 5 <= mins[i] < 360
                and tt < 10 and d >= CUT):
            up = c[i] > sess_hi and c[i] > vwap[i]
            dn = c[i] < sess_lo and c[i] < vwap[i]
            if up:
                nr = min([x for x in res if x > c[i]], default=np.nan)
                room = 100.0 if np.isnan(nr) else (nr - c[i]) / c[i] * 100
                if room >= 0.25:
                    tgt = c[i] + 0.75 * atr[i]
                    if not np.isnan(nr) and nr < tgt:
                        tgt = nr
                    pos = (1, c[i], or_lo, tgt)
                    tt += 1
            elif dn:
                ns = max([x for x in sup if x < c[i]], default=np.nan)
                room = 100.0 if np.isnan(ns) else (c[i] - ns) / c[i] * 100
                if room >= 0.25:
                    tgt = c[i] - 0.75 * atr[i]
                    if not np.isnan(ns) and ns > tgt:
                        tgt = ns
                    pos = (-1, c[i], or_hi, tgt)
                    tt += 1
        sess_hi = max(sess_hi, h[i])
        sess_lo = min(sess_lo, l[i])
    trarr = np.array(trades)
    wins = (trarr > 0).sum() if len(trarr) else 0
    return dict(sym=sym, n=len(trarr),
                win=100 * wins / len(trarr) if len(trarr) else 0.0, bank=bank)


if __name__ == "__main__":
    syms = open(HERE / "universe_ok.txt").read().split(",")
    rows = []
    for s in syms:
        try:
            rows.append(run_one(s))
        except Exception as e:
            print(f"[skip] {s}: {e!r}")
    rows.sort(key=lambda r: r["bank"], reverse=True)
    pos_rows = [r for r in rows if r["bank"] > 100.0]
    print(f"\nscanned {len(rows)} stocks, last 30 days (Jun 27 - Jul 24)")
    print(f"positive: {len(pos_rows)}   >= +10%: "
          f"{sum(1 for r in pos_rows if r['bank'] >= 110)}")
    print(f"\n{'ticker':<8}{'trades':<8}{'win%':<8}{'ret% (30d)'}")
    for r in pos_rows:
        flag = "  <== +10%" if r["bank"] >= 110 else ""
        print(f"{r['sym']:<8}{r['n']:<8}{r['win']:<8.1f}"
              f"{r['bank']-100:+.1f}{flag}")
    banks = np.array([r["bank"] for r in rows])
    print(f"\nuniverse stats: avg {banks.mean()-100:+.1f}%  "
          f"median {np.median(banks)-100:+.1f}%  "
          f"worst {banks.min()-100:+.1f}% ({rows[-1]['sym']})")
