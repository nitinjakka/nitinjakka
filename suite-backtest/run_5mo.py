"""Merge Robinhood (Feb-Apr) + Yahoo (Apr-Jul) 5-min data, run final config over ~5 months.

The Feb 18 - Apr 21 window is PURE out-of-sample: it predates every session used
to tune the strategy (tuning used Apr 22 - Jun 18).
"""
import numpy as np
import pandas as pd
from pathlib import Path
from collections import Counter
from backtest import Cfg, prepare, run, stats, TICKERS

HERE = Path(__file__).parent
RH, YH, EXT = HERE / "data_rh", HERE / "data", HERE / "data_ext"
EXT.mkdir(exist_ok=True)

FINAL = Cfg(entry_source="orb", orb_stop_or=True, atr_stop=3.0, atr_tgt=0.5,
            orb_end_min=150, eod_flat=True, use_bias_exit=False, time_stop_bars=78)

# ---- merge ----
for t in TICKERS:
    parts = sorted(RH.glob(f"{t}_rh_*.csv"))
    assert parts, f"missing RH files for {t}"
    rh = pd.concat([pd.read_csv(p) for p in parts])
    rh["ts"] = pd.to_datetime(rh["begins_at_utc"], utc=True).dt.tz_convert("America/New_York")
    rh = rh.set_index("ts").sort_index()
    rh = rh.rename(columns={"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"})
    rh = rh[["Open", "High", "Low", "Close", "Volume"]]
    rh = rh[(rh.index.time >= pd.Timestamp("09:30").time()) & (rh.index.time < pd.Timestamp("16:00").time())]

    yh = pd.read_csv(YH / f"{t}_5m.csv", index_col=0)
    yh.index = pd.to_datetime(yh.index, utc=True).tz_convert("America/New_York")

    cutoff = yh.index[0]
    rh = rh[rh.index < cutoff]                      # avoid overlap; Yahoo wins from Apr 22 on
    merged = pd.concat([rh, yh]).sort_index()
    merged = merged[~merged.index.duplicated(keep="last")]
    merged.to_csv(EXT / f"{t}_5m.csv")
    days = sorted(set(merged.index.date))
    print(f"{t}: RH {len(rh)} bars + YH {len(yh)} bars -> {len(merged)} bars, "
          f"{len(days)} sessions, {days[0]} -> {days[-1]}")

# sanity: seam continuity (RH last close vs YH first open should be same scale)
for t in TICKERS:
    m = pd.read_csv(EXT / f"{t}_5m.csv", index_col=0)
    m.index = pd.to_datetime(m.index, utc=True).tz_convert("America/New_York")
    cutoff = pd.Timestamp("2026-04-22", tz="America/New_York")
    pre, post = m[m.index < cutoff], m[m.index >= cutoff]
    if len(pre) and len(post):
        jump = abs(post.Open.iloc[0] / pre.Close.iloc[-1] - 1) * 100
        flag = "  <-- CHECK (possible split/adjustment mismatch)" if jump > 8 else ""
        print(f"{t}: seam gap RH->YH = {jump:.2f}%{flag}")

# ---- run ----
def fmt(s):
    return f"n={s['n']:4d}  win={s['win']:5.1f}%  PF={s['pf']:4.2f}  avg/trade={s['avg']:+.3f}%"

all_tr = []
for t in TICKERS:
    out = prepare(t, data_dir=EXT)
    tr = run(out, FINAL)
    for x in tr:
        x["ticker"] = t
    all_tr += tr

d0 = pd.Timestamp("2026-04-22").date()   # tuning data started here
d1 = pd.Timestamp("2026-06-19").date()   # train/test split within tuning data

print("\n================ FINAL CONFIG over full merged history ================")
print(f"FULL PERIOD            : {fmt(stats(all_tr))}")
print(f"PRE-TUNING OOS (<4/22) : {fmt(stats([x for x in all_tr if x['date'] < d0]))}")
print(f"TUNING WINDOW (4/22-6/18): {fmt(stats([x for x in all_tr if d0 <= x['date'] <= d1]))}")
print(f"HOLDOUT (>6/18)        : {fmt(stats([x for x in all_tr if x['date'] > d1]))}")

print("\nper ticker (full period):")
for t in TICKERS:
    print(f"  {t:5s} {fmt(stats([x for x in all_tr if x['ticker'] == t]))}")

pnl = np.array([x["pnl"] for x in all_tr])
print(f"\ncumulative: {pnl.sum():+.2f}%  avg win {pnl[pnl>0].mean():+.3f}%  avg loss {pnl[pnl<0].mean():+.3f}%")
print(f"exits: {dict(Counter(x['why'] for x in all_tr))}")

df = pd.DataFrame(all_tr)
df["month"] = pd.to_datetime(df["date"].astype(str)).dt.to_period("M").astype(str)
mo = df.groupby("month").agg(n=("pnl", "size"), win=("pnl", lambda x: 100 * (x > 0).mean()), tot=("pnl", "sum"))
print("\nmonth      n   win%   sum%")
for m_, r in mo.iterrows():
    print(f"{m_}  {int(r['n']):3d}  {r['win']:5.1f}  {r['tot']:+6.2f}")
