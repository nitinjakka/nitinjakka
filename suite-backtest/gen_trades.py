"""Dump the FINAL-config trade list (recent weeks) with exact entry/exit bar timestamps,
for pricing against real option premiums."""
import pandas as pd
from pathlib import Path
from backtest import Cfg, prepare, run, TICKERS

EXT = Path(__file__).parent / "data_ext"
FINAL = Cfg(entry_source="orb", orb_stop_or=True, atr_stop=3.0, atr_tgt=0.5,
            orb_end_min=150, eod_flat=True, use_bias_exit=False, time_stop_bars=78)

# need timestamps: re-run engine but also record bar times
rows = []
for t in TICKERS:
    out = prepare(t, data_dir=EXT)
    idx = out.index
    # re-run with bookkeeping: patch run() logic by re-simulating via its trades + positions
    # simplest: modify run to return bar indices -> we re-implement the tiny wrapper here
    import backtest as B
    import numpy as np
    bias = B.votes_and_bias(out, FINAL)
    n = len(out)
    o, h, l, c = out.o.values, out.h.values, out.l.values, out.c.values
    atr_v, vwap = out.atr.values, out.vwap.values
    mins, dates = out.mins.values, out.date.values
    piv_hi, piv_lo = out.piv_hi.values, out.piv_lo.values
    res_lvls, sup_lvls = [], []
    pos = 0; entry = stop = tgt = float("nan"); ebar = -1
    or_hi = or_lo = float("nan"); orb_done = True
    cur_date = None
    for i in range(1, n):
        if dates[i] != cur_date:
            cur_date = dates[i]
            or_hi, or_lo = h[i], l[i]
            orb_done = False
        if not np.isnan(piv_hi[i]):
            res_lvls.append(piv_hi[i]); res_lvls[:] = res_lvls[-3:]
        if not np.isnan(piv_lo[i]):
            sup_lvls.append(piv_lo[i]); sup_lvls[:] = sup_lvls[-3:]
        n_res = min([x for x in res_lvls if x > c[i]], default=float("nan"))
        n_sup = max([x for x in sup_lvls if x < c[i]], default=float("nan"))
        last_bar = (i + 1 >= n) or (dates[i + 1] != dates[i])
        if pos != 0:
            exit_px = None; why = None
            if pos == 1:
                if l[i] <= stop: exit_px, why = (o[i] if o[i] < stop else stop), "STOP"
                elif h[i] >= tgt: exit_px, why = (o[i] if o[i] > tgt else tgt), "TARGET"
                elif i - ebar >= FINAL.time_stop_bars: exit_px, why = c[i], "TIME"
            else:
                if h[i] >= stop: exit_px, why = (o[i] if o[i] > stop else stop), "STOP"
                elif l[i] <= tgt: exit_px, why = (o[i] if o[i] < tgt else tgt), "TIME" if False else "TARGET"
                elif i - ebar >= FINAL.time_stop_bars: exit_px, why = c[i], "TIME"
            if exit_px is None and last_bar: exit_px, why = c[i], "EOD"
            if exit_px is not None:
                rows.append(dict(ticker=t, dir=pos, entry_ts=idx[ebar], exit_ts=idx[i],
                                 entry_px=entry, exit_px=exit_px, why=why,
                                 pnl_underlying=(exit_px - entry) / entry * pos * 100))
                pos = 0
        if pos == 0 and not last_bar:
            orb_ok = (not orb_done) and 5 <= mins[i] < FINAL.orb_end_min
            orb_up = orb_ok and c[i] > or_hi and c[i] > vwap[i]
            orb_dn = orb_ok and c[i] < or_lo and c[i] < vwap[i]
            if orb_up or orb_dn: orb_done = True
            room_up = 100.0 if np.isnan(n_res) else (n_res - c[i]) / c[i] * 100
            room_dn = 100.0 if np.isnan(n_sup) else (c[i] - n_sup) / c[i] * 100
            if orb_up and room_up >= FINAL.sr_buf_pct:
                pos, entry, ebar = 1, c[i], i
                stop, tgt = or_lo, c[i] + atr_v[i] * FINAL.atr_tgt
                if not np.isnan(n_res) and n_res < tgt: tgt = n_res
            elif orb_dn and room_dn >= FINAL.sr_buf_pct:
                pos, entry, ebar = -1, c[i], i
                stop, tgt = or_hi, c[i] - atr_v[i] * FINAL.atr_tgt
                if not np.isnan(n_sup) and n_sup > tgt: tgt = n_sup

df = pd.DataFrame(rows)
df = df[df.entry_ts >= "2026-06-29"]
df = df.sort_values(["entry_ts"]).reset_index(drop=True)
df.insert(0, "id", df.index)
df.to_csv(Path(__file__).parent / "trades_recent.csv", index=False)
print(df.to_string(index=False))
print(f"\n{len(df)} trades since 6/29;  by week:")
print(df.groupby(pd.to_datetime(df.entry_ts.astype(str).str[:10]).dt.to_period("W").astype(str)).size())
