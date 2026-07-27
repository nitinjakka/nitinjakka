"""Sweep: Mode A vs B, target 0.5 vs 0.75 ATR - $100 fractional portfolio."""
import numpy as np
import pandas as pd
from pathlib import Path

HERE = Path(__file__).parent
TICKERS = ["TSLA", "NVDA", "QQQ", "AAPL"]
WARMUP_SESSIONS = 3
LAST_DAY = pd.Timestamp("2026-07-24").date()
COST_RT = 0.0002


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


def run(mode, tgt_mult):
    state = {t: dict(res=[], or_hi=np.nan, or_lo=np.nan, sess_hi=np.nan,
                     sess_lo=np.nan, trades_today=0, orb_done=False)
             for t in TICKERS}
    bank = 100.0
    pos = None
    trades = []
    cur_date = None
    peak, maxdd = 100.0, 0.0
    win_end = 150 if mode == "A" else 360
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
                st["orb_done"] = False
        for t in TICKERS:
            ph = data[t]["piv_hi"].iloc[i]
            if not np.isnan(ph):
                state[t]["res"].append(ph)
                state[t]["res"] = state[t]["res"][-3:]
        last_bar = (i + 1 >= n) or (dates[i + 1] != dates[i])
        if pos is not None and not new_day:
            t = pos["ticker"]
            row = data[t].iloc[i]
            exit_px = None
            if row.l <= pos["stop"]:
                exit_px = row.o if row.o < pos["stop"] else pos["stop"]
            elif row.h >= pos["tgt"]:
                exit_px = row.o if row.o > pos["tgt"] else pos["tgt"]
            elif last_bar:
                exit_px = row.c
            if exit_px is not None:
                ret = exit_px / pos["entry"] - 1 - COST_RT
                bank *= 1 + ret
                trades.append(ret * 100)
                peak = max(peak, bank)
                maxdd = min(maxdd, bank / peak - 1)
                pos = None
        if pos is None and not new_day and not last_bar and dates[i] >= trade_start:
            cands = []
            for t in TICKERS:
                st = state[t]
                row = data[t].iloc[i]
                if np.isnan(row.c) or np.isnan(st["sess_hi"]):
                    continue
                mins = data[t]["mins"].iloc[i]
                if not (5 <= mins < win_end):
                    continue
                if mode == "A":
                    if st["orb_done"]:
                        continue
                    trig_hi, trig_lo = st["or_hi"], st["or_lo"]
                else:
                    if st["trades_today"] >= 10:
                        continue
                    trig_hi, trig_lo = st["sess_hi"], st["sess_lo"]
                up = row.c > trig_hi and row.c > row.vwap
                dn = row.c < trig_lo and row.c < row.vwap
                if mode == "A" and (up or dn):
                    st["orb_done"] = True
                if up:
                    n_res = min([x for x in st["res"] if x > row.c], default=np.nan)
                    room = 100.0 if np.isnan(n_res) else (n_res - row.c) / row.c * 100
                    if room >= 0.25:
                        tgt = row.c + tgt_mult * row.atr
                        if not np.isnan(n_res) and n_res < tgt:
                            tgt = n_res
                        cands.append((row.atr / row.c, t, row.c, st["or_lo"], tgt))
            if cands:
                cands.sort(reverse=True)
                _, t, entry, stop, tgt = cands[0]
                state[t]["trades_today"] += 1
                pos = dict(ticker=t, entry=entry, stop=stop, tgt=tgt)
        for t in TICKERS:
            st = state[t]
            row = data[t].iloc[i]
            if not np.isnan(row.h):
                st["sess_hi"] = max(st["sess_hi"], row.h)
                st["sess_lo"] = min(st["sess_lo"], row.l)
    tr = np.array(trades)
    wins = (tr > 0).sum()
    gp, gl = tr[tr > 0].sum(), -tr[tr < 0].sum()
    return (len(tr), 100 * wins / len(tr) if len(tr) else 0,
            gp / gl if gl else np.inf, bank, maxdd * 100)


print("mode  tgt   trades  win%    PF     final$    maxDD%")
for mode in ["A", "B"]:
    for tm in [0.5, 0.75]:
        nt, w, pf, bank, dd = run(mode, tm)
        print(f"{mode:<6}{tm:<6}{nt:<8}{w:<8.1f}{pf:<7.2f}{bank:<10.2f}{dd:.2f}")
