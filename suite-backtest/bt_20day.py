"""ORIGINAL strategy, ALL-DAY mode (spec Mode B) on 20 stocks, underlying.

Entries 9:35-15:30 whenever flat: close breaks running session high (LONG)
or session low (SHORT) with VWAP agreement; 0.25% pivot room filter;
stop = opposite side of the OPENING range; target = entry +/- 0.75*ATR(14)
capped at nearest pivot; <=10 trades/day; EOD flat; conservative fills.
$100 all-in per trade compounded per ticker; 0.02% round-trip friction.
Requires {SYM}_5m_60d.csv files (yfinance, 60d/5m) next to sweep_frac.py.
"""
import numpy as np
import pandas as pd
from bt_20orig import add_piv_lo, SYMS, CUT30
from sweep_frac import prepare, WARMUP_SESSIONS, COST_RT


def run_one(sym, start):
    out = add_piv_lo(prepare(sym))
    dates = np.array([d for d in out.index.date])
    sessions = sorted(set(dates))
    t0 = max(sessions[WARMUP_SESSIONS], start) if start else sessions[WARMUP_SESSIONS]
    n = len(out)
    bank, pos, trades = 100.0, None, []
    res, sup = [], []
    or_hi = or_lo = sess_hi = sess_lo = np.nan
    tt = 0
    cur = None
    for i in range(1, n):
        row = out.iloc[i]
        d = dates[i]
        new_day = d != cur
        if new_day:
            cur = d
            or_hi, or_lo = row.h, row.l
            sess_hi, sess_lo = row.h, row.l
            tt = 0
        if not np.isnan(row.piv_hi):
            res.append(row.piv_hi)
            res = res[-3:]
        if not np.isnan(row.piv_lo):
            sup.append(row.piv_lo)
            sup = sup[-3:]
        last_bar = (i + 1 >= n) or (dates[i + 1] != d)
        if pos is not None and not new_day:
            dirn = pos["dir"]
            exit_px = None
            stop_hit = (row.l <= pos["stop"]) if dirn == 1 else (row.h >= pos["stop"])
            tgt_hit = (row.h >= pos["tgt"]) if dirn == 1 else (row.l <= pos["tgt"])
            if stop_hit:
                gap = (row.o < pos["stop"]) if dirn == 1 else (row.o > pos["stop"])
                exit_px = row.o if gap else pos["stop"]
            elif tgt_hit:
                gap = (row.o > pos["tgt"]) if dirn == 1 else (row.o < pos["tgt"])
                exit_px = row.o if gap else pos["tgt"]
            elif last_bar:
                exit_px = row.c
            if exit_px is not None:
                ret = (exit_px / pos["entry"] - 1) * dirn - COST_RT
                bank *= 1 + ret
                trades.append(ret * 100)
                pos = None
        if (pos is None and not new_day and not last_bar and 5 <= row.mins < 360
                and tt < 10 and d >= t0 and not np.isnan(sess_hi)):
            up = row.c > sess_hi and row.c > row.vwap
            dn = row.c < sess_lo and row.c < row.vwap
            if up:
                nr = min([x for x in res if x > row.c], default=np.nan)
                room = 100.0 if np.isnan(nr) else (nr - row.c) / row.c * 100
                if room >= 0.25:
                    tgt = row.c + 0.75 * row.atr
                    if not np.isnan(nr) and nr < tgt:
                        tgt = nr
                    pos = dict(dir=1, entry=row.c, stop=or_lo, tgt=tgt)
                    tt += 1
            elif dn:
                ns = max([x for x in sup if x < row.c], default=np.nan)
                room = 100.0 if np.isnan(ns) else (row.c - ns) / row.c * 100
                if room >= 0.25:
                    tgt = row.c - 0.75 * row.atr
                    if not np.isnan(ns) and ns > tgt:
                        tgt = ns
                    pos = dict(dir=-1, entry=row.c, stop=or_hi, tgt=tgt)
                    tt += 1
        if not np.isnan(row.h):
            sess_hi = max(sess_hi, row.h) if not np.isnan(sess_hi) else row.h
            sess_lo = min(sess_lo, row.l) if not np.isnan(sess_lo) else row.l
    tr = np.array(trades)
    if not len(tr):
        return dict(n=0, win=0.0, pf=np.nan, bank=100.0)
    w = (tr > 0).sum()
    gp, gl = tr[tr > 0].sum(), -tr[tr < 0].sum()
    return dict(n=len(tr), win=100 * w / len(tr),
                pf=gp / gl if gl > 0 else np.inf, bank=bank)


if __name__ == "__main__":
    rows = [(s, run_one(s, None), run_one(s, CUT30)) for s in SYMS]
    rows.sort(key=lambda r: r[1]["bank"], reverse=True)
    print(f"{'ticker':<8}{'--- 56 sessions (all-day) ---':<36}{'--- last 30 days ---'}")
    print(f"{'':<8}{'trades':<8}{'win%':<7}{'PF':<7}{'ret%':<14}{'trades':<8}{'win%':<7}{'ret%'}")
    for s, f, m in rows:
        print(f"{s:<8}{f['n']:<8}{f['win']:<7.1f}{f['pf']:<7.2f}"
              f"{f['bank']-100:<+14.1f}{m['n']:<8}{m['win']:<7.1f}{m['bank']-100:+.1f}")
    fb = np.array([f["bank"] for _, f, _ in rows])
    mb = np.array([m["bank"] for _, _, m in rows])
    print(f"\n56-sess: winners {(fb>100).sum()}/20  avg {fb.mean()-100:+.1f}%  "
          f"median {np.median(fb)-100:+.1f}%")
    print(f"30-day : winners {(mb>100).sum()}/20  avg {mb.mean()-100:+.1f}%  "
          f"median {np.median(mb)-100:+.1f}%")
