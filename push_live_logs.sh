#!/bin/bash
# Push live logs to the 'live-logs' branch via a DEDICATED worktree, so
# the main working tree/branch is never polluted (no divergence when
# code is pulled). Run on the jump server.
set -u
REPO="$(cd "$(dirname "$0")" && pwd)"
WT="/opt/kalshi-logs"
export GIT_TERMINAL_PROMPT=0

# One-time: create the logs worktree checked out on live-logs.
if [ ! -e "$WT/.git" ]; then
    git -C "$REPO" fetch -q origin live-logs 2>/dev/null
    git -C "$REPO" worktree add -f -B live-logs "$WT" origin/live-logs \
        2>/dev/null \
      || git -C "$REPO" worktree add -f "$WT" live-logs 2>/dev/null
fi
git -C "$WT" config user.email "bot@server" 2>/dev/null
git -C "$WT" config user.name  "kalshi-bot" 2>/dev/null

LOGS="kalshi_bot.out kalshi_live_log.csv kalshi_cash.txt \
kalshi_paper.out kalshi_paper_log.csv kalshi_paper_cash.txt"
while true; do
    for f in $LOGS; do
        [ -f "$REPO/$f" ] && cp -f "$REPO/$f" "$WT/$f" 2>/dev/null
    done
    git -C "$WT" add -f $LOGS >/dev/null 2>&1
    if git -C "$WT" commit -q -m "live logs $(date -u +%FT%H:%M)" \
            >/dev/null 2>&1; then
        git -C "$WT" push -q origin live-logs >/dev/null 2>&1
    fi
    sleep 60
done
