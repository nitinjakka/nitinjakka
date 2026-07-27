#!/usr/bin/env bash
# ===========================================================
#  Robinhood BUY TEST - buys 1 SPY $739 Call exp 2026-07-24
#  Usage:  ./buy_test.sh             (limit = current ask)
#          ./buy_test.sh --price 2.50
#  WARNING: places a REAL order (queued while market closed).
# ===========================================================
set -e
cd "$(dirname "$0")"

if [ -x ".venv/Scripts/python.exe" ]; then VPY=".venv/Scripts/python.exe";
elif [ -x ".venv/bin/python" ]; then VPY=".venv/bin/python";
else
    echo "[ERROR] .venv not found. Run ./balance_check.sh once first to set it up."
    exit 1
fi

"$VPY" buy_test.py "$@"
