#!/usr/bin/env python3
"""Kalshi trading helper for the 15-minute BTC up/down markets (KXBTC15M).

SAFETY: This script NEVER places an order unless you pass --live.
Without --live it runs in dry-run mode and only prints the order it
would submit.

Setup (one time):
  1. Log in to Kalshi -> Account & Security -> API Keys -> Create key.
     Kalshi shows you a Key ID and lets you download an RSA private key
     (.pem file). Keep the .pem safe; Kalshi never shows it again.
  2. Export credentials (do NOT hardcode them in this file):
       export KALSHI_API_KEY_ID="your-key-id"
       export KALSHI_PRIVATE_KEY_PATH="$HOME/kalshi_private_key.pem"
  3. pip install requests cryptography

Usage:
  # Show the currently open 15-min BTC market and its odds (no auth needed)
  python3 kalshi_trade.py quote

  # Show your balance (auth needed)
  python3 kalshi_trade.py balance

  # Dry-run: buy 10 "Up" (Yes) contracts at a 78c limit on the live market
  python3 kalshi_trade.py order --side up --count 10 --limit-cents 78

  # Same but target a specific market ticker
  python3 kalshi_trade.py order --ticker KXBTC15M-26JUL262315-15 \
      --side down --count 5 --limit-cents 23

  # Actually place it (asks for confirmation first)
  python3 kalshi_trade.py order --side up --count 10 --limit-cents 78 --live
"""

import argparse
import base64
import datetime as dt
import json
import os
import sys
import time
import uuid

import requests

API_BASE = "https://api.elections.kalshi.com"
API_ROOT = "/trade-api/v2"
SERIES_TICKER = "KXBTC15M"


# ---------------------------------------------------------------- auth ----

def load_private_key():
    from cryptography.hazmat.primitives import serialization

    path = os.environ.get("KALSHI_PRIVATE_KEY_PATH")
    if not path:
        sys.exit("KALSHI_PRIVATE_KEY_PATH is not set (path to your RSA .pem)")
    with open(os.path.expanduser(path), "rb") as f:
        return serialization.load_pem_private_key(f.read(), password=None)


def auth_headers(method: str, path: str) -> dict:
    """Kalshi API v2 request signing: RSA-PSS-SHA256 over ts + METHOD + path."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    key_id = os.environ.get("KALSHI_API_KEY_ID")
    if not key_id:
        sys.exit("KALSHI_API_KEY_ID is not set")

    ts = str(int(time.time() * 1000))
    message = (ts + method.upper() + path).encode()
    signature = load_private_key().sign(
        message,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.DIGEST_LENGTH,
        ),
        hashes.SHA256(),
    )
    return {
        "KALSHI-ACCESS-KEY": key_id,
        "KALSHI-ACCESS-TIMESTAMP": ts,
        "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode(),
        "Content-Type": "application/json",
    }


# ------------------------------------------------------------- requests ----

def public_get(path: str, params: dict | None = None) -> dict:
    r = requests.get(API_BASE + API_ROOT + path, params=params, timeout=15)
    r.raise_for_status()
    return r.json()


def signed_request(method: str, path: str, body: dict | None = None) -> dict:
    # Signature covers the path WITHOUT query string.
    headers = auth_headers(method, API_ROOT + path)
    r = requests.request(
        method,
        API_BASE + API_ROOT + path,
        headers=headers,
        json=body,
        timeout=15,
    )
    if not r.ok:
        sys.exit(f"API error {r.status_code}: {r.text}")
    return r.json()


# ------------------------------------------------------------- commands ----

def current_market(ticker: str | None = None) -> dict:
    """Return the requested market, or the currently open KXBTC15M market."""
    if ticker:
        return public_get(f"/markets/{ticker}")["market"]
    markets = public_get(
        "/markets",
        {"series_ticker": SERIES_TICKER, "status": "open", "limit": 5},
    )["markets"]
    if not markets:
        sys.exit("No open KXBTC15M market found right now.")
    # Open markets are the live window(s); take the one closing soonest.
    return sorted(markets, key=lambda m: m["close_time"])[0]


def show_quote(market: dict) -> None:
    close = dt.datetime.fromisoformat(market["close_time"].replace("Z", "+00:00"))
    left = (close - dt.datetime.now(dt.timezone.utc)).total_seconds() / 60
    yes_ask = market.get("yes_ask_dollars") or "?"
    no_ask = market.get("no_ask_dollars") or "?"
    print(f"market : {market['ticker']}")
    print(f"title  : {market.get('title')} | {market.get('yes_sub_title', '')}")
    print(f"closes : {market['close_time']}  ({left:.1f} min left)")
    print(f"UP  (Yes) ask: ${yes_ask}  -> ~{float(yes_ask) * 100:.0f}% chance"
          if yes_ask != "?" else "UP  (Yes) ask: n/a")
    print(f"DOWN (No) ask: ${no_ask}  -> ~{float(no_ask) * 100:.0f}% chance"
          if no_ask != "?" else "DOWN (No) ask: n/a")
    print(f"last   : ${market.get('last_price_dollars', '?')}")


def cmd_quote(args: argparse.Namespace) -> None:
    show_quote(current_market(args.ticker))


def cmd_balance(_args: argparse.Namespace) -> None:
    data = signed_request("GET", "/portfolio/balance")
    print(json.dumps(data, indent=2))


def cmd_order(args: argparse.Namespace) -> None:
    market = current_market(args.ticker)
    side = "yes" if args.side == "up" else "no"

    if not 1 <= args.limit_cents <= 99:
        sys.exit("--limit-cents must be between 1 and 99")
    if args.count < 1:
        sys.exit("--count must be >= 1")

    order = {
        "ticker": market["ticker"],
        "client_order_id": str(uuid.uuid4()),
        "action": "buy",
        "side": side,
        "type": "limit",
        "count": args.count,
        ("yes_price" if side == "yes" else "no_price"): args.limit_cents,
    }
    max_cost = args.count * args.limit_cents / 100

    show_quote(market)
    print()
    print(f"ORDER  : buy {args.count}x {args.side.upper()} ({side}) "
          f"@ {args.limit_cents}c limit  (max cost ${max_cost:.2f}, "
          f"max payout ${args.count:.2f})")
    print(json.dumps(order, indent=2))

    if not args.live:
        print("\nDRY RUN - nothing was sent. Re-run with --live to place it.")
        return

    confirm = input(f"\nType PLACE to submit this order for real: ").strip()
    if confirm != "PLACE":
        print("Aborted - no order placed.")
        return

    result = signed_request("POST", "/portfolio/orders", order)
    print("\nOrder submitted:")
    print(json.dumps(result, indent=2))


# ------------------------------------------------------------------ cli ----

def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    q = sub.add_parser("quote", help="show live odds for the open 15-min BTC market")
    q.add_argument("--ticker", help="specific market ticker (default: live market)")
    q.set_defaults(func=cmd_quote)

    b = sub.add_parser("balance", help="show account balance (needs API key)")
    b.set_defaults(func=cmd_balance)

    o = sub.add_parser("order", help="build (and optionally place) a limit order")
    o.add_argument("--ticker", help="specific market ticker (default: live market)")
    o.add_argument("--side", choices=["up", "down"], required=True,
                   help="up = Yes, down = No")
    o.add_argument("--count", type=int, required=True, help="number of contracts")
    o.add_argument("--limit-cents", type=int, required=True,
                   help="limit price in cents (1-99)")
    o.add_argument("--live", action="store_true",
                   help="actually place the order (default is dry run)")
    o.set_defaults(func=cmd_order)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
