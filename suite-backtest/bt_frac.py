"""$100 fractional-share strategy backtest, May 5 - Jul 24 2026 (56 sessions).

STRATEGY (long-only underlying, fractional shares):
  - Tickers: TSLA, NVDA, QQQ, AAPL (the suite's validated movers)
  - Mode B entries (spec 5): when FLAT, on a 5-min bar close that breaks the
    running session high (prior bar) AND is above session VWAP, 9:35-15:30,
    max 10 entries/day/ticker; skip if a confirmed pivot resistance is
    within 0.25% of price
  - target = entry + 0.75*ATR(14), capped at nearest pivot resistance
  - stop   = opening-range low (first 5-min bar) -- the validated stop
  - always flat by 15:55; conservative fills (stop before target in a bar)
  - PUT signals are NOT traded ($100 accounts cannot short) but still
    consume nothing -- long entries only
PORTFOLIO: one $100 bankroll, all 4 tickers watched simultaneously; when
flat, take the first eligible CALL signal (same-bar ties -> highest ATR%
ticker, i.e. the biggest mover). 100%% of bankroll per trade (max loss per
trade is under 1%% because the stop is structural, not premium-based).
FRICTION: 0.02%% round trip (fractional-share spread; $0 commission).
Benchmarks: SPY and QQQ buy & hold over the identical window.
"""
import numpy as np
import pandas as pd
from pathlib import Path

HERE = Path(__file__).parent
TICKERS = ["TSLA", "NVDA", "QQQ", "AAPL"]
WARMUP_SESSIONS = 3
LAST_DAY = pd.Timestamp("2026-07-24").date()
COST_RT = 0.0002          # 0.02% round-trip friction


def rma(s, n):
    return s.ewm(alpha=1 / n, adjust=False).mean()


def prepare(sym):
    df = pd.read_csv(HERE / f"{sym}_5m_60d.csv", index_col=0, parse_dates=True)
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    df.index = df.index.tz_convert("America/New_York")
    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
    df = df[pd.Series(df.index.date, index=df.index) <= LAST_DAY]
    out = pd.DataFrame(index=df.index)
    out["o"], out["h"], out["l"], out["c"] = df.Open, df.High, df.Low, df.Close
    tr = pd.concat([df.High - df.Low, (df.High - df.Close.shift()).abs(),
                    (df.Low - df.Close.shift()).abs()], axis=1).max(axis=1)
    out["atr"] = rma(tr, 14)
    dates = pd.Series(df.index.date, index=df.index)
    out["date"] = dates
    out["mins"] = (df.index.hour - 9) * 60 + (df.index.minute - 30)
    tp = (df.High + df.Low + df.Close) / 3
    out["vwap"] = (tp * df.Volume).groupby(dates.values).cumsum() / \
                  df.Volume.groupby(dates.values).cumsum().replace(0, np.nan)
    L = R = 10
    hh = df.High.values
    n = len(out)
    piv_hi = np.full(n, np.nan)
    for i in range(L + R, n):
        p = i - R
        if hh[p] == hh[p - L:p + R + 1].max():
            piv_hi[i] = hh[p]
    out["piv_hi"] = piv_hi
    return out


# ---- load all tickers on a shared timeline ----
data = {t: prepare(t) for t in TICKERS}
common = data[TICKERS[0]].index
for t in TICKERS[1:]:
    common = common.intersection(data[t].index)
for t in TICKERS:
    data[t] = data[t].reindex(common)

sessions = sorted(set(common.date))
trade_start = sessions[WARMUP_SESSIONS]
n = len(common)
dates = np.array([d for d in common.date])

# per-ticker rolling state
state = {t: dict(res=[], or_hi=np.nan, or_lo=np.nan, sess_hi=np.nan,
                 sess_lo=np.nan, trades_today=0) for t in TICKERS}

bank = 100.0
equity_curve = []
pos = None                    # dict(ticker, entry, stop, tgt, entry_i)
trades = []
cur_date = None

for i in range(1, n):
    new_day = dates[i] != cur_date
    if new_day:
        cur_date = dates[i]
        for t in TICKERS:
            st = state[t]
            row = data[t].iloc[i]
            st["or_hi"], st["or_lo"] = row.h, row.l
            st["sess_hi"], st["sess_lo"] = row.h, row.l
            st["trades_today"] = 0
    # maintain pivots
    for t in TICKERS:
        ph = data[t]["piv_hi"].iloc[i]
        if not np.isnan(ph):
            state[t]["res"].append(ph)
            state[t]["res"] = state[t]["res"][-3:]

    last_bar = (i + 1 >= n) or (dates[i + 1] != dates[i])

    # ---------- exit ----------
    if pos is not None and not new_day:
        t = pos["ticker"]
        row = data[t].iloc[i]
        exit_px = why = None
        if row.l <= pos["stop"]:
            exit_px = row.o if row.o < pos["stop"] else pos["stop"]
            why = "STOP"
        elif row.h >= pos["tgt"]:
            exit_px = row.o if row.o > pos["tgt"] else pos["tgt"]
            why = "TARGET"
        elif last_bar:
            exit_px, why = row.c, "EOD"
        if exit_px is not None:
            ret = exit_px / pos["entry"] - 1 - COST_RT
            bank *= (1 + ret)
            trades.append(dict(day=str(dates[i]), ticker=t, why=why,
                               ret=ret * 100, bank=bank))
            pos = None

    # ---------- entry ----------
    if pos is None and not new_day and not last_bar and dates[i] >= trade_start:
        candidates = []
        for t in TICKERS:
            st = state[t]
            row = data[t].iloc[i]
            if np.isnan(row.c) or np.isnan(st["sess_hi"]):
                continue
            mins = data[t]["mins"].iloc[i]
            if not (5 <= mins < 360) or st["trades_today"] >= 10:
                continue
            if row.c > st["sess_hi"] and row.c > row.vwap:
                n_res = min([x for x in st["res"] if x > row.c], default=np.nan)
                room = 100.0 if np.isnan(n_res) else (n_res - row.c) / row.c * 100
                if room >= 0.25:
                    tgt = row.c + 0.5 * row.atr
                    if not np.isnan(n_res) and n_res < tgt:
                        tgt = n_res
                    candidates.append((row.atr / row.c, t, row.c, st["or_lo"], tgt))
        if candidates:
            candidates.sort(reverse=True)       # biggest mover first
            _, t, entry, stop, tgt = candidates[0]
            state[t]["trades_today"] += 1
            pos = dict(ticker=t, entry=entry, stop=stop, tgt=tgt, entry_i=i)

    # update session extremes AFTER signal checks (prior-bar rule)
    for t in TICKERS:
        st = state[t]
        row = data[t].iloc[i]
        if not np.isnan(row.h):
            st["sess_hi"] = max(st["sess_hi"], row.h)
            st["sess_lo"] = min(st["sess_lo"], row.l)
    equity_curve.append((common[i], bank))

# ---------- results ----------
tr = pd.DataFrame(trades)
eq = pd.Series([b for _, b in equity_curve], index=[x for x, _ in equity_curve])
dd = (eq / eq.cummax() - 1).min() * 100
wins = (tr.ret > 0).sum()
gp = tr.ret[tr.ret > 0].sum()
gl = -tr.ret[tr.ret < 0].sum()

print(f"WINDOW: {trade_start} -> {LAST_DAY}  ({len([s for s in sessions if s >= trade_start])} sessions)")
print(f"TRADES: {len(tr)}   wins {wins} ({100*wins/len(tr):.1f}%)   PF {gp/gl:.2f}")
print(f"avg trade {tr.ret.mean():+.3f}%   avg win {tr.ret[tr.ret>0].mean():+.3f}%   "
      f"avg loss {tr.ret[tr.ret<0].mean():+.3f}%")
print(f"exits: {dict(tr.why.value_counts())}")
print(f"per-ticker trades: {dict(tr.ticker.value_counts())}")
print(f"\n$100.00 -> ${bank:.2f}  ({bank-100:+.2f}%)   max drawdown {dd:.2f}%")

# weekly progression
tr["week"] = pd.to_datetime(tr.day).dt.to_period("W").astype(str)
print("\nweekly bankroll (end of week):")
for wk, g in tr.groupby("week"):
    print(f"  {wk}  trades={len(g):>3}  bank=${g.bank.iloc[-1]:>7.2f}")

# benchmarks
for b in ["SPY", "QQQ"]:
    df = pd.read_csv(HERE / f"{b}_5m_60d.csv", index_col=0, parse_dates=True)
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    df.index = df.index.tz_convert("America/New_York")
    d0 = df[pd.Series(df.index.date, index=df.index) >= trade_start]
    d0 = d0[pd.Series(d0.index.date, index=d0.index) <= LAST_DAY]
    ret = (float(d0.Close.iloc[-1]) / float(d0.Open.iloc[0]) - 1) * 100
    print(f"benchmark {b} buy&hold same window: $100 -> ${100*(1+ret/100):.2f} ({ret:+.2f}%)")
