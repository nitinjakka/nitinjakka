"""Emit Jul 13-17 trade lists from the final 1-min configs, for option pricing."""
import pandas as pd
from dataclasses import replace
from bt1m import Cfg1, prepare1m, run_all, TICKERS

datasets = {t: prepare1m(t) for t in TICKERS}

FIN_ORB = Cfg1(entry_source="orb", orb_stop_or=True, atr_tgt=0.5)
FIN_DAY = Cfg1(entry_source="daybreak", entry_cutoff_min=360, orb_stop_or=True, atr_tgt=0.75)

def dump(cfg, name):
    tr = [t for t in run_all(datasets, cfg) if str(t["date"]) >= "2026-07-13"]
    df = pd.DataFrame(tr).sort_values("entry_ts").reset_index(drop=True)
    df.insert(0, "id", df.index)
    df["entry_utc"] = pd.to_datetime(df.entry_ts.astype(str)).dt.tz_convert("UTC").dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    df["exit_utc"] = pd.to_datetime(df.exit_ts.astype(str)).dt.tz_convert("UTC").dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    cols = ["id", "ticker", "dir", "entry_utc", "exit_utc", "entry_px", "exit_px", "why", "pnl"]
    df[cols].to_csv(f"trades_1m_{name}.csv", index=False)
    print(f"--- {name}: {len(df)} trades ---")
    print(df[cols].to_string(index=False))
    return df

dump(FIN_ORB, "orb")
day = dump(FIN_DAY, "daybreak")
# sample 12 daybreak trades stratified across days/tickers for premium spot-check
samp = day.groupby(day.entry_utc.str[:10]).apply(lambda g: g.sample(min(3, len(g)), random_state=7), include_groups=False)
print(f"\nsampled {len(samp)} daybreak trades for option pricing (ids): {sorted(samp.id.tolist())}")
