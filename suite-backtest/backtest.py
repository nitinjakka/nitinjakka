"""Backtest of the Combined Suite (combined-suite.pine) trade engine on real 5-min data.

Faithful replication of the Pine logic:
  - Confluence bias votes: EMA9/21, close vs EMA50, RSI50 line, MACD hist, DMI, HTF(60m) trend
  - ADX chop gate, score threshold, bias flips
  - ORB: first-5-min opening range, break + VWAP confirm, window 5..150 min, once/day
  - Pivot S/R (10/10, confirmed 10 bars later - no lookahead), entry room filter, target capping
  - Exits: ATR stop, ATR target (capped at S/R), bias flip/lost, time stop [, EOD flat]
Fills are conservative: if a bar spans both stop and target, the STOP is assumed hit first.
"""
import numpy as np
import pandas as pd
from pathlib import Path
from dataclasses import dataclass, replace, asdict, field

DATA = Path(__file__).parent / "data"
TICKERS = ["NVDA", "SPY", "QQQ", "TSLA", "AAPL"]


# ---------------- indicators (match Pine ta.*) ----------------
def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()

def rma(s, n):
    return s.ewm(alpha=1 / n, adjust=False).mean()

def rsi(close, n=14):
    d = close.diff()
    up = rma(d.clip(lower=0), n)
    dn = rma((-d).clip(lower=0), n)
    rs = up / dn
    return 100 - 100 / (1 + rs)

def macd_hist(close, f=12, s=26, sig=9):
    line = ema(close, f) - ema(close, s)
    return line - ema(line, sig)

def dmi(h, l, c, n=14):
    up = h.diff()
    dn = -l.diff()
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr_ = rma(tr, n)
    pdi = 100 * rma(pd.Series(plus_dm, index=h.index), n) / atr_
    mdi = 100 * rma(pd.Series(minus_dm, index=h.index), n) / atr_
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi)
    adx = rma(dx.fillna(0), n)
    return pdi, mdi, adx

def atr(h, l, c, n=14):
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return rma(tr, n)


# ---------------- config ----------------
@dataclass(frozen=True)
class Cfg:
    entry_source: str = "both"      # bias | orb | both
    score_thresh: int = 2
    adx_thresh: float = 20.0
    use_adx_gate: bool = True
    use_htf: bool = True
    atr_stop: float = 1.5
    atr_tgt: float = 2.0
    use_sr_target: bool = True
    use_sr_filter: bool = True
    sr_buf_pct: float = 0.25
    use_bias_exit: bool = True
    bias_exit_orb: bool = False
    time_stop_bars: int = 30        # 5m bars
    eod_flat: bool = False          # exit at session end (Pine holds overnight)
    orb_use_vwap: bool = True
    orb_end_min: int = 150
    entry_cutoff_min: int = 9999    # no new entries after N min from open (bias entries too)
    orb_stop_or: bool = False       # ORB entries: stop at opposite OR side instead of ATR
    orb_bias_filter: str = "off"    # off | soft (bias not opposite) | hard (bias must agree)


# ---------------- per-ticker precompute ----------------
def prepare(ticker, data_dir=DATA):
    df = pd.read_csv(data_dir / f"{ticker}_5m.csv", index_col=0)
    # mixed UTC offsets across DST boundaries -> parse via UTC then convert
    df.index = pd.to_datetime(df.index, utc=True).tz_convert("America/New_York")
    o, h, l, c, v = df.Open, df.High, df.Low, df.Close, df.Volume

    out = pd.DataFrame(index=df.index)
    out["o"], out["h"], out["l"], out["c"] = o, h, l, c
    out["ema_f"], out["ema_s"], out["ema_t"] = ema(c, 9), ema(c, 21), ema(c, 50)
    out["rsi"] = rsi(c)
    out["mhist"] = macd_hist(c)
    pdi, mdi, adx = dmi(h, l, c)
    out["pdi"], out["mdi"], out["adx"] = pdi, mdi, adx
    out["atr"] = atr(h, l, c)

    # session bookkeeping
    dates = pd.Series(df.index.date, index=df.index)
    out["date"] = dates
    out["mins"] = (df.index.hour - 9) * 60 + (df.index.minute - 30)

    # session VWAP
    tp = (h + l + c) / 3
    out["vwap"] = (tp * v).groupby(dates.values).cumsum() / v.groupby(dates.values).cumsum().replace(0, np.nan)

    # HTF 60m trend vote: last COMPLETED 60m bar close > EMA50(60m)  (no lookahead)
    c60 = c.resample("60min", origin="start_day", offset="570min").last().dropna()
    htf_bull_60 = (c60 > ema(c60, 50))
    # value known at the close of each 60m bar -> applies to later 5m bars
    htf_map = htf_bull_60.copy()
    htf_map.index = htf_map.index + pd.Timedelta(minutes=60)  # becomes usable after the bar completes
    out["htf_bull"] = htf_map.reindex(out.index, method="ffill").astype("boolean").fillna(False).astype(bool)

    # pivot S/R 10/10, confirmed pivRight bars later
    L = R = 10
    hh, ll = h.values, l.values
    n = len(out)
    piv_hi = np.full(n, np.nan)  # at bar i: a pivot high CONFIRMED at i (pivot was at i-R)
    piv_lo = np.full(n, np.nan)
    for i in range(L + R, n):
        p = i - R
        if hh[p] == hh[p - L:p + R + 1].max():
            piv_hi[i] = hh[p]
        if ll[p] == ll[p - L:p + R + 1].min():
            piv_lo[i] = ll[p]
    out["piv_hi"], out["piv_lo"] = piv_hi, piv_lo
    return out


def votes_and_bias(out, cfg: Cfg):
    v = (np.where(out.ema_f > out.ema_s, 1, -1)
         + np.where(out.c > out.ema_t, 1, -1)
         + np.where(out.rsi > 50, 1, -1)
         + np.where(out.mhist > 0, 1, -1)
         + np.where(out.pdi > out.mdi, 1, -1))
    if cfg.use_htf:
        v = v + np.where(out.htf_bull, 1, -1)
    chop = cfg.use_adx_gate & (out.adx < cfg.adx_thresh)
    bias = np.where(chop, 0, np.where(v >= cfg.score_thresh, 1, np.where(v <= -cfg.score_thresh, -1, 0)))
    return bias


# ---------------- engine ----------------
def run(out, cfg: Cfg):
    bias = votes_and_bias(out, cfg)
    n = len(out)
    o, h, l, c = out.o.values, out.h.values, out.l.values, out.c.values
    atr_v, vwap = out.atr.values, out.vwap.values
    mins = out.mins.values
    dates = out.date.values
    piv_hi, piv_lo = out.piv_hi.values, out.piv_lo.values

    res_lvls, sup_lvls = [], []          # rolling last-3 confirmed levels
    trades = []
    pos = 0; entry = stop = tgt = np.nan; ebar = -1; esrc = 0
    or_hi = or_lo = np.nan; orb_done = True
    cur_date = None

    for i in range(1, n):
        if dates[i] != cur_date:          # new session
            cur_date = dates[i]
            or_hi, or_lo = h[i], l[i]     # first 5m bar = opening range (bar spans 9:30-9:35)
            orb_done = False
            if cfg.eod_flat and pos != 0:
                pass                      # handled at end of prior session below
        # maintain S/R lists
        if not np.isnan(piv_hi[i]):
            res_lvls.append(piv_hi[i])
            if len(res_lvls) > 3: res_lvls.pop(0)
        if not np.isnan(piv_lo[i]):
            sup_lvls.append(piv_lo[i])
            if len(sup_lvls) > 3: sup_lvls.pop(0)

        n_res = min([x for x in res_lvls if x > c[i]], default=np.nan)
        n_sup = max([x for x in sup_lvls if x < c[i]], default=np.nan)

        last_bar_of_day = (i + 1 >= n) or (dates[i + 1] != dates[i])

        # ---------- exits ----------
        if pos != 0:
            exit_px = None; why = None
            bias_exit_on = cfg.use_bias_exit and (esrc == 1 or cfg.bias_exit_orb)
            if pos == 1:
                if l[i] <= stop:
                    exit_px, why = (o[i] if o[i] < stop else stop), "STOP"
                elif h[i] >= tgt:
                    exit_px, why = (o[i] if o[i] > tgt else tgt), "TARGET"
                elif bias_exit_on and bias[i] != 1:
                    exit_px, why = c[i], "BIAS"
                elif i - ebar >= cfg.time_stop_bars:
                    exit_px, why = c[i], "TIME"
            else:
                if h[i] >= stop:
                    exit_px, why = (o[i] if o[i] > stop else stop), "STOP"
                elif l[i] <= tgt:
                    exit_px, why = (o[i] if o[i] < tgt else tgt), "TARGET"
                elif bias_exit_on and bias[i] != -1:
                    exit_px, why = c[i], "BIAS"
                elif i - ebar >= cfg.time_stop_bars:
                    exit_px, why = c[i], "TIME"
            if exit_px is None and cfg.eod_flat and last_bar_of_day:
                exit_px, why = c[i], "EOD"
            if exit_px is not None:
                pnl = (exit_px - entry) / entry * pos * 100
                trades.append(dict(date=dates[i], src=esrc, dir=pos, pnl=pnl, why=why))
                pos = 0; esrc = 0

        # ---------- entries ----------
        if pos == 0 and mins[i] < cfg.entry_cutoff_min and not (cfg.eod_flat and last_bar_of_day):
            flip_call = bias[i] == 1 and bias[i - 1] != 1
            flip_put = bias[i] == -1 and bias[i - 1] != -1
            orb_ok = (not orb_done) and 5 <= mins[i] < cfg.orb_end_min
            orb_up = orb_ok and c[i] > or_hi and (not cfg.orb_use_vwap or c[i] > vwap[i])
            orb_dn = orb_ok and c[i] < or_lo and (not cfg.orb_use_vwap or c[i] < vwap[i])
            if cfg.orb_bias_filter == "soft":
                orb_up = orb_up and bias[i] >= 0
                orb_dn = orb_dn and bias[i] <= 0
            elif cfg.orb_bias_filter == "hard":
                orb_up = orb_up and bias[i] == 1
                orb_dn = orb_dn and bias[i] == -1
            if orb_up or orb_dn:
                orb_done = True

            allow_bias = cfg.entry_source in ("bias", "both")
            allow_orb = cfg.entry_source in ("orb", "both")
            t_call_b, t_put_b = allow_bias and flip_call, allow_bias and flip_put
            t_call_o, t_put_o = allow_orb and orb_up, allow_orb and orb_dn

            room_up = 100.0 if np.isnan(n_res) else (n_res - c[i]) / c[i] * 100
            room_dn = 100.0 if np.isnan(n_sup) else (c[i] - n_sup) / c[i] * 100

            if (t_call_b or t_call_o) and (not cfg.use_sr_filter or room_up >= cfg.sr_buf_pct):
                pos, entry, ebar = 1, c[i], i
                esrc = 1 if t_call_b else 2
                stop = c[i] - atr_v[i] * cfg.atr_stop
                if esrc == 2 and cfg.orb_stop_or:
                    stop = or_lo
                tgt = c[i] + atr_v[i] * cfg.atr_tgt
                if cfg.use_sr_target and not np.isnan(n_res) and n_res < tgt:
                    tgt = n_res
            elif (t_put_b or t_put_o) and (not cfg.use_sr_filter or room_dn >= cfg.sr_buf_pct):
                pos, entry, ebar = -1, c[i], i
                esrc = 1 if t_put_b else 2
                stop = c[i] + atr_v[i] * cfg.atr_stop
                if esrc == 2 and cfg.orb_stop_or:
                    stop = or_hi
                tgt = c[i] - atr_v[i] * cfg.atr_tgt
                if cfg.use_sr_target and not np.isnan(n_sup) and n_sup > tgt:
                    tgt = n_sup
    return trades


def stats(trades):
    if not trades:
        return dict(n=0, win=np.nan, pf=np.nan, avg=np.nan, exp=np.nan)
    pnl = np.array([t["pnl"] for t in trades])
    wins = pnl > 0
    gp, gl = pnl[pnl > 0].sum(), -pnl[pnl < 0].sum()
    return dict(n=len(pnl), win=100 * wins.mean(), pf=(gp / gl if gl > 0 else np.inf),
                avg=pnl.mean(), exp=pnl.mean())


def run_all(datasets, cfg, date_filter=None):
    all_tr = []
    for t, out in datasets.items():
        tr = run(out, cfg)
        for x in tr:
            x["ticker"] = t
        all_tr += tr
    if date_filter:
        all_tr = [t for t in all_tr if date_filter(t["date"])]
    return all_tr


if __name__ == "__main__":
    datasets = {t: prepare(t) for t in TICKERS}
    all_dates = sorted(set(d for out in datasets.values() for d in out.date))
    split = all_dates[int(len(all_dates) * 0.67)]
    print(f"sessions: {len(all_dates)}  train <= {split}  test > {split}")

    base = Cfg()  # Pine defaults
    tr = run_all(datasets, base)
    s = stats(tr)
    print(f"\nBASELINE (Pine defaults, both sources): n={s['n']} win={s['win']:.1f}% PF={s['pf']:.2f} avg={s['avg']:.3f}%")
    for src, name in [(1, "bias-flip"), (2, "ORB")]:
        s2 = stats([t for t in tr if t["src"] == src])
        print(f"  {name:9s}: n={s2['n']} win={s2['win']:.1f}% PF={s2['pf']:.2f} avg={s2['avg']:.3f}%")
    from collections import Counter
    print("  exits:", Counter(t["why"] for t in tr))
