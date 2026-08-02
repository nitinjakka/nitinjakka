#!/usr/bin/env python3
"""Liveness monitor for the Kalshi bot running elsewhere (e.g. the jump
server). It does NOT trade. It watches the heartbeat topic the bot
pings every 5 minutes; if the heartbeat goes stale it alerts your phone
on the main topic, and tells you when it recovers.

Usage:
  python3 monitor.py                 # runs until stopped
Env:
  NTFY_TOPIC            main topic your phone is subscribed to (alerts)
  NTFY_HEARTBEAT_TOPIC  topic the bot pings (watched here)
"""

import datetime as dt
import os
import time
from zoneinfo import ZoneInfo

import requests

ET = ZoneInfo("America/New_York")
MAIN_TOPIC = os.environ.get("NTFY_TOPIC", "nitin-kalshi-bot-x7q2")
HB_TOPIC = os.environ.get("NTFY_HEARTBEAT_TOPIC",
                          "nitin-kalshi-heartbeat-x7q2")

CHECK_EVERY = 120      # poll for heartbeats every 2 min
STALE_AFTER = 900      # 15 min with no heartbeat  -> consider it down
REALERT_EVERY = 1800   # while down, re-remind every 30 min


def now() -> float:
    return time.time()


def et_now() -> str:
    return f"{dt.datetime.now(ET):%I:%M:%S %p ET}"


def alert(title: str, body: str) -> None:
    try:
        requests.post(f"https://ntfy.sh/{MAIN_TOPIC}", data=body.encode(),
                      headers={"Title": title, "Priority": "high",
                               "Tags": "rotating_light"}, timeout=10)
    except Exception:
        pass


def last_heartbeat_age() -> float | None:
    """Seconds since the newest heartbeat, or None if none is cached."""
    try:
        r = requests.get(
            f"https://ntfy.sh/{HB_TOPIC}/json",
            params={"poll": "1", "since": "2h"}, timeout=15)
        r.raise_for_status()
    except Exception:
        return None
    newest = 0
    for line in r.text.splitlines():
        if not line.strip():
            continue
        try:
            import json
            msg = json.loads(line)
        except Exception:
            continue
        if msg.get("event") == "message" and msg.get("time"):
            newest = max(newest, int(msg["time"]))
    if not newest:
        return None
    return now() - newest


def main() -> None:
    print(f"[{et_now()}] monitor start: watching {HB_TOPIC}, "
          f"alerting {MAIN_TOPIC}. stale>{STALE_AFTER}s", flush=True)
    down = False
    last_realert = 0.0
    # Grace period so we don't false-alarm before the first heartbeat.
    started = now()

    while True:
        age = last_heartbeat_age()
        ts = et_now()

        if age is None:
            # No heartbeat cached yet. Only worry after a grace period.
            if now() - started > STALE_AFTER and not down:
                down = True
                last_realert = now()
                alert("Kalshi monitor: NO HEARTBEAT",
                      f"No bot heartbeat seen at all as of {ts}. "
                      f"Is the script running on the server?")
            print(f"[{ts}] no heartbeat cached", flush=True)
        elif age > STALE_AFTER:
            if not down:
                down = True
                last_realert = now()
                alert("Kalshi monitor: BOT DOWN?",
                      f"No heartbeat for {age/60:.0f} min as of {ts}. "
                      f"The bot may have stopped on the server.")
            elif now() - last_realert > REALERT_EVERY:
                last_realert = now()
                alert("Kalshi monitor: STILL DOWN",
                      f"Still no heartbeat ({age/60:.0f} min) as of {ts}.")
            print(f"[{ts}] STALE: {age/60:.1f} min", flush=True)
        else:
            if down:
                down = False
                alert("Kalshi monitor: BACK UP",
                      f"Heartbeat resumed at {ts} "
                      f"(last ping {age:.0f}s ago).")
            print(f"[{ts}] ok: last heartbeat {age:.0f}s ago", flush=True)

        time.sleep(CHECK_EVERY)


if __name__ == "__main__":
    main()
