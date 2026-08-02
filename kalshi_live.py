#!/usr/bin/env python3
"""Live Kalshi trading helpers: RSA-signed auth + real orders.

Used by kalshi_bot.py only when it is started with --live.

REQUIRED environment (set on the server, NOT in the repo):
  KALSHI_API_KEY_ID        - the API Key ID from Kalshi -> Settings -> API Keys
  KALSHI_PRIVATE_KEY_PATH  - path to the downloaded RSA private key (.pem)
  KALSHI_LIVE_CONFIRM=YES   - explicit opt-in so live can't start by accident

NOTE: Kalshi's API authenticates with an API Key ID + RSA private key.
An account email/password CANNOT place API orders and is not used here.
"""

import base64
import os
import time
import uuid

import requests

API_HOST = "https://api.elections.kalshi.com"
API_ROOT = "/trade-api/v2"

# Runaway guard: refuse any single order above this notional (USD).
MAX_ORDER_USD = float(os.environ.get("KALSHI_MAX_ORDER_USD", "50"))

_private_key = None


def _load_key():
    global _private_key
    if _private_key is not None:
        return _private_key
    from cryptography.hazmat.primitives import serialization
    path = os.environ.get("KALSHI_PRIVATE_KEY_PATH")
    if not path or not os.path.exists(os.path.expanduser(path)):
        raise RuntimeError(
            "KALSHI_PRIVATE_KEY_PATH is unset or the .pem file is missing")
    with open(os.path.expanduser(path), "rb") as f:
        _private_key = serialization.load_pem_private_key(
            f.read(), password=None)
    return _private_key


def preflight() -> str:
    """Validate credentials + confirmation before any trading. Returns a
    human-readable summary or raises RuntimeError."""
    if os.environ.get("KALSHI_LIVE_CONFIRM") != "YES":
        raise RuntimeError(
            "Refusing to trade live: set KALSHI_LIVE_CONFIRM=YES to confirm")
    if not os.environ.get("KALSHI_API_KEY_ID"):
        raise RuntimeError("KALSHI_API_KEY_ID is not set")
    _load_key()  # raises if missing/invalid
    bal = balance_dollars()
    return f"live auth OK, account balance ${bal:.2f}, max order ${MAX_ORDER_USD:.2f}"


def _headers(method: str, path_with_root: str) -> dict:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    ts = str(int(time.time() * 1000))
    msg = (ts + method.upper() + path_with_root).encode()
    sig = _load_key().sign(
        msg,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.DIGEST_LENGTH),
        hashes.SHA256(),
    )
    return {
        "KALSHI-ACCESS-KEY": os.environ["KALSHI_API_KEY_ID"],
        "KALSHI-ACCESS-TIMESTAMP": ts,
        "KALSHI-ACCESS-SIGNATURE": base64.b64encode(sig).decode(),
        "Content-Type": "application/json",
    }


def _signed(method: str, path: str, body: dict | None = None) -> dict:
    # Signature covers API_ROOT + path WITHOUT any query string.
    full = API_ROOT + path
    for attempt in range(3):
        try:
            r = requests.request(method, API_HOST + full,
                                 headers=_headers(method, full),
                                 json=body, timeout=15)
            if r.status_code >= 400:
                raise RuntimeError(f"{r.status_code}: {r.text}")
            return r.json()
        except Exception:
            if attempt == 2:
                raise
            time.sleep(1.5 * (attempt + 1))
    return {}


def balance_dollars() -> float:
    d = _signed("GET", "/portfolio/balance")
    # Kalshi returns balance in cents.
    return float(d.get("balance", 0)) / 100.0


def held_contracts(ticker: str, side: str) -> int:
    """How many contracts we currently hold on this ticker/side. Drops
    if the user sells manually from the Kalshi app. Kalshi's position
    field is net YES contracts (negative = holding NO)."""
    d = _signed("GET", "/portfolio/positions")
    for p in d.get("market_positions", []):
        if p.get("ticker") == ticker:
            pos = int(p.get("position", 0))
            return max(0, pos) if side == "yes" else max(0, -pos)
    return 0


# Kalshi V2 order endpoint. Everything is quoted from the YES leg:
#   side="bid" = buy YES ; side="ask" = sell YES (== buy NO).
# We only ever place marketable orders (immediate_or_cancel) so nothing
# rests: it fills now at the touch or is canceled.
ORDERS_PATH = "/portfolio/events/orders"


def _place(ticker: str, order_side: str, price_cents: int,
           count: int) -> dict:
    price_cents = max(1, min(99, int(price_cents)))
    body = {
        "ticker": ticker,
        "client_order_id": str(uuid.uuid4()),
        "side": order_side,                    # "bid" (buy YES) / "ask" (sell YES)
        "count": str(int(count)),
        "price": f"{price_cents / 100:.4f}",   # YES-leg price, dollars
        "time_in_force": "immediate_or_cancel",
        "self_trade_prevention_type": "taker_at_cross",
    }
    return _signed("POST", ORDERS_PATH, body)


def enter(ticker: str, want: str, yes_ask_c: int, yes_bid_c: int,
          count: int) -> dict:
    """Open a position marketably.
      want == "yes" -> buy YES: bid at the YES ask.
      want == "no"  -> buy NO : sell YES at the YES bid.
    Prices are whole cents from the YES book."""
    if want == "yes":
        cost = count * yes_ask_c / 100.0
        side, price = "bid", yes_ask_c
    else:
        cost = count * (100 - yes_bid_c) / 100.0   # NO cost = 1 - yes_bid
        side, price = "ask", yes_bid_c
    if MAX_ORDER_USD > 0 and cost > MAX_ORDER_USD:
        raise RuntimeError(
            f"order ${cost:.2f} exceeds MAX_ORDER_USD ${MAX_ORDER_USD}")
    return _place(ticker, side, price, count)


def exit_pos(ticker: str, held_side: str, yes_ask_c: int, yes_bid_c: int,
             count: int) -> dict:
    """Close a position marketably (stop-loss).
      held YES -> sell YES: ask at the YES bid.
      held NO  -> buy  YES: bid at the YES ask (covers the short)."""
    if held_side == "yes":
        return _place(ticker, "ask", yes_bid_c, count)
    return _place(ticker, "bid", yes_ask_c, count)
