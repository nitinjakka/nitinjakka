"""ORIGINAL strategy (spec Mode A ORB) on 20 stocks, traded on the underlying.

Per strategy-spec.md: first bar close after 9:35 (window [5,150) min) breaking
OR high (LONG) / OR low (SHORT) with VWAP agreement; 0.25% room filter vs
nearest confirmed pivot; stop = opposite OR side; target = entry +/- 0.5*ATR
capped at nearest pivot; EOD flat; ONE trade/day/ticker; conservative fills.
$100 all-in per trade, compounded per ticker. 0.02% round-trip friction.
Columns: full ~56 sessions and last-30-days cut.
"""
import numpy as np
import pandas as pd
from sweep_frac import prepare, WARMUP_SESSIONS, COST_RT

SYMS = ["NVDA", "TSLA", "AAPL", "QQQ", "AMD", "META", "MSFT", "AMZN", "GOOGL",
        "NFLX", "AVGO", "PLTR", "COIN", "MSTR", "SMCI", "CRWD", "MU", "ARM",
        "UBER", "ORCL"]
CUT30 = pd.Timestamp("2026-06-27").date()


def add_piv_lo(out):
    L = R = 10
    ll = out.l.values
    n = len(out)
    piv_lo = np.full(n, np.nan)
    for i in range(L + R, n):
        p = i - R
        w = ll[p - L:p + R + 1]
        if not np.isnan(w).any() and ll[p] == w.min():
            piv_lo[i] = ll[p]
    out = out.copy()
    out["piv_lo"] = piv_lo
    return out


def run_one(sym, start):
    out = add_piv_lo(prepare(sym))
    dates = np.array([d for d in out.index.date])
    sessions = sorted(set(dates))
    t0 = max(sessions[WARMUP_SESSIONS], start) if start else sessions[WARMUP_SESSIONS]
    n = len(out)
    bank, pos, trades = 100.0, None, []
    res, sup = [], []
    or_hi = or_lo = np.nan
    orb_done = True
    cur = None
    for i in range(1, n):
        row = out.iloc[i]
        d = dates[i]
        new_day = d != cur
        if new_day:
            cur = d
            or_hi, or_lo = row.h, row.l
            orb_done = False
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
        if (pos is None and not orb_done and not new_day and not last_bar
                and 5 <= row.mins < 150 and d >= t0):
            up = row.c > or_hi and row.c > row.vwap
            dn = row.c < or_lo and row.c < row.vwap
            if up or dn:
                orb_done = True
                dirn = 1 if up else -1
                if dirn == 1:
                    n_res = min([x for x in res if x > row.c], default=np.nan)
                    room = 100.0 if np.isnan(n_res) else (n_res - row.c) / row.c * 100
                    if room < 0.25:
                        continue
                    tgt = row.c + 0.5 * row.atr
                    if not np.isnan(n_res) and n_res < tgt:
                        tgt = n_res
                    pos = dict(dir=1, entry=row.c, stop=or_lo, tgt=tgt)
                else:
                    n_sup = max([x for x in sup if x < row.c], default=np.nan)
                    room = 100.0 if np.isnan(n_sup) else (row.c - n_sup) / row.c * 100
                    if room < 0.25:
                        continue
                    tgt = row.c - 0.5 * row.atr
                    if not np.isnan(n_sup) and n_sup > tgt:
                        tgt = n_sup
                    pos = dict(dir=-1, entry=row.c, stop=or_hi, tgt=tgt)
    tr = np.array(trades)
    if not len(tr):
        return dict(n=0, win=0.0, pf=np.nan, bank=100.0)
    wins = (tr > 0).sum()
    gp, gl = tr[tr > 0].sum(), -tr[tr < 0].sum()
    return dict(n=len(tr), win=100 * wins / len(tr),
                pf=gp / gl if gl > 0 else np.inf, bank=bank)


rows = []
for s in SYMS:
    full = run_one(s, None)
    m30 = run_one(s, CUT30)
    rows.append((s, full, m30))
rows.sort(key=lambda r: r[1]["bank"], reverse=True)
print(f"{'ticker':<8}{'--- 56 sessions ---':<34}{'--- last 30 days ---'}")
print(f"{'':<8}{'trades':<8}{'win%':<7}{'PF':<7}{'ret%':<12}{'trades':<8}{'win%':<7}{'ret%'}")
for s, f, m in rows:
    print(f"{s:<8}{f['n']:<8}{f['win']:<7.1f}{f['pf']:<7.2f}{f['bank']-100:<+12.1f}"
          f"{m['n']:<8}{m['win']:<7.1f}{m['bank']-100:+.1f}")
fb = np.array([f["bank"] for _, f, _ in rows])
mb = np.array([m["bank"] for _, _, m in rows])
fw = np.array([f["win"] * f["n"] / 100 for _, f, _ in rows]).sum()
fn = np.array([f["n"] for _, f, _ in rows]).sum()
print(f"\n56-sess: winners {(fb>100).sum()}/20  avg {fb.mean()-100:+.1f}%  "
      f"median {np.median(fb)-100:+.1f}%  overall win rate {100*fw/fn:.1f}%")
print(f"30-day : winners {(mb>100).sum()}/20  avg {mb.mean()-100:+.1f}%  "
      f"median {np.median(mb)-100:+.1f}%")
