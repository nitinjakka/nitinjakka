#!/bin/bash
# Install/refresh the Kalshi bot systemd services. Run as root on the
# server AFTER creating /etc/kalshi-bot.env (holds the secrets).
set -eu
cd /opt/nitinjakka

if [ ! -f /etc/kalshi-bot.env ]; then
    echo "ERROR: /etc/kalshi-bot.env is missing. Create it first." >&2
    echo "See deploy/README.md for the template." >&2
    exit 1
fi
chmod 600 /etc/kalshi-bot.env

# Stop any old nohup-based processes so they don't run alongside systemd.
for p in 'watchdog.sh' 'python3 kalshi_bot' 'auto_deploy.sh' 'push_live_logs'; do
    pkill -f "$p" 2>/dev/null || true
done
sleep 2

cp deploy/kalshi-bot.service deploy/kalshi-paper.service \
   deploy/kalshi-autodeploy.service \
   deploy/kalshi-logpush.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now kalshi-bot kalshi-paper kalshi-autodeploy kalshi-logpush

echo "Installed. Status:"
systemctl --no-pager --lines=2 status \
    kalshi-bot kalshi-paper kalshi-autodeploy kalshi-logpush || true
