"""Grid search over strategy variants. Train on first ~2/3 sessions, test on rest."""
import numpy as np
from dataclasses import replace
from backtest import Cfg, prepare, run_all, stats, TICKERS

datasets = {t: prepare(t) for t in TICKERS}
all_dates = sorted(set(d for out in datasets.values() for d in out.date))
split = all_dates[int(len(all_dates) * 0.67)]
train = lambda d: d <= split
test = lambda d: d > split

def ev(cfg):
    tr = run_all(datasets, cfg)
    return stats([t for t in tr if train(t["date"])]), stats([t for t in tr if test(t["date"])]), tr

results = []

# ---- Stage A: ORB-only variants (memory: ORB+VWAP had the edge) ----
for stop_m in [1.5, 2.0, 2.5, 3.0]:
    for tgt_m in [0.5, 0.75, 1.0, 1.5, 2.0]:
        for stop_or in [False, True]:
            for end_min in [60, 150]:
                cfg = Cfg(entry_source="orb", atr_stop=stop_m, atr_tgt=tgt_m,
                          orb_stop_or=stop_or, orb_end_min=end_min,
                          eod_flat=True, use_bias_exit=False, time_stop_bars=78)
                tr_s, te_s, _ = ev(cfg)
                results.append(("ORB", cfg, tr_s, te_s))

# ---- Stage B: bias-flip variants ----
for score in [2, 3, 4]:
    for adxg in [20.0, 25.0, 30.0]:
        for stop_m in [1.5, 2.5]:
            for tgt_m in [0.75, 1.5]:
                for bexit in [True, False]:
                    cfg = Cfg(entry_source="bias", score_thresh=score, adx_thresh=adxg,
                              atr_stop=stop_m, atr_tgt=tgt_m, use_bias_exit=bexit,
                              eod_flat=True, time_stop_bars=30)
                    tr_s, te_s, _ = ev(cfg)
                    results.append(("BIAS", cfg, tr_s, te_s))

# ---- report: rank by train win rate among configs with enough trades & PF >= 1 ----
def fmt(s):
    return f"n={s['n']:4d} win={s['win']:5.1f}% PF={s['pf']:4.2f} avg={s['avg']:+.3f}%"

print(f"split: train <= {split}, test after\n")
usable = [r for r in results if r[2]["n"] >= 60 and r[2]["pf"] >= 1.0]
usable.sort(key=lambda r: -r[2]["win"])
print("TOP 15 by TRAIN win-rate (min 60 train trades, train PF>=1):")
for kind, cfg, tr_s, te_s in usable[:15]:
    tag = (f"{kind} stop={cfg.atr_stop} tgt={cfg.atr_tgt}"
           + (f" stopOR={cfg.orb_stop_or} end={cfg.orb_end_min}" if kind == "ORB" else
              f" score={cfg.score_thresh} adx={cfg.adx_thresh} bexit={cfg.use_bias_exit}"))
    print(f"  {tag:55s} TRAIN {fmt(tr_s)} | TEST {fmt(te_s)}")

# also show best by test-consistency (train win & test win both high)
usable2 = [r for r in usable if r[3]["n"] >= 25]
usable2.sort(key=lambda r: -(min(r[2]["win"], r[3]["win"])))
print("\nTOP 10 by MIN(train,test) win-rate (robustness):")
for kind, cfg, tr_s, te_s in usable2[:10]:
    tag = (f"{kind} stop={cfg.atr_stop} tgt={cfg.atr_tgt}"
           + (f" stopOR={cfg.orb_stop_or} end={cfg.orb_end_min}" if kind == "ORB" else
              f" score={cfg.score_thresh} adx={cfg.adx_thresh} bexit={cfg.use_bias_exit}"))
    print(f"  {tag:55s} TRAIN {fmt(tr_s)} | TEST {fmt(te_s)}")
