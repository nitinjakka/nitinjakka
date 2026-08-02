#!/bin/bash
# Keeps the paper bot alive: checks every 60s, restarts it if dead.
# Usage: ./watchdog.sh <end_epoch>
set -u
cd "$(dirname "$0")"
END_TS="${1:?usage: watchdog.sh <end_epoch>}"

while [ "$(date +%s)" -lt "$END_TS" ]; do
    if ! pgrep -f "python3 kalshi_bo[t]" >/dev/null; then
        # Resume with the last known cash balance (default 10).
        cash=$(cat kalshi_cash.txt 2>/dev/null)
        case "$cash" in
            ''|*[!0-9.]*) cash=10 ;;
        esac
        rem_h=$(awk -v e="$END_TS" -v n="$(date +%s)" \
            'BEGIN{h=(e-n)/3600; if (h<0.05) h=0.05; printf "%.2f", h}')
        echo "[watchdog $(date -u '+%H:%M:%S') UTC] bot dead - restarting: cash=$cash hours=$rem_h" >> kalshi_bot.out
        nohup python3 kalshi_bot.py --cash "$cash" --hours "$rem_h" \
            --log kalshi_paper_log.csv >> kalshi_bot.out 2>&1 &
    fi
    sleep 60
done
