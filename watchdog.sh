#!/bin/bash
# Keeps the bot alive: checks every 60s, restarts it if dead.
# Usage: ./watchdog.sh <end_epoch>
# Env:
#   BOT_EXTRA_ARGS   extra args for the bot, e.g. "--live" (default none)
#   LOG_FILE         trade CSV (default kalshi_paper_log.csv)
set -u
cd "$(dirname "$0")"
END_TS="${1:?usage: watchdog.sh <end_epoch>}"
EXTRA="${BOT_EXTRA_ARGS:-}"
LOG_FILE="${LOG_FILE:-kalshi_paper_log.csv}"

while [ "$(date +%s)" -lt "$END_TS" ]; do
    if ! pgrep -f "python3 kalshi_bo[t]" >/dev/null; then
        # Paper resumes from the saved balance; live ignores --cash.
        cash=$(cat kalshi_cash.txt 2>/dev/null)
        case "$cash" in
            ''|*[!0-9.]*) cash=10 ;;
        esac
        rem_h=$(awk -v e="$END_TS" -v n="$(date +%s)" \
            'BEGIN{h=(e-n)/3600; if (h<0.05) h=0.05; printf "%.2f", h}')
        echo "[watchdog $(date -u '+%H:%M:%S') UTC] bot dead - restarting: cash=$cash hours=$rem_h args=$EXTRA" >> kalshi_bot.out
        nohup python3 kalshi_bot.py --cash "$cash" --hours "$rem_h" \
            --log "$LOG_FILE" $EXTRA >> kalshi_bot.out 2>&1 &
    fi
    sleep 60
done
