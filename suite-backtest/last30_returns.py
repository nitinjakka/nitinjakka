"""Last-30-calendar-days % return for both $100 strategies + benchmarks."""
import numpy as np
import pandas as pd
import yfinance as yf

CUT = pd.Timestamp.now(tz="America/New_York") - pd.Timedelta(days=30)

# ---- 1) TQQQ trend strategy (QQQ > 200sma -> TQQQ else cash) ----
qqq = yf.download("QQQ", start="2025-06-01", interval="1d", auto_adjust=True,
                  progress=False)
tqqq = yf.download("TQQQ", start="2025-06-01", interval="1d", auto_adjust=True,
                   progress=False)
for d in (qqq, tqqq):
    if d.columns.nlevels > 1:
        d.columns = d.columns.get_level_values(0)
idx = qqq.index.intersection(tqqq.index)
qqq, tqqq = qqq.reindex(idx), tqqq.reindex(idx)
sma = qqq.Close.rolling(200).mean()
in_mkt = (qqq.Close > sma).shift(1).fillna(False)
ret = np.where(in_mkt, tqqq.Open.shift(-1) / tqqq.Open - 1, 0.0)
eq = pd.Series((1 + pd.Series(ret, index=idx).fillna(0)).cumprod(), index=idx)
eq.index = eq.index.tz_localize("America/New_York")
w = eq[eq.index >= CUT]
days_in = int(in_mkt[in_mkt.index.tz_localize('America/New_York') >= CUT].sum())
print(f"TQQQ-trend strategy last 30 days : {(w.iloc[-1]/w.iloc[0]-1)*100:+.2f}%  "
      f"(in market {days_in}/{len(w)} sessions)")

# ---- 2) intraday fractional Mode B long-only (equity curve slice) ----
import io, contextlib
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    import bt_frac
feq = pd.Series([b for _, b in bt_frac.equity_curve],
                index=[x for x, _ in bt_frac.equity_curve])
fw = feq[feq.index >= CUT]
ftr = pd.DataFrame(bt_frac.trades)
ftr30 = ftr[pd.to_datetime(ftr.day).dt.tz_localize("America/New_York") >= CUT]
w30 = (ftr30.ret > 0).sum()
print(f"Intraday fractional (Mode B long) : {(fw.iloc[-1]/fw.iloc[0]-1)*100:+.2f}%  "
      f"({len(ftr30)} trades, {w30}W/{len(ftr30)-w30}L, win {100*w30/len(ftr30):.0f}%)")

# ---- benchmarks ----
for sym in ["SPY", "QQQ", "TQQQ"]:
    df = yf.download(sym, period="45d", interval="1d", auto_adjust=True,
                     progress=False)
    if df.columns.nlevels > 1:
        df.columns = df.columns.get_level_values(0)
    df.index = df.index.tz_localize("America/New_York")
    dw = df[df.index >= CUT]
    print(f"benchmark {sym:<5} buy&hold          : "
          f"{(float(dw.Close.iloc[-1])/float(dw.Close.iloc[0])-1)*100:+.2f}%")
