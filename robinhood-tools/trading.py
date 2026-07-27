#!/usr/bin/env python3
"""
trading.py
----------
Stub for the trading features you want to add later (buy/sell equities and
options). It reuses the exact same login() from robinhood_balance.py, so you
only manage credentials in one place.

IMPORTANT: every function here places REAL orders against a REAL account.
They are wrapped with a DRY_RUN guard so nothing fires until you flip it off.
Start with DRY_RUN=True, confirm the printout looks right, then set it False.
"""

from __future__ import annotations

import robin_stocks.robinhood as rh

from robinhood_balance import login

# Safety switch. While True, functions print what they *would* do and return
# without sending anything to Robinhood.
DRY_RUN = True


def _guard(action: str, **details) -> bool:
    """Return True if the caller should actually place the order."""
    pretty = ", ".join(f"{k}={v}" for k, v in details.items())
    if DRY_RUN:
        print(f"[DRY_RUN] Would {action}: {pretty}")
        return False
    print(f"Placing order -> {action}: {pretty}")
    return True


# --- Equities --------------------------------------------------------------
def buy_market(symbol: str, quantity: float):
    if not _guard("BUY market", symbol=symbol, qty=quantity):
        return None
    return rh.orders.order_buy_market(symbol, quantity)


def sell_market(symbol: str, quantity: float):
    if not _guard("SELL market", symbol=symbol, qty=quantity):
        return None
    return rh.orders.order_sell_market(symbol, quantity)


def buy_limit(symbol: str, quantity: float, limit_price: float):
    if not _guard("BUY limit", symbol=symbol, qty=quantity, price=limit_price):
        return None
    return rh.orders.order_buy_limit(symbol, quantity, limit_price)


def sell_limit(symbol: str, quantity: float, limit_price: float):
    if not _guard("SELL limit", symbol=symbol, qty=quantity, price=limit_price):
        return None
    return rh.orders.order_sell_limit(symbol, quantity, limit_price)


# --- Order management ------------------------------------------------------
def open_orders():
    return rh.orders.get_all_open_stock_orders()


if __name__ == "__main__":
    # Example: dry-run a buy so you can see the flow without risking anything.
    login()
    try:
        buy_market("AAPL", 1)          # prints [DRY_RUN] ... while DRY_RUN=True
        print("Open orders:", open_orders())
    finally:
        rh.logout()
