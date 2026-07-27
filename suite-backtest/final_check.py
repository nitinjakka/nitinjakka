"""Definitive stats for the final validated config (matches combined-suite.pine defaults)."""
import numpy as np
from collections import Counter
from backtest import Cfg, prepare, run_all, stats, TICKERS

FINAL = Cfg(entry_source="orb", orb_stop_or=True, atr_stop=3.0, atr_tgt=0.5,
            orb_end_min=150, eod_flat=True, use_bias_exit=False, time_stop_bars=78)

datasets = {t: prepare(t) for t in TICKERS}
all_dates = sorted(set(d for out in datasets.values() for d in out.date))
split = all_dates[int(len(all_dates) * 0.67)]
tr = run_all(datasets, FINAL)

def fmt(s):
    return f"n={s['n']:4d}  win={s['win']:5.1f}%  PF={s['pf']:4.2f}  avg/trade={s['avg']:+.3f}%"

print("FINAL CONFIG: ORB entry (5m OR break + VWAP), stop=opposite OR side,")
print("target=0.5xATR (S/R capped), no bias exit, EOD flat, window 5-150min\n")
print(f"FULL 60 sessions : {fmt(stats(tr))}")
print(f"TRAIN (40 sess)  : {fmt(stats([t for t in tr if t['date'] <= split]))}")
print(f"TEST  (20 sess)  : {fmt(stats([t for t in tr if t['date'] > split]))}")

pnl = np.array([t["pnl"] for t in tr])
print(f"\ncumulative underlying move captured: {pnl.sum():+.1f}%  "
      f"avg win {pnl[pnl>0].mean():+.3f}%  avg loss {pnl[pnl<0].mean():+.3f}%")
print(f"exits: {dict(Counter(t['why'] for t in tr))}")
print(f"trades/day (5 tickers): {len(tr)/60:.1f}")

# weekly consistency
import pandas as pd
df = pd.DataFrame(tr)
df["week"] = pd.to_datetime(df["date"].astype(str)).dt.to_period("W").astype(str)
wk = df.groupby("week").agg(n=("pnl", "size"), win=("pnl", lambda x: 100 * (x > 0).mean()), tot=("pnl", "sum"))
print("\nweek                        n   win%   sum%")
for w, r in wk.iterrows():
    print(f"{w}  {int(r['n']):3d}  {r['win']:5.1f}  {r['tot']:+6.2f}")
