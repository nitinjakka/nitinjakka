#!/bin/bash
# Auto-deploy: poll GitHub every 2 min; when new code lands on the
# branch, reset the working tree to it. The bot notices the new commit
# and restarts itself at the next safe window boundary (the watchdog
# brings it back on the new code). Log files are gitignored, so the
# reset never disturbs them.
set -u
cd "$(dirname "$0")"
BR="claude/kalshi-api-access-o5hnen"
export GIT_TERMINAL_PROMPT=0

while true; do
    git fetch -q origin "$BR" 2>/dev/null
    LOCAL=$(git rev-parse HEAD 2>/dev/null)
    REMOTE=$(git rev-parse "origin/$BR" 2>/dev/null)
    if [ -n "$REMOTE" ] && [ "$LOCAL" != "$REMOTE" ]; then
        git reset --hard "origin/$BR" >/dev/null 2>&1
        echo "[autodeploy $(date -u '+%FT%H:%M') UTC] pulled ${REMOTE:0:7}" \
            >> kalshi_bot.out
    fi
    sleep 120
done
