"""Comparison: NVDA ORB-9:35 options (validated Mode A) on the SAME 19 sessions.

Entry: first 5-min bar close after 9:35 (window to 12:00) breaking the
opening range high (CALL) or low (PUT) with VWAP agreement, 0.25% room
filter. Option: Friday expiry, nearest OTM. Exits: premium -50% stop,
0.5*ATR underlying target (capped at pivots), else 15:55. Same BS pricing
as bt_930 (IV .51, hs $.025). $100 all-in compounded.
"""
import math
import numpy as np
import pandas as pd
from bt_930 import bs, friday_expiry, t_exp, HS, STEP, CUT, LAST_DAY
from sweep_frac import prepare

out = prepare("NVDA")
idx = out.index
dates = np.array([d for d in idx.date])
test_mask = (dates >= CUT) & (dates <= LAST_DAY)

bank = 100.0
log = []
res_lvls = []
cur = None
or_hi = or_lo = np.nan
orb_done = True
pos = None
for i in range(1, len(out)):
    row = out.iloc[i]
    d = dates[i]
    if d != cur:
        cur = d
        or_hi, or_lo = row.h, row.l
        orb_done = False
        pos = None          # safety: EOD exit happens on last bar anyway
    if not np.isnan(row.piv_hi):
        res_lvls.append(row.piv_hi)
        res_lvls = res_lvls[-3:]
    last_bar = (i + 1 >= len(out)) or (dates[i + 1] != d)
    ts = idx[i]

    if pos is not None:
        t = t_exp(ts + pd.Timedelta(minutes=5), pos["exp"])
        exit_prem = why = None
        worst_S = row.l if pos["dir"] == 1 else row.h
        tgt_hit = (row.h >= pos["tgt"]) if pos["dir"] == 1 else (row.l <= pos["tgt"])
        if bs(pos["dir"], worst_S, pos["K"], t) - HS <= 0.5 * pos["entry"]:
            exit_prem, why = 0.5 * pos["entry"], "STOP"
        elif tgt_hit:
            exit_prem = bs(pos["dir"], pos["tgt"], pos["K"], t) - HS
            why = "TGT"
        elif last_bar:
            exit_prem = max(bs(pos["dir"], row.c, pos["K"], t) - HS, 0.0)
            why = "EOD"
        if exit_prem is not None:
            ret = exit_prem / pos["entry"] - 1
            bank *= 1 + ret
            log.append(dict(day=str(d), dir="C" if pos["dir"] == 1 else "P",
                            why=why, ret=round(ret * 100, 1),
                            bank=round(bank, 2)))
            pos = None

    if pos is None and not orb_done and 5 <= row.mins < 150 and test_mask[i] \
            and not last_bar:
        up = row.c > or_hi and row.c > row.vwap
        dn = row.c < or_lo and row.c < row.vwap
        if up or dn:
            orb_done = True
            direction = 1 if up else -1
            n_res = min([x for x in res_lvls if x > row.c], default=np.nan)
            room_ok = True
            if direction == 1 and not np.isnan(n_res):
                room_ok = (n_res - row.c) / row.c * 100 >= 0.25
            if room_ok:
                exp = friday_expiry(d)
                K = (math.ceil(row.c / STEP) if direction == 1
                     else math.floor(row.c / STEP)) * STEP
                entry = bs(direction, row.c, K, t_exp(ts, exp)) + HS
                tgt = row.c + direction * 0.5 * row.atr
                if direction == 1 and not np.isnan(n_res) and n_res < tgt:
                    tgt = n_res
                pos = dict(dir=direction, K=K, exp=exp, entry=entry, tgt=tgt)

wins = sum(1 for x in log if x["ret"] > 0)
print(f"ORB-9:35 NVDA options, same sessions: {len(log)} trades, "
      f"{wins}W/{len(log)-wins}L   $100 -> ${bank:.2f} ({bank-100:+.1f}%)")
for x in log:
    print(f"  {x['day']}  {x['dir']}  {x['why']:<5} {x['ret']:>+7.1f}%  "
          f"bank ${x['bank']:>7.2f}")
