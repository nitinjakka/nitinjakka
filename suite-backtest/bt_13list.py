"""All-day Mode B (original spec, both directions) on the user's 13-ticker
list. Reuses the bt_20day.py engine; needs {SYM}_5m_60d.csv files present.
Result 2026-07-27: 3/13 winners (TSLA +16%, AAPL +8%, AMZN +0.2%); SPY -8.5%
(PF 0.56) re-confirming spec section 9.1 that SPY does not work.
"""
import numpy as np
from bt_20day import run_one
from bt_20orig import CUT30

SYMS = ["NVDA", "AAPL", "MSFT", "AMZN", "GOOGL", "GOOG", "AVGO", "META",
        "TSLA", "PLTR", "NFLX", "SOFI", "SPY"]

if __name__ == "__main__":
    rows = [(s, run_one(s, None), run_one(s, CUT30)) for s in SYMS]
    rows.sort(key=lambda r: r[1]["bank"], reverse=True)
    print(f"{'ticker':<8}{'trades':<8}{'win%':<7}{'PF':<7}{'ret56%':<10}"
          f"{'ret30d%'}")
    for s, f, m in rows:
        print(f"{s:<8}{f['n']:<8}{f['win']:<7.1f}{f['pf']:<7.2f}"
              f"{f['bank']-100:<+10.1f}{m['bank']-100:+.1f}")
    fb = np.array([f["bank"] for _, f, _ in rows])
    mb = np.array([m["bank"] for _, _, m in rows])
    print(f"56-sess: winners {(fb>100).sum()}/13  avg {fb.mean()-100:+.1f}%")
    print(f"30-day : winners {(mb>100).sum()}/13  avg {mb.mean()-100:+.1f}%")
