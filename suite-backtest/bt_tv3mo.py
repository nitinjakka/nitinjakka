"""All-day Mode B on TradingView 5-min data (~3 months, independent source).

Reads {SYM}_5m_tv.csv (tvdatafeed format: naive ET timestamps, lowercase
columns). Same engine/rules as scan_universe.py. Reports full-window and
last-30-day returns per ticker for cross-validation against the Yahoo runs.
"""
import numpy as np
import pandas as pd
from pathlib import Path

TVDIR = Path(r"E:\Nitin_Hadoop\Claude\trading-suite-repo\suite-backtest")
COST_RT = 0.0002
CUT30 = pd.Timestamp("2026-06-27").date()
SYMS = ["TSLA", "AAPL", "ORCL", "KLAC", "PANW", "SMR", "U", "NVDA", "AMZN",
        "CRWD", "SMCI"]


def rma(s, n):
    return s.ewm(alpha=1 / n, adjust=False).mean()


def load(sym):
    df = pd.read_csv(TVDIR / f"{sym}_5m_tv.csv", index_col=0, parse_dates=True)
    df.columns = [c.lower() for c in df.columns]
    df = df[["open", "high", "low", "close", "volume"]].dropna()
    # RTH only, and drop the trailing partial session (last date in file)
    df = df.between_time("09:30", "15:55")
    last = sorted(set(df.index.date))[-1]
    df = df[pd.Series(df.index.date, index=df.index) < last]
    return df


def run_one(sym, start=None):
    df = load(sym)
    o, h, l, c, v = (df.open.values, df.high.values, df.low.values,
                     df.close.values, df.volume.values)
    tr = pd.concat([df.high - df.low, (df.high - df.close.shift()).abs(),
                    (df.low - df.close.shift()).abs()], axis=1).max(axis=1)
    atr = rma(tr, 14).values
    dates = np.array([d for d in df.index.date])
    sessions = sorted(set(dates))
    t0 = max(sessions[3], start) if start else sessions[3]
    dser = pd.Series(dates)
    tp = (df.high + df.low + df.close) / 3
    vwap = pd.Series(tp.values * v).groupby(dser).cumsum().values / \
        np.maximum(pd.Series(v).groupby(dser).cumsum().values, 1e-9)
    n = len(df)
    L = R = 10
    piv_hi = np.full(n, np.nan)
    piv_lo = np.full(n, np.nan)
    for i in range(L + R, n):
        p = i - R
        if h[p] == h[p - L:p + R + 1].max():
            piv_hi[i] = h[p]
        if l[p] == l[p - L:p + R + 1].min():
            piv_lo[i] = l[p]

    bank = 100.0
    trades = []
    res, sup = [], []
    or_hi = or_lo = sess_hi = sess_lo = np.nan
    tt = 0
    cur = None
    pos = None
    peak, maxdd = 100.0, 0.0
    mins_arr = (df.index.hour - 9) * 60 + (df.index.minute - 30)
    mins_arr = np.asarray(mins_arr)
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
                peak = max(peak, bank)
                maxdd = min(maxdd, bank / peak - 1)
                pos = None
        if (pos is None and not new_day and not last_bar
                and 5 <= mins_arr[i] < 360 and tt < 10 and d >= t0):
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
    tr_ = np.array(trades)
    wins = (tr_ > 0).sum() if len(tr_) else 0
    gp, gl = (tr_[tr_ > 0].sum(), -tr_[tr_ < 0].sum()) if len(tr_) else (0, 0)
    return dict(sym=sym, n=len(tr_),
                win=100 * wins / len(tr_) if len(tr_) else 0,
                pf=gp / gl if gl > 0 else np.inf, bank=bank, dd=maxdd * 100,
                nsess=len([s for s in sessions if s >= t0]))


if __name__ == "__main__":
    rows = [(run_one(s), run_one(s, CUT30)) for s in SYMS]
    rows.sort(key=lambda r: r[0]["bank"], reverse=True)
    ns = rows[0][0]["nsess"]
    print(f"TradingView data, ~{ns} sessions (full) + last-30d column")
    print(f"{'ticker':<8}{'trades':<8}{'win%':<7}{'PF':<7}{'ret%':<10}"
          f"{'maxDD%':<9}{'ret30d%'}")
    for f, m in rows:
        print(f"{f['sym']:<8}{f['n']:<8}{f['win']:<7.1f}{f['pf']:<7.2f}"
              f"{f['bank']-100:<+10.1f}{f['dd']:<9.1f}{m['bank']-100:+.1f}")
    fb = np.array([f["bank"] for f, _ in rows])
    print(f"\nwinners {(fb>100).sum()}/{len(rows)}  avg {fb.mean()-100:+.1f}%  "
          f"median {np.median(fb)-100:+.1f}%")
