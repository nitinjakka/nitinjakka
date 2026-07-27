#!/usr/bin/env python3
"""
buy_test.py
-----------
Test placing an OPTIONS order: buy to open 1 SPY $739 Call exp 2026-07-24,
as a limit order at the current ask price. Works while the market is closed --
Robinhood accepts the order and queues it for the next session.

Usage:
    python buy_test.py                 # SPY 739 call 2026-07-24, limit = ask
    python buy_test.py --price 2.50    # same contract, your own limit price

To test a different contract, edit the DEFAULTS below.

NOTE: this places a REAL order (queued if the market is closed). Cancel it
any time in the app: the contract -> Orders -> Cancel. The order goes to the
primary (individual) account. Everything is logged to logs/.
"""

from __future__ import annotations

import sys
import traceback
from datetime import datetime

import robin_stocks.robinhood as rh

from robinhood_balance import _money, _to_float, login, setup_logging

# ---------------------------------------------------------------------------
# DEFAULTS - the contract this test buys
# ---------------------------------------------------------------------------
SYMBOL = "SPY"
STRIKE = 739
OPTION_TYPE = "call"          # "call" or "put"
EXPIRATION = "2026-07-24"     # YYYY-MM-DD
QUANTITY = 1                  # contracts (1 contract = 100 shares exposure)
TIME_IN_FORCE = "gtc"         # good-till-canceled, so it survives the queue


def get_contract_quote() -> dict | None:
    """Market data for the target contract (ask/bid/mark, tradability)."""
    results = rh.options.find_options_by_expiration_and_strike(
        SYMBOL, EXPIRATION, str(STRIKE), optionType=OPTION_TYPE
    )
    for c in results or []:
        if c:
            return c
    return None


def main() -> None:
    limit_price = None
    argv = sys.argv[1:]
    if "--price" in argv:
        try:
            limit_price = float(argv[argv.index("--price") + 1])
        except (IndexError, ValueError):
            sys.exit("Usage: buy_test.py [--price X.XX]")

    log_path = setup_logging(prefix="buy_test")
    print(f"Run started : {datetime.now():%Y-%m-%d %H:%M:%S}")
    print(f"Log file    : {log_path}")
    print()

    try:
        login()
        try:
            contract = get_contract_quote()
            if not contract:
                sys.exit(f"Contract not found: {SYMBOL} ${STRIKE} "
                         f"{OPTION_TYPE} exp {EXPIRATION}. Check the strike "
                         "and expiration date.")

            ask = _to_float(contract.get("ask_price"))
            bid = _to_float(contract.get("bid_price"))
            mark = _to_float(contract.get("adjusted_mark_price")
                             or contract.get("mark_price"))
            state = contract.get("state")
            tradability = contract.get("tradability")

            if limit_price is None:
                limit_price = ask if ask > 0 else mark
            limit_price = round(limit_price, 2)
            if limit_price <= 0:
                sys.exit("No usable price (ask/mark both 0) and no --price "
                         "given. Pass one, e.g.: buy_test.py --price 2.88")

            cost = limit_price * 100 * QUANTITY
            print("=" * 44)
            print("BUY TO OPEN - ORDER PREVIEW")
            print("=" * 44)
            print(f"  Contract   : {SYMBOL} ${STRIKE} {OPTION_TYPE.upper()} "
                  f"exp {EXPIRATION}")
            print(f"  Quantity   : {QUANTITY} contract(s)")
            print(f"  Limit price: {_money(limit_price)}  "
                  f"(ask {_money(ask)} / bid {_money(bid)} / mark {_money(mark)})")
            print(f"  Max cost   : {_money(cost)}  (premium x 100)")
            print(f"  In force   : {TIME_IN_FORCE.upper()}")
            print(f"  Contract state/tradability: {state} / {tradability}")
            print()
            print("Placing order now...")

            result = rh.orders.order_buy_option_limit(
                positionEffect="open",
                creditOrDebit="debit",
                price=limit_price,
                symbol=SYMBOL,
                quantity=QUANTITY,
                expirationDate=EXPIRATION,
                strike=STRIKE,
                optionType=OPTION_TYPE,
                timeInForce=TIME_IN_FORCE,
            )

            print()
            print("Robinhood response:")
            print(result)
            print()
            if isinstance(result, dict) and result.get("id"):
                print(f"Order state : {result.get('state')}   "
                      f"(id: {result.get('id')})")
                print("With the market closed, expect state 'queued' or "
                      "'unconfirmed' -- it activates at the next open.")
                print("Cancel any time in the app: SPY -> Orders -> Cancel.")
            else:
                print("[!] Order does not look accepted -- see the response "
                      "above (also saved in the log).")
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
