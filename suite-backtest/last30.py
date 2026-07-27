"""Final config evaluated on the last 30 trading sessions only."""
import numpy as np
import pandas as pd
from collections import Counter
from backtest import Cfg, prepare, run_all, stats, TICKERS

FINAL = Cfg(entry_source="orb", orb_stop_or=True, atr_stop=3.0, atr_tgt=0.5,
            orb_end_min=150, eod_flat=True, use_bias_exit=False, time_stop_bars=78)

datasets = {t: prepare(t) for t in TICKERS}
all_dates = sorted(set(d for out in datasets.values() for d in out.date))
cut = all_dates[-30]
tr = [t for t in run_all(datasets, FINAL) if t["date"] >= cut]

def fmt(s):
    return f"n={s['n']:4d}  win={s['win']:5.1f}%  PF={s['pf']:4.2f}  avg/trade={s['avg']:+.3f}%"

print(f"LAST 30 SESSIONS: {cut} -> {all_dates[-1]}\n")
print(f"ALL    {fmt(stats(tr))}")
for tk in TICKERS:
    print(f"{tk:5s}  {fmt(stats([x for x in tr if x['ticker'] == tk]))}")

pnl = np.array([t["pnl"] for t in tr])
print(f"\ncumulative: {pnl.sum():+.2f}%   avg win {pnl[pnl>0].mean():+.3f}%   avg loss {pnl[pnl<0].mean():+.3f}%")
print(f"exits: {dict(Counter(t['why'] for t in tr))}")

df = pd.DataFrame(tr)
df["week"] = pd.to_datetime(df["date"].astype(str)).dt.to_period("W").astype(str)
wk = df.groupby("week").agg(n=("pnl", "size"), win=("pnl", lambda x: 100 * (x > 0).mean()), tot=("pnl", "sum"))
print("\nweek                        n   win%   sum%")
for w, r in wk.iterrows():
    print(f"{w}  {int(r['n']):3d}  {r['win']:5.1f}  {r['tot']:+6.2f}")

# daily hit-rate distribution
day = df.groupby("date").agg(n=("pnl", "size"), wins=("pnl", lambda x: (x > 0).sum()))
green = (df.groupby("date")["pnl"].sum() > 0).mean() * 100
print(f"\ngreen days (net P&L > 0): {green:.0f}% of {day.shape[0]} sessions")
