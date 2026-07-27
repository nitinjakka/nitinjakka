"""Round 2: strict pullback filters + stop geometry; pick the final combined mode."""
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
    print(f"{name:48s} ALL n={a['n']:4d} {a['win']:5.1f}% PF={a['pf']:4.2f} avg={a['avg']:+.3f} | "
          f"TEST n={te['n']:3d} {te['win']:5.1f}% PF={te['pf']:4.2f}")
    if detail:
        for s, nm in [(3, "breakout"), (4, "pullback")]:
            d = [x for x in tr if x["src"] == s]
            if d:
                ds = stats(d); dte = stats([x for x in d if x["date"] > split])
                print(f"    {nm:9s} n={ds['n']:4d} win={ds['win']:5.1f}% PF={ds['pf']:4.2f} avg={ds['avg']:+.3f} | test {dte['win']:5.1f}% PF={dte['pf']:4.2f}")
    return tr

B = Cfg1(entry_cutoff_min=360, max_trades_day=10)

print("== strict pullback (dip to EMA21, trend-aligned) ==")
for tgt in [0.4, 0.5, 0.75]:
    for stp in [0.0, 1.5, 2.5]:
        ev(f"pb_strict tgt{tgt} stop={'swing' if stp==0 else str(stp)+'ATR'}",
           replace(B, entry_source="pullback", pb_strict=True, atr_tgt=tgt, pb_stop_atr=stp))

print("\n== combined breakout + strict pullback ==")
for tgt in [0.5, 0.75]:
    for stp in [1.5, 2.5]:
        ev(f"db+pb_strict tgt{tgt} pbstop={stp}ATR",
           replace(B, entry_source="db+pb", pb_strict=True, atr_tgt=tgt, pb_stop_atr=stp), detail=True)

# per-ticker for the leading candidate
print("\n== per-ticker: db+pb_strict tgt0.75 pbstop2.5 ==")
FIN = replace(B, entry_source="db+pb", pb_strict=True, atr_tgt=0.75, pb_stop_atr=2.5)
tr = run_all(datasets, FIN)
for t in TICKERS:
    s = stats([x for x in tr if x["ticker"] == t])
    print(f"  {t:5s} n={s['n']:4d} win={s['win']:5.1f}% PF={s['pf']:4.2f} avg={s['avg']:+.3f}%")
s = stats(tr); ex = stats([x for x in tr if x["ticker"] != "SPY"])
print(f"  ALL   n={s['n']:4d} win={s['win']:5.1f}% PF={s['pf']:4.2f}  |  exSPY n={ex['n']} win={ex['win']:5.1f}% PF={ex['pf']:4.2f}")
print(f"  exits: {dict(Counter(x['why'] for x in tr))}")
