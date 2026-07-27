"""1-minute backtest engine for the Combined Suite — generalizes the 5m engine:
  - opening range accumulated over the first `or_min` minutes (five 1-min bars)
  - entry sources: orb (once/day) | orb_rearm (re-fires after each exit) |
                   daybreak (running session hi/lo breakout, all day) | bias | both
  - exits: stop (opposite-OR or ATR), 0.5xATR-style target (S/R capped), time, EOD flat
Conservative fills: stop assumed first when a bar spans both stop and target.
"""
import numpy as np
import pandas as pd
from pathlib import Path
from dataclasses import dataclass
from backtest import ema, rma, rsi, macd_hist, dmi, atr

HERE = Path(__file__).parent
D1M = HERE / "data_1m"
TICKERS = ["NVDA", "SPY", "QQQ", "TSLA", "AAPL"]


@dataclass(frozen=True)
class Cfg1:
    entry_source: str = "orb"       # orb | orb_rearm | daybreak | pullback | srfade | db+pb | bias | both
    or_min: int = 5                 # opening-range length, minutes
    score_thresh: int = 2
    adx_thresh: float = 20.0
    use_adx_gate: bool = True
    use_htf: bool = True
    atr_stop: float = 3.0
    atr_tgt: float = 0.5
    orb_stop_or: bool = True        # ORB-family entries: stop at opposite OR side
    stop_mode: str = ""             # "" (use orb_stop_or/ATR) | "vwap" (stop at entry-time VWAP -/+ tick)
    pb_strict: bool = False         # pullback: require dip to EMA21 + EMA9/21 trend alignment
    pb_stop_atr: float = 0.0        # pullback: 0 = swing stop; >0 = fixed ATR-multiple stop
    use_sr_target: bool = True
    use_sr_filter: bool = True
    sr_buf_pct: float = 0.25
    use_bias_exit: bool = False
    time_stop_bars: int = 390       # 1m bars
    eod_flat: bool = True
    eod_min: int = 385              # 15:55 ET
    orb_use_vwap: bool = True
    orb_end_min: int = 150
    entry_cutoff_min: int = 360     # no NEW entries after 15:30 ET (all-day modes)
    max_trades_day: int = 10        # cap for re-arm / daybreak modes


def prepare1m(ticker):
    df = pd.read_csv(D1M / f"{ticker}_1m.csv", index_col=0)
    df.index = pd.to_datetime(df.index, utc=True).tz_convert("America/New_York")
    df = df.sort_index()
    df = df[~df.index.duplicated(keep="last")]
    df = df[(df.index.time >= pd.Timestamp("09:30").time()) & (df.index.time < pd.Timestamp("16:00").time())]
    o, h, l, c, v = df.open, df.high, df.low, df.close, df.volume

    out = pd.DataFrame(index=df.index)
    out["o"], out["h"], out["l"], out["c"] = o, h, l, c
    out["ema_f"], out["ema_s"], out["ema_t"] = ema(c, 9), ema(c, 21), ema(c, 50)
    out["rsi"] = rsi(c)
    out["mhist"] = macd_hist(c)
    pdi, mdi, adx = dmi(h, l, c)
    out["pdi"], out["mdi"], out["adx"] = pdi, mdi, adx
    out["atr"] = atr(h, l, c)
    dates = pd.Series(df.index.date, index=df.index)
    out["date"] = dates
    out["mins"] = (df.index.hour - 9) * 60 + (df.index.minute - 30)
    tp = (h + l + c) / 3
    out["vwap"] = (tp * v).groupby(dates.values).cumsum() / v.groupby(dates.values).cumsum().replace(0, np.nan)
    c60 = c.resample("60min", origin="start_day", offset="570min").last().dropna()
    htf_bull_60 = (c60 > ema(c60, 50))
    htf_map = htf_bull_60.copy()
    htf_map.index = htf_map.index + pd.Timedelta(minutes=60)
    out["htf_bull"] = htf_map.reindex(out.index, method="ffill").astype("boolean").fillna(False).astype(bool)
    L = R = 10
    hh, ll = h.values, l.values
    n = len(out)
    piv_hi = np.full(n, np.nan)
    piv_lo = np.full(n, np.nan)
    for i in range(L + R, n):
        p = i - R
        if hh[p] == hh[p - L:p + R + 1].max():
            piv_hi[i] = hh[p]
        if ll[p] == ll[p - L:p + R + 1].min():
            piv_lo[i] = ll[p]
    out["piv_hi"], out["piv_lo"] = piv_hi, piv_lo
    return out


def bias_arr(out, cfg):
    v = (np.where(out.ema_f > out.ema_s, 1, -1)
         + np.where(out.c > out.ema_t, 1, -1)
         + np.where(out.rsi > 50, 1, -1)
         + np.where(out.mhist > 0, 1, -1)
         + np.where(out.pdi > out.mdi, 1, -1))
    if cfg.use_htf:
        v = v + np.where(out.htf_bull, 1, -1)
    chop = cfg.use_adx_gate & (out.adx < cfg.adx_thresh)
    return np.where(chop, 0, np.where(v >= cfg.score_thresh, 1, np.where(v <= -cfg.score_thresh, -1, 0)))


def run1m(out, cfg: Cfg1):
    bias = bias_arr(out, cfg)
    n = len(out)
    o, h, l, c = out.o.values, out.h.values, out.l.values, out.c.values
    atr_v, vwap = out.atr.values, out.vwap.values
    mins, dates = out.mins.values, out.date.values
    piv_hi, piv_lo = out.piv_hi.values, out.piv_lo.values
    idx = out.index

    res_lvls, sup_lvls = [], []
    trades = []
    pos = 0; entry = stop = tgt = np.nan; ebar = -1; esrc = 0
    or_hi = or_lo = np.nan
    day_hi = day_lo = np.nan          # running session extremes as of PRIOR bar
    orb_fired_up = orb_fired_dn = False
    trades_today = 0
    cur_date = None

    for i in range(1, n):
        if dates[i] != cur_date:
            cur_date = dates[i]
            or_hi, or_lo = h[i], l[i]
            day_hi, day_lo = h[i], l[i]
            orb_fired_up = orb_fired_dn = False
            trades_today = 0
        elif mins[i] < cfg.or_min:
            or_hi = max(or_hi, h[i]); or_lo = min(or_lo, l[i])

        if not np.isnan(piv_hi[i]):
            res_lvls.append(piv_hi[i]); res_lvls[:] = res_lvls[-3:]
        if not np.isnan(piv_lo[i]):
            sup_lvls.append(piv_lo[i]); sup_lvls[:] = sup_lvls[-3:]
        n_res = min([x for x in res_lvls if x > c[i]], default=np.nan)
        n_sup = max([x for x in sup_lvls if x < c[i]], default=np.nan)
        last_bar = (i + 1 >= n) or (dates[i + 1] != dates[i])
        eod_now = cfg.eod_flat and mins[i] >= cfg.eod_min

        # ---------- exits ----------
        if pos != 0:
            exit_px = None; why = None
            if pos == 1:
                if l[i] <= stop: exit_px, why = (o[i] if o[i] < stop else stop), "STOP"
                elif h[i] >= tgt: exit_px, why = (o[i] if o[i] > tgt else tgt), "TARGET"
                elif cfg.use_bias_exit and bias[i] != 1: exit_px, why = c[i], "BIAS"
                elif i - ebar >= cfg.time_stop_bars: exit_px, why = c[i], "TIME"
                elif eod_now or (cfg.eod_flat and last_bar): exit_px, why = c[i], "EOD"
            else:
                if h[i] >= stop: exit_px, why = (o[i] if o[i] > stop else stop), "STOP"
                elif l[i] <= tgt: exit_px, why = (o[i] if o[i] < tgt else tgt), "TARGET"
                elif cfg.use_bias_exit and bias[i] != -1: exit_px, why = c[i], "BIAS"
                elif i - ebar >= cfg.time_stop_bars: exit_px, why = c[i], "TIME"
                elif eod_now or (cfg.eod_flat and last_bar): exit_px, why = c[i], "EOD"
            if exit_px is not None:
                trades.append(dict(date=dates[i], src=esrc, dir=pos,
                                   entry_ts=idx[ebar], exit_ts=idx[i], entry_px=entry,
                                   exit_px=exit_px, why=why,
                                   pnl=(exit_px - entry) / entry * pos * 100))
                pos = 0; esrc = 0

        # ---------- entries ----------
        can_enter = (pos == 0 and not eod_now and not last_bar
                     and mins[i] >= cfg.or_min and trades_today < cfg.max_trades_day)
        if can_enter:
            up_sig = dn_sig = False; src = 0
            es = cfg.entry_source
            if es in ("orb", "orb_rearm", "both"):
                in_win = mins[i] < cfg.orb_end_min
                up_ok = in_win and c[i] > or_hi and (not cfg.orb_use_vwap or c[i] > vwap[i])
                dn_ok = in_win and c[i] < or_lo and (not cfg.orb_use_vwap or c[i] < vwap[i])
                if es == "orb":            # one signal per day per direction-set
                    up_ok = up_ok and not (orb_fired_up or orb_fired_dn)
                    dn_ok = dn_ok and not (orb_fired_up or orb_fired_dn)
                else:                      # re-arm: block only same-direction repeats back-to-back
                    up_ok = up_ok and not orb_fired_up
                    dn_ok = dn_ok and not orb_fired_dn
                if up_ok: up_sig, src = True, 2
                if dn_ok: dn_sig, src = True, 2
            if es in ("daybreak", "db+pb"):
                in_win = mins[i] < cfg.entry_cutoff_min
                if in_win and c[i] > day_hi and (not cfg.orb_use_vwap or c[i] > vwap[i]):
                    up_sig, src = True, 3
                if in_win and c[i] < day_lo and (not cfg.orb_use_vwap or c[i] < vwap[i]):
                    dn_sig, src = True, 3
            if es in ("pullback", "db+pb") and not (up_sig or dn_sig):
                # with-trend pullback: VWAP side + close re-crossing EMA9 after dip
                in_win = mins[i] < cfg.entry_cutoff_min
                ef, ef1 = out.ema_f.values[i], out.ema_f.values[i - 1]
                es_ = out.ema_s.values[i]
                pb_up = in_win and c[i] > vwap[i] and c[i] > ef and c[i - 1] <= ef1 and c[i] < day_hi
                pb_dn = in_win and c[i] < vwap[i] and c[i] < ef and c[i - 1] >= ef1 and c[i] > day_lo
                if cfg.pb_strict:
                    # genuine dip to EMA21 + aligned trend
                    pb_up = pb_up and ef > es_ and min(l[max(0, i - 10):i + 1]) <= es_
                    pb_dn = pb_dn and ef < es_ and max(h[max(0, i - 10):i + 1]) >= es_
                if pb_up: up_sig, src = True, 4
                if pb_dn: dn_sig, src = True, 4
            if es == "srfade" and not (up_sig or dn_sig):
                # rejection at nearest pivot S/R: touch the level, close back away from it
                in_win = mins[i] < cfg.entry_cutoff_min
                a = atr_v[i]
                if in_win and not np.isnan(n_sup) and l[i] <= n_sup + 0.10 * a and c[i] > o[i] and c[i] > n_sup:
                    up_sig, src = True, 5
                if in_win and not np.isnan(n_res) and h[i] >= n_res - 0.10 * a and c[i] < o[i] and c[i] < n_res:
                    dn_sig, src = True, 5
            if es in ("bias", "both") and not (up_sig or dn_sig):
                if bias[i] == 1 and bias[i - 1] != 1: up_sig, src = True, 1
                if bias[i] == -1 and bias[i - 1] != -1: dn_sig, src = True, 1

            room_up = 100.0 if np.isnan(n_res) else (n_res - c[i]) / c[i] * 100
            room_dn = 100.0 if np.isnan(n_sup) else (c[i] - n_sup) / c[i] * 100

            if up_sig and (not cfg.use_sr_filter or room_up >= cfg.sr_buf_pct):
                pos, entry, ebar, esrc = 1, c[i], i, src
                if src == 4:                       # pullback: stop below the pullback swing low
                    stop = (c[i] - atr_v[i] * cfg.pb_stop_atr) if cfg.pb_stop_atr > 0 else \
                           min(l[max(0, i - 8):i + 1]) - 0.05 * atr_v[i]
                elif src == 5:                     # srfade: stop just beyond the level
                    stop = n_sup - 0.25 * atr_v[i]
                elif cfg.stop_mode == "vwap" and not np.isnan(vwap[i]) and vwap[i] < c[i]:
                    stop = vwap[i]
                else:
                    stop = or_lo if (src in (2, 3) and cfg.orb_stop_or) else c[i] - atr_v[i] * cfg.atr_stop
                tgt = c[i] + atr_v[i] * cfg.atr_tgt
                if cfg.use_sr_target and not np.isnan(n_res) and n_res < tgt: tgt = n_res
                trades_today += 1
                if src == 2: orb_fired_up = True
            elif dn_sig and (not cfg.use_sr_filter or room_dn >= cfg.sr_buf_pct):
                pos, entry, ebar, esrc = -1, c[i], i, src
                if src == 4:
                    stop = (c[i] + atr_v[i] * cfg.pb_stop_atr) if cfg.pb_stop_atr > 0 else \
                           max(h[max(0, i - 8):i + 1]) + 0.05 * atr_v[i]
                elif src == 5:
                    stop = n_res + 0.25 * atr_v[i]
                elif cfg.stop_mode == "vwap" and not np.isnan(vwap[i]) and vwap[i] > c[i]:
                    stop = vwap[i]
                else:
                    stop = or_hi if (src in (2, 3) and cfg.orb_stop_or) else c[i] + atr_v[i] * cfg.atr_stop
                tgt = c[i] - atr_v[i] * cfg.atr_tgt
                if cfg.use_sr_target and not np.isnan(n_sup) and n_sup > tgt: tgt = n_sup
                trades_today += 1
                if src == 2: orb_fired_dn = True

        # update running session extremes AFTER signal check (prior-bar semantics)
        day_hi = max(day_hi, h[i]); day_lo = min(day_lo, l[i])
    return trades


def stats(trades):
    if not trades:
        return dict(n=0, win=np.nan, pf=np.nan, avg=np.nan)
    pnl = np.array([t["pnl"] for t in trades])
    gp, gl = pnl[pnl > 0].sum(), -pnl[pnl < 0].sum()
    return dict(n=len(pnl), win=100 * (pnl > 0).mean(), pf=(gp / gl if gl > 0 else np.inf), avg=pnl.mean())


def run_all(datasets, cfg):
    out = []
    for t, d in datasets.items():
        tr = run1m(d, cfg)
        for x in tr:
            x["ticker"] = t
        out += tr
    return out
