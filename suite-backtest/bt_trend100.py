"""Trend-filtered leveraged ETF strategy for a $100 account - daily bars.

RULE: hold TQQQ (3x Nasdaq-100) while QQQ's close > its 200-day SMA;
otherwise 100% cash. Signal evaluated at each close, executed at the NEXT
day's open (no lookahead). 0.02% cost per switch. Cash earns 0% (conservative).
Uses real TQQQ prices (fees/volatility decay included by construction).
Benchmarks: QQQ and TQQQ buy & hold. Also a 2x variant (QLD) and SPY/UPRO.
"""
import numpy as np
import pandas as pd
import yfinance as yf

START = "2011-01-01"
COST = 0.0002


def fetch(sym):
    df = yf.download(sym, start=START, interval="1d", auto_adjust=True,
                     progress=False)
    if df.columns.nlevels > 1:
        df.columns = df.columns.get_level_values(0)
    return df[["Open", "Close"]].dropna()


def strategy(signal_sym, hold_sym):
    sig = fetch(signal_sym)
    hold = fetch(hold_sym)
    idx = sig.index.intersection(hold.index)
    sig, hold = sig.reindex(idx), hold.reindex(idx)
    sma = sig.Close.rolling(200).mean()
    in_mkt = (sig.Close > sma).shift(1).fillna(False)   # decided at prior close
    # daily strategy return: hold ETF open->open? use close-to-close while in market,
    # with switch executed at open: approximate with open-to-open returns
    opn = hold.Open
    ret_oo = opn.shift(-1) / opn - 1                    # today's open -> tomorrow's open
    ret = np.where(in_mkt, ret_oo, 0.0)
    switches = in_mkt.astype(int).diff().abs().fillna(0)
    ret = ret - switches.values * COST
    eq = pd.Series((1 + pd.Series(ret, index=idx).fillna(0)).cumprod(),
                   index=idx)
    yrs = (idx[-1] - idx[0]).days / 365.25
    cagr = eq.iloc[-1] ** (1 / yrs) - 1
    dd = (eq / eq.cummax() - 1).min()
    n_switch = int(switches.sum())
    return eq, cagr * 100, dd * 100, n_switch, yrs


def bh(sym):
    df = fetch(sym)
    eq = df.Close / df.Close.iloc[0]
    yrs = (df.index[-1] - df.index[0]).days / 365.25
    cagr = eq.iloc[-1] ** (1 / yrs) - 1
    dd = (eq / eq.cummax() - 1).min()
    return eq.iloc[-1], cagr * 100, dd * 100


print(f"{'strategy':<38}{'$100 ->':>12}{'CAGR':>8}{'maxDD':>9}{'switches':>10}")
for sig, hold, label in [("QQQ", "TQQQ", "TQQQ when QQQ>200sma else cash"),
                         ("QQQ", "QLD",  "QLD (2x) when QQQ>200sma else cash"),
                         ("SPY", "UPRO", "UPRO when SPY>200sma else cash")]:
    eq, cagr, dd, ns, yrs = strategy(sig, hold)
    print(f"{label:<38}{'$' + format(100*eq.iloc[-1], ',.0f'):>12}"
          f"{cagr:>7.1f}%{dd:>8.1f}%{ns:>8} ({ns/yrs:.1f}/yr)")
    # year-by-year for the first one
    if hold == "TQQQ":
        yr_ret = eq.resample("YE").last() / eq.resample("YE").last().shift(1) - 1
        tq = eq
for sym in ["QQQ", "TQQQ", "SPY"]:
    f, cagr, dd = bh(sym)
    print(f"{'buy&hold ' + sym:<38}{'$' + format(100*f, ',.0f'):>12}"
          f"{cagr:>7.1f}%{dd:>8.1f}%")

print("\nTQQQ-trend year by year ($100 start-of-strategy compounding):")
yr = tq.resample("YE").last()
prev = 1.0
for d, v in yr.items():
    print(f"  {d.year}: {100*(v/prev-1):+7.1f}%   (cum ${100*v:,.0f})")
    prev = v

print("\nlast-5-years window (2021-07 -> 2026-07):")
five = tq[tq.index >= tq.index[-1] - pd.DateOffset(years=5)]
five = five / five.iloc[0]
dd5 = (five / five.cummax() - 1).min() * 100
cagr5 = (five.iloc[-1] ** (1 / 5) - 1) * 100
print(f"  $100 -> ${100*five.iloc[-1]:,.0f}   CAGR {cagr5:.1f}%   maxDD {dd5:.1f}%")
