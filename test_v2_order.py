#!/usr/bin/env python3
"""Safely confirm the Kalshi V2 order endpoint works with our request.

Places a 1-contract YES bid at 1 cent (immediate-or-cancel) on the
current BTC 15-min market. At 1c it will NOT fill (nothing sells YES
that cheap near the money) and IOC cancels it instantly, so no position
is opened and effectively no money is spent (worst case 1c). It just
proves the endpoint/path/body format are accepted.

Run on the server with the KALSHI_* env vars set:
  python3 test_v2_order.py
"""
import datetime as dt
import json
import time

import requests

import kalshi_live as k

API = "https://api.elections.kalshi.com/trade-api/v2"

# Credentials sanity first (clear message if env not set).
try:
    print(k.preflight())
except Exception as e:
    print(f"CREDENTIAL/PREFLIGHT ERROR: {e}")
    raise SystemExit(1)

# Find a current open BTC 15-min market (>2 min to close).
ms = requests.get(f"{API}/markets",
                  params={"series_ticker": "KXBTC15M", "status": "open",
                          "limit": 5}, timeout=15).json().get("markets", [])
ms = [m for m in ms
      if dt.datetime.fromisoformat(
          m["close_time"].replace("Z", "+00:00")).timestamp()
      > time.time() + 120]
if not ms:
    print("No open BTC 15-min market right now; try again shortly.")
    raise SystemExit(0)

ticker = sorted(ms, key=lambda x: x["close_time"])[0]["ticker"]
print(f"\nTesting V2 order on {ticker}: 1x YES bid @ 1c (IOC, will not fill)")

try:
    resp = k._place(ticker, "bid", 1, 1)   # side=bid, price=1c, count=1
    print("\n>>> V2 ORDER ENDPOINT ACCEPTED THE ORDER (format is correct):")
    print(json.dumps(resp, indent=2)[:1800])
    print("\nIf you see an order object above with status 'canceled' or "
          "0 filled, the V2 path works and nothing was bought.")
except Exception as e:
    print("\n>>> V2 ORDER TEST FAILED - here is the exact error:")
    print(e)
    print("\nPaste this whole error to Claude to fix the exact field.")
