#!/usr/bin/env python3
"""
diagnose_accounts.py
--------------------
READ-ONLY diagnostic: dump everything Robinhood's API reports about your
accounts, to find one that's visible in the app but missing from the script.

Usage:
    .venv/Scripts/python.exe diagnose_accounts.py     (Windows/MobaXterm)
    .venv/bin/python diagnose_accounts.py             (macOS/Linux)

Places no orders and changes nothing. Output goes to logs/diagnose_*.log.
"""

from __future__ import annotations

import json
import traceback
from datetime import datetime

import robin_stocks.robinhood as rh
from robin_stocks.robinhood.helper import request_get

from robinhood_balance import _money, login, setup_logging

SUMMARY_FIELDS = [
    "account_number", "brokerage_account_type", "type", "state",
    "deactivated", "cash", "buying_power", "created_at",
]


def dump_endpoint(title: str, url: str) -> None:
    print("=" * 60)
    print(title)
    print(f"  {url}")
    print("=" * 60)
    try:
        data = request_get(url, "regular")
    except Exception as exc:
        print(f"  request failed: {exc!r}")
        print()
        return
    results = (data or {}).get("results") if isinstance(data, dict) else None
    if results is None:
        print(json.dumps(data, indent=2, default=str))
        print()
        return
    print(f"  {len(results)} account(s) on this endpoint "
          f"(next page: {(data or {}).get('next')})")
    for acct in results:
        print()
        for f in SUMMARY_FIELDS:
            print(f"    {f:<24}: {acct.get(f)}")
    print()
    print("  --- full JSON (for the log) ---")
    print(json.dumps(data, indent=2, default=str))
    print()


def main() -> None:
    log_path = setup_logging(prefix="diagnose")
    print(f"Run started : {datetime.now():%Y-%m-%d %H:%M:%S}")
    print(f"Log file    : {log_path}")
    print()
    try:
        login()
        try:
            dump_endpoint(
                "BROKERAGE ACCOUNTS (all-accounts flag)",
                "https://api.robinhood.com/accounts/?default_to_all_accounts=true",
            )
            dump_endpoint(
                "BROKERAGE ACCOUNTS (plain)",
                "https://api.robinhood.com/accounts/",
            )

            print("=" * 60)
            print("PHOENIX UNIFIED ACCOUNT (whole-login totals)")
            print("=" * 60)
            try:
                phoenix = rh.account.load_phoenix_account() or {}
                for key in ("total_equity", "portfolio_equity", "equities",
                            "crypto", "uninvested_cash", "withdrawable_cash",
                            "account_buying_power", "options_buying_power"):
                    val = phoenix.get(key)
                    if isinstance(val, dict):
                        val = val.get("amount")
                    print(f"  {key:<24}: {val}")
                print()
                print("  --- full JSON (for the log) ---")
                print(json.dumps(phoenix, indent=2, default=str))
            except Exception as exc:
                print(f"  request failed: {exc!r}")
            print()
        finally:
            rh.logout()
        print(f"Run finished: {datetime.now():%Y-%m-%d %H:%M:%S}")
    except SystemExit:
        raise
    except Exception:
        print(f"Run FAILED  : {datetime.now():%Y-%m-%d %H:%M:%S}")
        traceback.print_exc()
        raise SystemExit(1)


if __name__ == "__main__":
    main()
