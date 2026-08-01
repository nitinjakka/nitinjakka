#!/bin/bash
# Auto-push of the paper-trading bot logs to the remote branch every
# 10 minutes. Runs alongside kalshi_bot.py; exits after the given
# number of hours.
set -u
cd "$(dirname "$0")"
HOURS="${1:-24}"
BRANCH="claude/kalshi-api-access-o5hnen"

for ((i = 1; i <= HOURS * 6; i++)); do
    sleep 600
    git add kalshi_bot.out kalshi_paper_log.csv 2>/dev/null
    if ! git diff --cached --quiet; then
        git commit -q -m "Update paper-trading logs (hourly auto-push)"
        for backoff in 2 4 8 16 0; do
            git push -q -u origin "$BRANCH" && break
            [ "$backoff" -eq 0 ] || sleep "$backoff"
        done
    fi
done
