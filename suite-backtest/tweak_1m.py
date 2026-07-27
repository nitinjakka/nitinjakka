"""Validate the two new signal families the user asked for:
   pullback (with-trend VWAP/EMA9 re-cross) and srfade (rejection at pivot S/R),
   plus the combined breakout+pullback mode."""
import numpy as np
from dataclasses import replace
from collections import Counter
from bt1m import Cfg1, prepare1m, run_all, stats, TICKERS

datasets = {t: prepare1m(t) for t in TICKERS}
all_dates = sorted(set(d for out in datasets.values() for d in out.date))
split = all_dates[int(len(all_dates) * 0.66)]

def ev(name, cfg, detail=False):
    tr = run_all(datasets, cfg)
    a = stats(tr); te = stats([x for x in tr if x["date"] > split])
    print(f"{name:46s} ALL n={a['n']:4d} {a['win']:5.1f}% PF={a['pf']:4.2f} avg={a['avg']:+.3f} | "
          f"TEST n={te['n']:3d} {te['win']:5.1f}% PF={te['pf']:4.2f}")
    if detail:
        for s, nm in [(3, "breakout"), (4, "pullback"), (5, "srfade")]:
            d = [x for x in tr if x["src"] == s]
            if d:
                ds = stats(d)
                print(f"    src {nm:9s} n={ds['n']:4d} win={ds['win']:5.1f}% PF={ds['pf']:4.2f} avg={ds['avg']:+.3f}")
    return tr

B = Cfg1(entry_cutoff_min=360, max_trades_day=10)

print("== pullback (with-trend VWAP+EMA9 recross, swing stop) ==")
for tgt in [0.5, 0.75, 1.0, 1.5]:
    ev(f"pullback tgt{tgt}", replace(B, entry_source="pullback", atr_tgt=tgt))

print("\n== srfade (rejection at pivot S/R) ==")
for tgt in [0.5, 0.75, 1.0]:
    ev(f"srfade tgt{tgt}", replace(B, entry_source="srfade", atr_tgt=tgt))

print("\n== combined: breakout + pullback ==")
for tgt in [0.5, 0.75]:
    ev(f"db+pb tgt{tgt}", replace(B, entry_source="db+pb", atr_tgt=tgt), detail=True)
