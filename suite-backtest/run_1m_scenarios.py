"""Merge 1-min halves and run ALL previously-tested scenarios + new all-day modes on 1-min bars."""
import numpy as np
import pandas as pd
from pathlib import Path
from dataclasses import replace
from collections import Counter
from bt1m import Cfg1, prepare1m, run_all, stats, TICKERS, D1M

# ---- merge h1+h2 -> {T}_1m.csv ----
for t in TICKERS:
    parts = [pd.read_csv(D1M / f"{t}_{h}.csv") for h in ("h1", "h2") if (D1M / f"{t}_{h}.csv").exists()]
    df = pd.concat(parts)
    df["ts"] = pd.to_datetime(df["begins_at_utc"], utc=True)
    df = df.drop_duplicates("ts").sort_values("ts").set_index("ts")[["open", "high", "low", "close", "volume"]]
    df.to_csv(D1M / f"{t}_1m.csv")
    days = sorted(set(df.index.date))
    print(f"{t}: {len(df)} bars, {len(days)} sessions, {days[0]} -> {days[-1]}")

datasets = {t: prepare1m(t) for t in TICKERS}
all_dates = sorted(set(d for out in datasets.values() for d in out.date))
split = all_dates[int(len(all_dates) * 0.66)]
print(f"\nsessions {len(all_dates)}, train <= {split}, test after\n")

def ev(name, cfg):
    tr = run_all(datasets, cfg)
    a = stats(tr); trn = stats([x for x in tr if x["date"] <= split]); te = stats([x for x in tr if x["date"] > split])
    print(f"{name:44s} ALL n={a['n']:4d} {a['win']:5.1f}% PF={a['pf']:4.2f} | "
          f"TRAIN {trn['win']:5.1f}% PF={trn['pf']:4.2f} | TEST n={te['n']:3d} {te['win']:5.1f}% PF={te['pf']:4.2f}")
    return tr

print("== previously-tested scenarios, now on 1-min bars ==")
ev("baseline: old defaults (both, biasexit, ATR1.5/2)",
   Cfg1(entry_source="both", atr_stop=1.5, atr_tgt=2.0, orb_stop_or=False,
        use_bias_exit=True, time_stop_bars=30, eod_flat=False, score_thresh=2))
ev("bias-only best-5m (score2 adx30 s2.5/t0.75 eod)",
   Cfg1(entry_source="bias", score_thresh=2, adx_thresh=30, atr_stop=2.5, atr_tgt=0.75,
        orb_stop_or=False, use_bias_exit=False, time_stop_bars=150))
final5m = Cfg1(entry_source="orb", orb_stop_or=True, atr_stop=3.0, atr_tgt=0.5)
tr_final = ev("FINAL-5m config on 1m (orb stopOR tgt0.5 eod)", final5m)

print("\n== ORB variants on 1m ==")
for tgt in [0.4, 0.5, 0.6, 0.75, 1.0]:
    ev(f"orb stopOR tgt{tgt}", replace(final5m, atr_tgt=tgt))
ev("orb ATRstop3 tgt0.5 (no stopOR)", replace(final5m, orb_stop_or=False))
ev("orb stopOR tgt0.5 end=60", replace(final5m, orb_end_min=60))
ev("orb stopOR tgt0.5 noVWAP", replace(final5m, orb_use_vwap=False))

print("\n== all-day modes (request #4) ==")
for mx in [2, 3, 5, 10]:
    ev(f"orb_rearm max{mx}/day tgt0.5", replace(final5m, entry_source="orb_rearm", max_trades_day=mx))
for cut in [150, 240, 360]:
    ev(f"daybreak cutoff{cut} tgt0.5", replace(final5m, entry_source="daybreak", entry_cutoff_min=cut))
ev("daybreak cutoff360 tgt0.75", replace(final5m, entry_source="daybreak", entry_cutoff_min=360, atr_tgt=0.75))
ev("daybreak cutoff360 ATRstop2 tgt0.5",
   replace(final5m, entry_source="daybreak", entry_cutoff_min=360, orb_stop_or=False, atr_stop=2.0))
