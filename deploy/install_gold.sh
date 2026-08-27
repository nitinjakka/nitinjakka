#!/bin/bash
# Install the GOLD bot + log pusher. The old crypto bots (kalshi-bot,
# kalshi-paper) and auto-deploy stay OFF; code updates are a manual
# 'git fetch && git reset --hard origin/claude/kalshi-api-access-o5hnen'
# followed by 'systemctl restart kalshi-gold'.
# Run as root on the server after pulling latest code.
set -eu
cd /opt/nitinjakka

if [ ! -f /etc/kalshi-bot.env ]; then
    echo "ERROR: /etc/kalshi-bot.env is missing (Kalshi API creds)." >&2
    exit 1
fi
chmod 600 /etc/kalshi-bot.env

cp deploy/kalshi-gold.service deploy/kalshi-logpush.service \
   /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now kalshi-gold kalshi-logpush

echo "Installed. Status:"
systemctl --no-pager --lines=3 status kalshi-gold || true
