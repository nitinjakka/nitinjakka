"""NVDA blind-9:30 options test, last 30 days (20 sessions Jun 27 - Jul 24 2026).

Each session: buy ONE weekly NVDA option (this-week-Friday expiry, nearest
OTM, $2.50 strikes) at the 9:30 open price. Direction rules tested (all
knowable at 9:30 sharp):
  gap-follow : open > prior close -> CALL, else PUT
  gap-fade   : open > prior close -> PUT,  else CALL
  always-call / always-put
Exits: premium stop at -50% (checked on 5-min bar extremes, conservative),
else hold to 15:55 and sell. Premiums: Black-Scholes, IV=0.51 (calibrated
from live NVDA ATM weekly quote), r=4%, half-spread $0.025.
Also shown: same rules with NO stop (to isolate the stop's effect).
$100 all-in per trade, fractional contracts, compounded daily.
"""
import math
import numpy as np
import pandas as pd
from pathlib import Path

HERE = Path(__file__).parent
IV, RATE, HS, STEP = 0.51, 0.04, 0.025, 2.5
LAST_DAY = pd.Timestamp("2026-07-24").date()
CUT = pd.Timestamp("2026-06-27").date()


def bs(d, S, K, t):
    intr = max(S - K, 0.0) if d == 1 else max(K - S, 0.0)
    if t <= 0:
        return intr
    d1 = (math.log(S / K) + (RATE + IV * IV / 2) * t) / (IV * math.sqrt(t))
    d2 = d1 - IV * math.sqrt(t)
    N = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))
    px = (S * N(d1) - K * math.exp(-RATE * t) * N(d2)) if d == 1 else \
         (K * math.exp(-RATE * t) * N(-d2) - S * N(-d1))
    return max(px, intr, 0.01)


df = pd.read_csv(HERE / "NVDA_5m_60d.csv", index_col=0, parse_dates=True)
if df.index.tz is None:
    df.index = df.index.tz_localize("UTC")
df.index = df.index.tz_convert("America/New_York")
df = df[["Open", "High", "Low", "Close"]].dropna()
df["date"] = pd.Series(df.index.date, index=df.index)
df = df[df.date <= LAST_DAY]

days = sorted(set(df.date))
day_bars = {d: df[df.date == d] for d in days}
prior_close = {days[i]: float(day_bars[days[i - 1]].Close.iloc[-1])
               for i in range(1, len(days))}
test_days = [d for d in days if d >= CUT and d in prior_close]


def friday_expiry(d):
    dt = pd.Timestamp(d)
    fri = dt + pd.Timedelta(days=(4 - dt.weekday()) % 7)
    return fri.tz_localize("America/New_York") + pd.Timedelta(hours=16)


def t_exp(ts, exp):
    return max((exp - ts).total_seconds() / (365 * 24 * 3600), 0.0)


def run(rule, use_stop):
    bank = 100.0
    log = []
    for d in test_days:
        bars = day_bars[d]
        o930 = float(bars.Open.iloc[0])
        gap_up = o930 > prior_close[d]
        direction = {"gap-follow": 1 if gap_up else -1,
                     "gap-fade": -1 if gap_up else 1,
                     "always-call": 1, "always-put": -1}[rule]
        exp = friday_expiry(d)
        K = (math.ceil(o930 / STEP) if direction == 1 else
             math.floor(o930 / STEP)) * STEP
        ts0 = bars.index[0]
        entry = bs(direction, o930, K, t_exp(ts0, exp)) + HS
        exit_prem = why = None
        for ts, row in bars.iterrows():
            t = t_exp(ts + pd.Timedelta(minutes=5), exp)
            worst_S = row.Low if direction == 1 else row.High
            if use_stop and bs(direction, worst_S, K, t) - HS <= 0.5 * entry:
                exit_prem, why = 0.5 * entry, "STOP"
                break
        if exit_prem is None:
            last = bars.iloc[-1]
            t = t_exp(bars.index[-1], exp)
            exit_prem = max(bs(direction, float(last.Close), K, t) - HS, 0.0)
            why = "EOD"
        ret = exit_prem / entry - 1
        bank *= 1 + ret
        log.append(dict(day=str(d), dir="C" if direction == 1 else "P",
                        strike=K, entry=round(entry, 2),
                        exit=round(exit_prem, 2), why=why,
                        ret=round(ret * 100, 1), bank=round(bank, 2)))
    return bank, log


print(f"NVDA, {len(test_days)} sessions {test_days[0]} -> {test_days[-1]}")
print(f"{'rule':<14}{'stop':<10}{'wins':<8}{'final $100':<14}{'return'}")
results = {}
for rule in ["gap-follow", "gap-fade", "always-call", "always-put"]:
    for use_stop in [True, False]:
        bank, log = run(rule, use_stop)
        wins = sum(1 for x in log if x["ret"] > 0)
        tag = "-50% prem" if use_stop else "none"
        print(f"{rule:<14}{tag:<10}{wins}/{len(log):<6}${bank:<13.2f}{bank-100:+.1f}%")
        results[(rule, use_stop)] = (bank, log)

best_key = max(results, key=lambda k: results[k][0])
bank, log = results[best_key]
print(f"\n--- daily log: {best_key[0]}, stop={'on' if best_key[1] else 'off'} "
      f"(best variant) ---")
for x in log:
    print(f"  {x['day']}  {x['dir']} {x['strike']:>6}  in ${x['entry']:>5.2f} "
          f"out ${x['exit']:>5.2f}  {x['why']:<5} {x['ret']:>+7.1f}%  "
          f"bank ${x['bank']:>8.2f}")
