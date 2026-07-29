"""Best strategy on 20 movers, each traded individually on the STOCK.

Per ticker: Mode B long-only on 5-min bars -- enter on close > running
session high AND > VWAP (9:35-15:30, <=10/day, 0.25% pivot-resistance room
filter), target = entry + 0.5*ATR(14) capped at pivots, stop = opening-range
low, flat by 15:55. $100 all-in per trade, compounded. 0.02% round-trip
friction. Conservative fills (stop before target). ~56 sessions.
"""
import numpy as np
import pandas as pd
from sweep_frac import prepare, WARMUP_SESSIONS, COST_RT

SYMS = ["NVDA", "TSLA", "AAPL", "QQQ", "AMD", "META", "MSFT", "AMZN", "GOOGL",
        "NFLX", "AVGO", "PLTR", "COIN", "MSTR", "SMCI", "CRWD", "MU", "ARM",
        "UBER", "ORCL"]


def run_one(sym):
    out = prepare(sym)
    idx = out.index
    dates = np.array([d for d in idx.date])
    sessions = sorted(set(dates))
    trade_start = sessions[WARMUP_SESSIONS]
    n = len(out)
    bank, pos, trades = 100.0, None, []
    res_lvls = []
    or_lo = sess_hi = np.nan
    trades_today = 0
    cur = None
    peak, maxdd = 100.0, 0.0
    for i in range(1, n):
        row = out.iloc[i]
        d = dates[i]
        new_day = d != cur
        if new_day:
            cur = d
            or_lo, sess_hi = row.l, row.h
            trades_today = 0
        if not np.isnan(row.piv_hi):
            res_lvls.append(row.piv_hi)
            res_lvls = res_lvls[-3:]
        last_bar = (i + 1 >= n) or (dates[i + 1] != d)
        if pos is not None and not new_day:
            exit_px = None
            if row.l <= pos["stop"]:
                exit_px = row.o if row.o < pos["stop"] else pos["stop"]
            elif row.h >= pos["tgt"]:
                exit_px = row.o if row.o > pos["tgt"] else pos["tgt"]
            elif last_bar:
                exit_px = row.c
            if exit_px is not None:
                ret = exit_px / pos["entry"] - 1 - COST_RT
                bank *= 1 + ret
                trades.append(ret * 100)
                peak = max(peak, bank)
                maxdd = min(maxdd, bank / peak - 1)
                pos = None
        if (pos is None and not new_day and not last_bar and d >= trade_start
                and 5 <= row.mins < 360 and trades_today < 10
                and not np.isnan(sess_hi)):
            if row.c > sess_hi and row.c > row.vwap:
                n_res = min([x for x in res_lvls if x > row.c], default=np.nan)
                room = 100.0 if np.isnan(n_res) else (n_res - row.c) / row.c * 100
                if room >= 0.25:
                    tgt = row.c + 0.5 * row.atr
                    if not np.isnan(n_res) and n_res < tgt:
                        tgt = n_res
                    pos = dict(entry=row.c, stop=or_lo, tgt=tgt)
                    trades_today += 1
        if not np.isnan(row.h):
            sess_hi = max(sess_hi, row.h) if not np.isnan(sess_hi) else row.h
    tr = np.array(trades)
    wins = (tr > 0).sum()
    gp, gl = tr[tr > 0].sum(), -tr[tr < 0].sum()
    return dict(sym=sym, n=len(tr), win=100 * wins / len(tr) if len(tr) else 0,
                pf=gp / gl if gl > 0 else np.inf, bank=bank, dd=maxdd * 100)


rows = [run_one(s) for s in SYMS]
rows.sort(key=lambda r: r["bank"], reverse=True)
print(f"{'ticker':<8}{'trades':<8}{'win%':<8}{'PF':<7}{'$100 ->':<11}{'ret%':<9}{'maxDD%'}")
for r in rows:
    print(f"{r['sym']:<8}{r['n']:<8}{r['win']:<8.1f}{r['pf']:<7.2f}"
          f"${r['bank']:<10.2f}{r['bank']-100:<+9.1f}{r['dd']:.1f}")
banks = np.array([r["bank"] for r in rows])
print(f"\nwinners: {(banks > 100).sum()}/20   average: ${banks.mean():.2f} "
      f"({banks.mean()-100:+.1f}%)   median: ${np.median(banks):.2f} "
      f"({np.median(banks)-100:+.1f}%)")
