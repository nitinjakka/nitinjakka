#!/bin/bash
# One-shot deploy for the Kalshi paper bot on your own always-on server.
#
# Usage on the jump server (NOT in the Claude sandbox):
#   git clone <your-repo-url> nitinjakka
#   cd nitinjakka
#   ./deploy.sh 'YYYY-MM-DD HH:MM'   # local end time, e.g. '2026-08-03 20:00'
#
# Requires: python3, pip, git, outbound HTTPS. Notifications keep working
# because the bot POSTs to ntfy.sh (no server-side setup needed).
set -eu
cd "$(dirname "$0")"

END_STR="${1:?usage: ./deploy.sh 'YYYY-MM-DD HH:MM'  (server-local end time)}"
END_TS=$(date -d "$END_STR" +%s)
NOW=$(date +%s)
HOURS=$(awk -v e="$END_TS" -v n="$NOW" 'BEGIN{printf "%.2f", (e-n)/3600}')
if [ "$END_TS" -le "$NOW" ]; then
    echo "End time is in the past. Pick a future time." >&2
    exit 1
fi

# Keep your existing phone alerts unless you override the topic.
export NTFY_TOPIC="${NTFY_TOPIC:-nitin-kalshi-bot-x7q2}"

echo "Checking dependency (requests)..."
if python3 -c 'import requests' 2>/dev/null; then
    echo "  requests already available."
else
    pip install requests --break-system-packages --quiet 2>/dev/null \
        || pip install requests --quiet 2>/dev/null \
        || apt-get install -y python3-requests
fi

# Fresh starting bankroll unless a state file already exists.
[ -f kalshi_cash.txt ] || echo "10" > kalshi_cash.txt

echo "Starting watchdog (auto-restarts the bot) until $END_STR ..."
nohup ./watchdog.sh "$END_TS" >> kalshi_bot.out 2>&1 &

echo "Starting log auto-pusher (git commits every 10 min)..."
nohup ./push_logs.sh "$HOURS" >/dev/null 2>&1 &

sleep 3
if pgrep -f "python3 kalshi_bo[t]" >/dev/null; then
    echo "OK - bot is running. Notifications -> ntfy topic: $NTFY_TOPIC"
else
    echo "Bot not up yet; the watchdog starts it within 60s. Tail with:"
fi
echo "  tail -f kalshi_bot.out"
