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


def buy(ticker: str, side: str, count: int, limit_cents: int) -> dict:
    """Marketable LIMIT buy (limit at the ask caps slippage vs a raw
    market order). Returns the API order object. Raises on cap breach."""
    notional = count * limit_cents / 100.0
    # MAX_ORDER_USD <= 0 disables the per-order cap.
    if MAX_ORDER_USD > 0 and notional > MAX_ORDER_USD:
        raise RuntimeError(
            f"order ${notional:.2f} exceeds MAX_ORDER_USD ${MAX_ORDER_USD}")
    order = {
        "ticker": ticker,
        "client_order_id": str(uuid.uuid4()),
        "action": "buy",
        "side": side,
        "type": "limit",
        "count": count,
        ("yes_price" if side == "yes" else "no_price"): limit_cents,
    }
    return _signed("POST", "/portfolio/orders", order)


def sell(ticker: str, side: str, count: int, limit_cents: int) -> dict:
    """Marketable LIMIT sell to exit (stop-loss). limit_cents should be
    at or below the current bid to guarantee the fill."""
    order = {
        "ticker": ticker,
        "client_order_id": str(uuid.uuid4()),
        "action": "sell",
        "side": side,
        "type": "limit",
        "count": count,
        ("yes_price" if side == "yes" else "no_price"): limit_cents,
    }
    return _signed("POST", "/portfolio/orders", order)
