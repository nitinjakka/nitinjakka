#!/bin/bash
# Pushes the live bot's logs to the GitHub 'live-logs' branch every 60s
# so they can be monitored remotely. Run on the jump server.
# Requires the origin remote to have push credentials (a token in the URL).
set -u
cd "$(dirname "$0")"
git config user.email "bot@server" 2>/dev/null
git config user.name  "kalshi-bot" 2>/dev/null
while true; do
    git add -f kalshi_bot.out kalshi_live_log.csv kalshi_cash.txt \
        >/dev/null 2>&1
    if git commit -q -m "live logs $(date -u '+%FT%H:%M')" >/dev/null 2>&1; then
        git push -q origin HEAD:live-logs >/dev/null 2>&1
    fi
    sleep 60
done
