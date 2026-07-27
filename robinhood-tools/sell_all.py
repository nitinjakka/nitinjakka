#!/usr/bin/env python3
"""
sell_all.py
-----------
Sell your ENTIRE position in one symbol (crypto or equity) at market.

Usage:
    python sell_all.py SOL     # sells the entire SOL position IMMEDIATELY

There is NO confirmation prompt -- running this places a real order.

The symbol is looked up in your crypto positions first, then your equity
holdings. A MARKET order is placed for the full available quantity. Robinhood
often rejects market crypto sells with HTTP 422; when that happens the script
automatically retries as a limit sell ~1% below the current price (fills
immediately, like a market order). The whole run (including Robinhood's order
response) is written to logs/.

Reuses login() and the credentials in .env from robinhood_balance.py.
"""

from __future__ import annotations

import math
import sys
import traceback
from datetime import datetime
from decimal import ROUND_DOWN, Decimal

import robin_stocks.robinhood as rh

from robinhood_balance import _money, login, setup_logging


# ---------------------------------------------------------------------------
# Position lookup
# ---------------------------------------------------------------------------
def _to_float(value) -> float:
    """Robinhood returns numbers as strings; parse defensively."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def find_crypto_position(symbol: str) -> dict | None:
    """Raw position dict for `symbol` (if held at all), else None.

    Note: quantity fields come back as STRINGS (e.g. "0.00000000"), which are
    truthy -- always parse with _to_float() before comparing.
    """
    for p in rh.crypto.get_crypto_positions() or []:
        code = (p.get("currency") or {}).get("code", "")
        if code.upper() == symbol and _to_float(p.get("quantity")) > 0:
            return p
    return None


def print_open_crypto_orders() -> None:
    orders = rh.orders.get_all_open_crypto_orders() or []
    if not orders:
        print("  Open crypto orders: none")
        return
    print("  Open crypto orders:")
    for o in orders:
        print(f"    side={o.get('side')} quantity={o.get('quantity')} "
              f"state={o.get('state')} id={o.get('id')}")


def print_available_positions() -> None:
    """When the symbol isn't found, show what IS there to help diagnose."""
    print("Positions the account does have:")
    for p in rh.crypto.get_crypto_positions() or []:
        code = (p.get("currency") or {}).get("code", "?")
        qty = p.get("quantity")
        qty_avail = p.get("quantity_available")
        print(f"  crypto  {code:<6} quantity={qty}  available={qty_avail}")
    for ticker, data in (rh.account.build_holdings() or {}).items():
        print(f"  equity  {ticker:<6} quantity={data.get('quantity')}")


def find_equity_quantity(symbol: str) -> float | None:
    """Share count of `symbol` in equity holdings, or None."""
    data = (rh.account.build_holdings() or {}).get(symbol)
    if not data:
        return None
    try:
        qty = float(data.get("quantity") or 0)
    except (TypeError, ValueError):
        return None
    return qty if qty > 0 else None


def _round_down_to_increment(value: float, increment: float) -> float:
    """Round `value` DOWN to a multiple of `increment` (exact, via Decimal)."""
    inc = Decimal(str(increment))
    if inc <= 0:
        return value
    return float((Decimal(str(value)) / inc).to_integral_value(ROUND_DOWN) * inc)


def get_crypto_pair_info(symbol: str) -> dict | None:
    """Trading-pair metadata (price/quantity increments) for SYMBOL-USD."""
    for pair in rh.crypto.get_crypto_currency_pairs() or []:
        if (pair.get("symbol") or "").upper() == f"{symbol}-USD":
            return pair
    return None


def _order_ok(result) -> bool:
    return isinstance(result, dict) and bool(result.get("id"))


def sell_crypto(symbol: str, qty: float):
    """Market sell; on Robinhood's frequent 422 rejection, fall back to a
    marketable limit sell ~1% under the mark price (fills immediately)."""
    result = rh.orders.order_sell_crypto_by_quantity(symbol, qty)
    if _order_ok(result):
        return result

    print()
    print("[!] Market order was rejected (Robinhood often 422s crypto market")
    print("    sells). Retrying as a limit sell just below the current price...")

    mark = float(rh.crypto.get_crypto_quote(symbol)["mark_price"])
    pair = get_crypto_pair_info(symbol)
    price_inc = float((pair or {}).get("min_order_price_increment") or 0.01)
    qty_inc = float((pair or {}).get("min_order_quantity_increment") or 1e-8)

    limit_price = _round_down_to_increment(mark * 0.99, price_inc)
    qty = _round_down_to_increment(qty, qty_inc)
    print(f"    Limit sell: {qty} {symbol} @ {_money(limit_price)} "
          f"(mark {_money(mark)})")
    return rh.orders.order_sell_crypto_limit(symbol, qty, limit_price)


def estimate_value(kind: str, symbol: str, qty: float) -> float | None:
    """Current market value of the position, best effort."""
    try:
        if kind == "crypto":
            price = float(rh.crypto.get_crypto_quote(symbol)["mark_price"])
        else:
            price = float(rh.stocks.get_latest_price(symbol)[0])
        return qty * price
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if len(args) != 1:
        sys.exit("Usage: sell_all.py SYMBOL\nExample: sell_all.py SOL")
    symbol = args[0].upper()

    log_path = setup_logging(prefix=f"sell_{symbol}")
    print(f"Run started : {datetime.now():%Y-%m-%d %H:%M:%S}")
    print(f"Log file    : {log_path}")
    print()

    try:
        login()
        try:
            qty = None
            kind = "crypto"
            pos = find_crypto_position(symbol)
            if pos is not None:
                qty_total = _to_float(pos.get("quantity"))
                qty_avail = _to_float(pos.get("quantity_available"))
                if qty_avail <= 0:
                    print(f"You hold {qty_total} {symbol}, but Robinhood reports "
                          f"0 available to sell -- the entire position is locked.")
                    print()
                    print("Most common causes:")
                    print(f"  * The {symbol} is STAKED. Staked crypto can't be "
                          "sold; unstake it in the app first")
                    print("    (Robinhood app -> the coin -> Staking -> Unstake; "
                          "Solana unstaking takes ~2-3 days).")
                    print("  * An open order is holding it (shown below; cancel "
                          "it in the app to free the coins).")
                    print()
                    print(f"  quantity           : {pos.get('quantity')}")
                    print(f"  quantity_available : {pos.get('quantity_available')}")
                    print(f"  held_for_sell      : {pos.get('quantity_held_for_sell')}")
                    print(f"  held_for_buy       : {pos.get('quantity_held_for_buy')}")
                    print_open_crypto_orders()
                    print()
                    print("No order was placed. Once the coins are unlocked, "
                          "run this again.")
                    sys.exit(1)
                if qty_avail < qty_total:
                    print(f"[!] Only {qty_avail} of {qty_total} {symbol} is "
                          "available to sell (rest is locked -- staked or held "
                          "by an open order). Selling the available part.")
                    print()
                # round DOWN to 8 decimals so we never ask for more than held
                qty = math.floor(qty_avail * 1e8) / 1e8
            else:
                qty = find_equity_quantity(symbol)
                kind = "equity"
            if qty is None:
                print(f"No {symbol} position found in crypto or equities. "
                      "Nothing to sell.")
                print()
                print_available_positions()
                sys.exit(1)

            value = estimate_value(kind, symbol, qty)
            unit = "" if kind == "crypto" else " sh"
            print("=" * 44)
            print("SELL ALL - ORDER PREVIEW")
            print("=" * 44)
            print(f"  Symbol     : {symbol} ({kind})")
            print(f"  Quantity   : {qty}{unit}  (entire position)")
            print(f"  Est. value : {_money(value)}")
            print(f"  Order type : MARKET")
            print()
            print("Placing order now (no confirmation prompt)...")

            if kind == "crypto":
                result = sell_crypto(symbol, qty)
            elif qty != int(qty):
                result = rh.orders.order_sell_fractional_by_quantity(symbol, qty)
            else:
                result = rh.orders.order_sell_market(symbol, int(qty))

            print()
            print("Robinhood response:")
            print(result)
            state = (result or {}).get("state") if isinstance(result, dict) else None
            order_id = (result or {}).get("id") if isinstance(result, dict) else None
            print()
            if state:
                print(f"Order state : {state}   (id: {order_id})")
                print("Check the Robinhood app to confirm the fill.")
            else:
                print("[!] Unexpected response - verify in the Robinhood app "
                      "whether the order was actually placed.")
        finally:
            rh.logout()
        print(f"Run finished: {datetime.now():%Y-%m-%d %H:%M:%S}")
    except SystemExit:
        raise
    except Exception:
        print(f"Run FAILED  : {datetime.now():%Y-%m-%d %H:%M:%S}", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
