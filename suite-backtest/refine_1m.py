"""Refine the all-day (daybreak) mode and finalize per-ticker view on 1-min."""
import numpy as np
import pandas as pd
from dataclasses import replace
from collections import Counter
from bt1m import Cfg1, prepare1m, run_all, stats, TICKERS

datasets = {t: prepare1m(t) for t in TICKERS}
all_dates = sorted(set(d for out in datasets.values() for d in out.date))
split = all_dates[int(len(all_dates) * 0.66)]

def ev(name, cfg, ret=False):
    tr = run_all(datasets, cfg)
    a = stats(tr); trn = stats([x for x in tr if x["date"] <= split]); te = stats([x for x in tr if x["date"] > split])
    print(f"{name:46s} ALL n={a['n']:4d} {a['win']:5.1f}% PF={a['pf']:4.2f} avg={a['avg']:+.3f} | "
          f"TEST n={te['n']:3d} {te['win']:5.1f}% PF={te['pf']:4.2f}")
    return tr if ret else None

DB = Cfg1(entry_source="daybreak", entry_cutoff_min=360, orb_stop_or=True, atr_tgt=0.5)

print("== daybreak stop/target refinement ==")
ev("daybreak stopOR tgt0.5  (base)", DB)
ev("daybreak stopVWAP tgt0.5", replace(DB, stop_mode="vwap"))
ev("daybreak stopVWAP tgt0.75", replace(DB, stop_mode="vwap", atr_tgt=0.75))
ev("daybreak stopVWAP tgt1.0", replace(DB, stop_mode="vwap", atr_tgt=1.0))
ev("daybreak stopOR tgt1.0", replace(DB, atr_tgt=1.0))
ev("daybreak stopOR tgt0.75 max3/day", replace(DB, atr_tgt=0.75, max_trades_day=3))
ev("daybreak stopOR tgt0.75 max5/day", replace(DB, atr_tgt=0.75, max_trades_day=5))

print("\n== per-ticker: the two finalists ==")
FIN_ORB = Cfg1(entry_source="orb", orb_stop_or=True, atr_tgt=0.5)
FIN_DAY = replace(DB, atr_tgt=0.75)
for name, cfg in [("ORB-only tgt0.5", FIN_ORB), ("daybreak tgt0.75", FIN_DAY)]:
    tr = run_all(datasets, cfg)
    print(f"\n{name}:")
    for t in TICKERS:
        s = stats([x for x in tr if x["ticker"] == t])
        print(f"  {t:5s} n={s['n']:4d} win={s['win']:5.1f}% PF={s['pf']:4.2f} avg={s['avg']:+.3f}%")
    s = stats(tr); print(f"  ALL   n={s['n']:4d} win={s['win']:5.1f}% PF={s['pf']:4.2f} avg={s['avg']:+.3f}%")
    ex = stats([x for x in tr if x["ticker"] != "SPY"])
    print(f"  exSPY n={ex['n']:4d} win={ex['win']:5.1f}% PF={ex['pf']:4.2f} avg={ex['avg']:+.3f}%")
    print(f"  exits: {dict(Counter(x['why'] for x in tr))}  trades/day: {s['n']/29:.1f}")
