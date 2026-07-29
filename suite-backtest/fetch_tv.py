"""Fetch deep 5-min history from TradingView via tvdatafeed.

Anonymous: ~5,000 bars (~3 months). With a TradingView login: up to
~20,000 bars (~1 year of 5-min data, more on higher plans).

Setup (optional, for the deep history):
  Add to E:\\Tradeing\\robinhood\\.env  (edit the file yourself):
      TV_USERNAME=your_tradingview_username
      TV_PASSWORD=your_tradingview_password

Usage:
  python fetch_tv.py TSLA AAPL ORCL          # specific symbols
  python fetch_tv.py                          # default shortlist
Writes {SYM}_5m_tv.csv next to this script.
Install: pip install "git+https://github.com/rongardF/tvDatafeed"
"""
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from tvDatafeed import Interval, TvDatafeed

HERE = Path(__file__).parent
DEFAULT = ["TSLA", "AAPL", "ORCL", "KLAC", "PANW", "SMR", "U", "NVDA",
           "AMZN", "CRWD", "SMCI"]
EXCHANGES = {"TSLA": "NASDAQ", "AAPL": "NASDAQ", "NVDA": "NASDAQ",
             "AMZN": "NASDAQ", "KLAC": "NASDAQ", "PANW": "NASDAQ",
             "SMCI": "NASDAQ", "CRWD": "NASDAQ", "ORCL": "NYSE",
             "SMR": "NYSE", "U": "NYSE"}

load_dotenv(r"E:\Tradeing\robinhood\.env")
user = os.getenv("TV_USERNAME")
pw = os.getenv("TV_PASSWORD")
if user and pw:
    print("logging in with TradingView account (deep history)...")
    tv = TvDatafeed(user, pw)
else:
    print("no TV_USERNAME/TV_PASSWORD in .env -> anonymous (~5000 bars)")
    tv = TvDatafeed()

syms = sys.argv[1:] or DEFAULT
for s in syms:
    exch = EXCHANGES.get(s, "NASDAQ")
    try:
        df = tv.get_hist(s, exch, interval=Interval.in_5_minute, n_bars=20000)
        if df is None or not len(df):
            print(f"{s}: NO DATA (check exchange; tried {exch})")
            continue
        path = HERE / f"{s}_5m_tv.csv"
        df.to_csv(path)
        print(f"{s}: {len(df)} bars  {df.index[0]} -> {df.index[-1]}")
    except Exception as e:
        print(f"{s}: FAILED {e!r}")
    time.sleep(1)          # be gentle
