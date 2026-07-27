"""Aggregate real option-premium results for the Jul 13-17 week (nearest OTM, Fri 7/17 expiry)."""
import pandas as pd
import numpy as np
from pathlib import Path

HERE = Path(__file__).parent
files = sorted((HERE / "options_results").glob("*.csv"))
df = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)
df["type"] = df["type"].str.lower()
tr = pd.read_csv(HERE / "trades_recent.csv")[["id", "pnl_underlying", "why"]].rename(columns={"why": "why_u"})
df = df.merge(tr, on="id", how="left").sort_values("id").reset_index(drop=True)

# spread penalty: buy at close+$0.03, sell at close-$0.03 (typical $0.05-0.06 round trip)
HALF = 0.03
df["pnl_adj"] = ((df.exit_prem - HALF) - (df.entry_prem + HALF)) / (df.entry_prem + HALF) * 100

def block(d, name):
    wins = (d.pnl_pct > 0).sum()
    wina = (d.pnl_adj > 0).sum()
    print(f"{name:6s} n={len(d):2d}  premium win {wins}/{len(d)} ({100*wins/len(d):.0f}%)  "
          f"avg {d.pnl_pct.mean():+6.2f}%  | spread-adj win {wina}/{len(d)} ({100*wina/len(d):.0f}%)  "
          f"avg {d.pnl_adj.mean():+6.2f}%")

print("REAL OPTION P&L — Jul 13-17 week, nearest-OTM strike, Fri 7/17 expiry")
print("=" * 78)
for t, d in df.groupby("ticker"):
    block(d, t)
print("-" * 78)
block(df, "ALL")
noSpy = df[df.ticker != "SPY"]
block(noSpy, "ex-SPY")

print(f"\nunderlying win rate same trades: {(df.pnl_underlying > 0).mean()*100:.1f}%  "
      f"(premium: {(df.pnl_pct > 0).mean()*100:.1f}%)")
print(f"sum of premium P&L (equal-weight 1 contract-$ per trade): {df.pnl_pct.sum():+.1f}%  "
      f"spread-adj: {df.pnl_adj.sum():+.1f}%")
lost_but_won = df[(df.pnl_underlying > 0) & (df.pnl_pct <= 0)]
print(f"trades that WON on underlying but LOST on premium: {len(lost_but_won)} "
      f"({', '.join(lost_but_won.ticker + ' ' + lost_but_won.id.astype(str))})")
print(f"worst trade: {df.pnl_pct.min():+.1f}% ({df.loc[df.pnl_pct.idxmin(), 'ticker']} "
      f"{df.loc[df.pnl_pct.idxmin(), 'why']})   best: {df.pnl_pct.max():+.1f}%")

print("\nfull table:")
cols = ["id", "ticker", "type", "strike", "why", "entry_prem", "exit_prem", "pnl_pct", "pnl_adj", "pnl_underlying"]
print(df[cols].to_string(index=False, float_format=lambda x: f"{x:+.2f}" if abs(x) < 1000 else f"{x:.0f}"))
df.to_csv(HERE / "options_results" / "ALL_aggregated.csv", index=False)
