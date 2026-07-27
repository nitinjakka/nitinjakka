#!/usr/bin/env python3
"""
robinhood_balance.py
--------------------
Log into Robinhood directly (no MCP) and print all account balances.

Uses the robin_stocks library, which talks to Robinhood's private API.
Credentials are read from a local .env file (see .env.example).

This file is deliberately structured so that trading actions (buy/sell
equities and options) can be bolted on later -- see the `trading.py`
stub and the "EXTENDING THIS" note at the bottom.

Usage:
    pip install -r requirements.txt
    cp .env.example .env      # then fill in your credentials
    python robinhood_balance.py
"""

from __future__ import annotations

import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

# robin_stocks exposes the Robinhood API under robin_stocks.robinhood
import robin_stocks.robinhood as rh
from dotenv import load_dotenv

try:
    import pyotp  # only needed if you use an MFA/TOTP secret
except ImportError:  # pragma: no cover - optional dependency
    pyotp = None


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_DIR = Path(__file__).resolve().parent / "logs"


class _Tee:
    """Write-through stream: everything goes to the console AND the log file."""

    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for s in self.streams:
            s.write(data)
        return len(data)

    def flush(self):
        for s in self.streams:
            s.flush()


def setup_logging(prefix: str = "balance") -> Path:
    """Create logs/ and mirror all output to a per-run timestamped file.

    File name pattern: logs/<prefix>_YYYY-MM-DD_HH-MM-SS.log
    """
    LOG_DIR.mkdir(exist_ok=True)
    log_path = LOG_DIR / f"{prefix}_{datetime.now():%Y-%m-%d_%H-%M-%S}.log"
    log_file = open(log_path, "w", encoding="utf-8")
    sys.stdout = _Tee(sys.__stdout__, log_file)
    sys.stderr = _Tee(sys.__stderr__, log_file)
    return log_path


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
def login() -> None:
    """Log into Robinhood using credentials from the environment (.env).

    Supports three MFA setups:
      * No MFA                      -> just username + password.
      * App-based 2FA (TOTP)        -> set RH_MFA_SECRET to your TOTP secret;
                                       a fresh code is generated automatically.
      * SMS / email / prompt MFA    -> you'll be asked to type the code once.

    robin_stocks stores a session token on disk after the first successful
    login, so subsequent runs usually won't re-prompt until it expires.
    """
    load_dotenv()  # loads variables from a local .env file

    username = os.getenv("RH_USERNAME")
    password = os.getenv("RH_PASSWORD")
    mfa_secret = os.getenv("RH_MFA_SECRET")  # optional TOTP secret

    if not username or not password:
        sys.exit(
            "Missing credentials. Copy .env.example to .env and set "
            "RH_USERNAME and RH_PASSWORD."
        )

    mfa_code = None
    if mfa_secret:
        if pyotp is None:
            sys.exit("RH_MFA_SECRET is set but 'pyotp' isn't installed. "
                     "Run: pip install pyotp")
        mfa_code = pyotp.TOTP(mfa_secret).now()

    # store_session=True writes a token to ~/.tokens so you don't have to
    # re-authenticate (and re-enter MFA) on every run.
    rh.login(
        username=username,
        password=password,
        mfa_code=mfa_code,
        store_session=True,
        expiresIn=86400,  # seconds the session token stays valid (1 day)
    )


# ---------------------------------------------------------------------------
# Balance helpers
# ---------------------------------------------------------------------------
def _money(value) -> str:
    """Format a number-ish value as $X,XXX.XX, tolerating None/strings."""
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return "n/a"


def _to_float(value) -> float:
    """Robinhood returns numbers as strings; parse defensively."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def get_all_accounts() -> list:
    """Every brokerage account on this login (individual, IRA, joint, ...).

    robin_stocks defaults every call to the primary account, so we enumerate
    the accounts ourselves and pass account_number explicitly per account.
    """
    from robin_stocks.robinhood.helper import request_get
    from robin_stocks.robinhood.urls import account_profile_url

    accounts = request_get(account_profile_url(), "results") or []
    accounts = [a for a in accounts
                if isinstance(a, dict) and a.get("account_number")]

    # Robinhood's newer account types (named second accounts, managed
    # "Strategies", agentic) are NOT returned by the listing endpoint, but
    # fetching them directly by account number may still work. Put their
    # numbers in .env as:  RH_EXTRA_ACCOUNTS=ABC123,DEF456
    known = {a["account_number"] for a in accounts}
    extra = os.getenv("RH_EXTRA_ACCOUNTS", "")
    for number in [n.strip() for n in extra.split(",") if n.strip()]:
        if number in known:
            continue
        try:
            acct = request_get(account_profile_url(number))
        except Exception as exc:
            print(f"[!] RH_EXTRA_ACCOUNTS: could not fetch {number}: {exc!r}")
            continue
        if isinstance(acct, dict) and acct.get("account_number"):
            accounts.append(acct)
        else:
            print(f"[!] RH_EXTRA_ACCOUNTS: account {number} not accessible "
                  f"via the API (response: {acct!r})")
    return accounts


def _account_label(acct: dict) -> str:
    label = acct.get("brokerage_account_type") or "account"
    if acct.get("nickname"):
        label = f"{acct['nickname']} - {label}"
    if acct.get("type"):
        label += f" / {acct['type']}"
    if acct.get("state") not in (None, "", "active"):
        label += f" [{acct['state']}]"
    return label


def print_account(acct: dict) -> float:
    """Summary + equity positions for ONE account. Returns its equity value."""
    number = acct.get("account_number")
    portfolio = rh.profiles.load_portfolio_profile(account_number=number) or {}

    equity = portfolio.get("equity") or portfolio.get("extended_hours_equity")
    prev_close = _to_float(portfolio.get("equity_previous_close"))
    day_change = None
    # per-account queries sometimes return 0 for previous close -- a day
    # change computed against that is bogus, so skip it
    if equity and prev_close > 0:
        day_change = _to_float(equity) - prev_close

    print("=" * 44)
    print(f"ACCOUNT {number} ({_account_label(acct)})")
    print("=" * 44)
    print(f"  Portfolio value : {_money(equity)}")
    if day_change is not None:
        sign = "+" if day_change >= 0 else "-"
        print(f"  Day change      : {sign}{_money(abs(day_change))}")
    print(f"  Cash            : {_money(acct.get('cash'))}")
    print(f"  Buying power    : {_money(acct.get('buying_power'))}")

    positions = rh.account.get_open_stock_positions(account_number=number) or []
    rows = []
    for pos in positions:
        qty = _to_float(pos.get("quantity"))
        if qty <= 0:
            continue
        symbol = pos.get("symbol") or rh.stocks.get_symbol_by_url(pos.get("instrument"))
        try:
            price = float(rh.stocks.get_latest_price(symbol)[0])
        except Exception:
            price = None
        value = qty * price if price is not None else None
        rows.append((symbol, qty, value))

    if rows:
        print()
        total = 0.0
        for symbol, qty, value in sorted(rows, key=lambda r: r[2] or 0.0,
                                         reverse=True):
            total += value or 0.0
            print(f"  {symbol:<6} {qty:>14.8f} sh   {_money(value):>14}")
    else:
        print()
        print("  (no equity positions)")
    print()
    return _to_float(equity)


def print_crypto() -> float:
    """Crypto holdings and their current value (shared across accounts).

    Returns the total crypto value for the grand total.
    """
    positions = rh.crypto.get_crypto_positions()
    rows = []
    for p in positions or []:
        qty = _to_float(p.get("quantity"))
        if qty <= 0:
            continue
        symbol = p.get("currency", {}).get("code", "?")
        # look up current price to value the holding
        try:
            price = float(rh.crypto.get_crypto_quote(symbol)["mark_price"])
        except Exception:
            price = None
        value = qty * price if price is not None else None
        rows.append((symbol, qty, value))

    if not rows:
        print("No crypto positions.\n")
        return 0.0

    print("=" * 44)
    print("CRYPTO POSITIONS")
    print("=" * 44)
    total = 0.0
    for symbol, qty, value in rows:
        if value is not None:
            total += value
        print(f"  {symbol:<6} {qty:>14.8f}   {_money(value):>14}")
    print("-" * 44)
    print(f"  {'TOTAL':<6} {'':>14}   {_money(total):>14}")
    print()
    return total


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    log_path = setup_logging()
    print(f"Run started : {datetime.now():%Y-%m-%d %H:%M:%S}")
    print(f"Log file    : {log_path}")
    print()
    try:
        login()
        try:
            accounts = get_all_accounts()
            print(f"Found {len(accounts)} brokerage account(s).")
            print()
            grand_total = 0.0
            for acct in accounts:
                grand_total += print_account(acct)
            grand_total += print_crypto()
            print("=" * 44)
            print(f"GRAND TOTAL (all accounts + crypto): {_money(grand_total)}")
        finally:
            # Comment this out if you want to keep the stored session token
            # around between runs (faster, no re-login).
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


# ---------------------------------------------------------------------------
# EXTENDING THIS (buying / selling later)
# ---------------------------------------------------------------------------
# robin_stocks already ships the trading calls -- you just wire them up behind
# the same login() above. A few you'll want:
#
#   Equities:
#     rh.orders.order_buy_market(symbol, quantity)
#     rh.orders.order_sell_market(symbol, quantity)
#     rh.orders.order_buy_limit(symbol, quantity, limitPrice)
#     rh.orders.order_sell_limit(symbol, quantity, limitPrice)
#
#   Options:
#     rh.orders.order_buy_option_limit(positionEffect, creditOrDebit,
#         price, symbol, quantity, expirationDate, strike, optionType)
#     rh.orders.order_sell_option_limit(...)
#
#   Order management:
#     rh.orders.get_all_open_stock_orders()
#     rh.orders.cancel_all_open_stock_orders()
#
# See trading.py for a small guarded wrapper you can grow into.
