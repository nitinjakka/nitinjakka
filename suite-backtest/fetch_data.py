"""Fetch real 5-min intraday data for backtesting the Combined Suite logic."""
import yfinance as yf
import pandas as pd
from pathlib import Path

OUT = Path(__file__).parent / "data"
OUT.mkdir(exist_ok=True)

TICKERS = ["NVDA", "SPY", "QQQ", "TSLA", "AAPL"]

for t in TICKERS:
    df = yf.download(t, period="60d", interval="5m", auto_adjust=False, progress=False)
    if df.empty:
        print(f"{t}: EMPTY")
        continue
    # yfinance may return MultiIndex columns for single ticker; flatten
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
    df.index = df.index.tz_convert("America/New_York")
    # regular session only
    df = df[(df.index.time >= pd.Timestamp("09:30").time()) & (df.index.time < pd.Timestamp("16:00").time())]
    df.to_csv(OUT / f"{t}_5m.csv")
    days = len(set(df.index.date))
    print(f"{t}: {len(df)} bars, {days} sessions, {df.index[0].date()} -> {df.index[-1].date()}")
