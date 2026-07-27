"""Refine the winning ORB config: bias filter, target size; per-ticker robustness."""
import numpy as np
from dataclasses import replace
from collections import Counter
from backtest import Cfg, prepare, run_all, stats, TICKERS

datasets = {t: prepare(t) for t in TICKERS}
all_dates = sorted(set(d for out in datasets.values() for d in out.date))
split = all_dates[int(len(all_dates) * 0.67)]

BASE = Cfg(entry_source="orb", orb_stop_or=True, atr_stop=3.0, atr_tgt=0.5,
           orb_end_min=150, eod_flat=True, use_bias_exit=False, time_stop_bars=78)

def fmt(s):
    return f"n={s['n']:4d} win={s['win']:5.1f}% PF={s['pf']:4.2f} avg={s['avg']:+.3f}%"

variants = {
    "base (stopOR, tgt 0.5)":            BASE,
    "base + bias soft filter":           replace(BASE, orb_bias_filter="soft"),
    "base + bias hard filter":           replace(BASE, orb_bias_filter="hard"),
    "tgt 0.4":                           replace(BASE, atr_tgt=0.4),
    "tgt 0.6":                           replace(BASE, atr_tgt=0.6),
    "tgt 0.75":                          replace(BASE, atr_tgt=0.75),
    "tgt 0.5 + soft + noSRfilter":       replace(BASE, orb_bias_filter="soft", use_sr_filter=False),
    "ATRstop3 tgt0.5 (no stopOR)":       replace(BASE, orb_stop_or=False),
    "ATRstop3 tgt0.5 + soft":            replace(BASE, orb_stop_or=False, orb_bias_filter="soft"),
    "stopOR tgt0.5 end=90":              replace(BASE, orb_end_min=90),
}

for name, cfg in variants.items():
    tr = run_all(datasets, cfg)
    tr_s = stats([t for t in tr if t["date"] <= split])
    te_s = stats([t for t in tr if t["date"] > split])
    print(f"{name:32s} TRAIN {fmt(tr_s)} | TEST {fmt(te_s)}")

# ---- deep dive on the two leading candidates ----
for name in ["base + bias soft filter", "base (stopOR, tgt 0.5)"]:
    cfg = variants[name]
    tr = run_all(datasets, cfg)
    print(f"\n=== {name} — per ticker (full 60 sessions) ===")
    for t in TICKERS:
        s = stats([x for x in tr if x["ticker"] == t])
        print(f"  {t:5s} {fmt(s)}")
    s_all = stats(tr)
    print(f"  ALL   {fmt(s_all)}   exits: {dict(Counter(x['why'] for x in tr))}")
    dirs = Counter(x["dir"] for x in tr)
    print(f"  direction: calls={dirs.get(1,0)} puts={dirs.get(-1,0)}")
