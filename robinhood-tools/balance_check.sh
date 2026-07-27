#!/usr/bin/env bash
# ===========================================================
#  Robinhood balance checker - one-click runner (macOS/Linux)
#  Usage:  ./balance_check.sh   (no arguments)
#  First run: creates a .venv here and installs dependencies.
#  Later runs: just runs the script.
# ===========================================================
set -e
cd "$(dirname "$0")"

# Find the venv's python. On Windows (Git Bash / MobaXterm) a venv made by
# Windows Python lives in .venv/Scripts, on macOS/Linux in .venv/bin.
venv_python() {
    if [ -x ".venv/Scripts/python.exe" ]; then echo ".venv/Scripts/python.exe";
    elif [ -x ".venv/bin/python" ]; then echo ".venv/bin/python";
    fi
}

# Find a system Python that's at least 3.9. MobaXterm ships an ancient
# python3 that can't install robin_stocks>=3.1 - this skips over it.
find_python() {
    for c in python python3 "py -3"; do
        v=$($c -c 'import sys; print(sys.version_info[0]*100+sys.version_info[1])' 2>/dev/null) || continue
        if [ -n "$v" ] && [ "$v" -ge 309 ] 2>/dev/null; then
            echo "$c"
            return 0
        fi
    done
    return 1
}

VPY=$(venv_python)
if [ -z "$VPY" ]; then
    PY=$(find_python) || { echo "[ERROR] No Python >= 3.9 found. Install it from https://www.python.org/downloads/ and add it to PATH."; exit 1; }
    echo "Creating virtual environment in $(pwd)/.venv using: $PY ..."
    $PY -m venv .venv
    VPY=$(venv_python)
    [ -n "$VPY" ] || { echo "[ERROR] venv creation failed."; exit 1; }
    echo "Installing dependencies (this only happens once) ..."
    "$VPY" -m pip install --upgrade pip >/dev/null
    "$VPY" -m pip install -r requirements.txt
fi

if grep -q "your_robinhood_email@example.com" .env 2>/dev/null; then
    echo "[!] Looks like .env isn't filled in yet. Edit it and set RH_USERNAME / RH_PASSWORD."
    exit 1
fi

"$VPY" robinhood_balance.py
