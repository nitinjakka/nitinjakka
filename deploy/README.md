# Systemd setup (survives reboots and new SSH sessions)

Replaces the manual nohup + watchdog.sh with three systemd services:

- **kalshi-bot** — the live trading bot (systemd restarts it on exit/crash,
  so it is its own watchdog; also restarts it after a code self-update).
- **kalshi-autodeploy** — polls GitHub every 2 min and resets to new code.
- **kalshi-logpush** — pushes logs to the `live-logs` branch every 60s.

Credentials live in `/etc/kalshi-bot.env` (root-only, NOT in git).

## One-time install (run as root on the server)

1. Create the secrets file:

```bash
cat > /etc/kalshi-bot.env <<'EOF'
KALSHI_API_KEY_ID=66ddc839-5676-4bc4-b305-0bcdcf9911df
KALSHI_PRIVATE_KEY_PATH=/root/.kalshi/kalshi_key.pem
KALSHI_LIVE_CONFIRM=YES
KALSHI_MAX_ORDER_USD=0
NTFY_TOPIC=nitin-kalshi-bot-x7q2
EOF
chmod 600 /etc/kalshi-bot.env
```

2. Get the latest code and install the services:

```bash
cd /opt/nitinjakka
git fetch -q origin claude/kalshi-api-access-o5hnen
git reset --hard -q origin/claude/kalshi-api-access-o5hnen
bash deploy/install_systemd.sh
```

## Everyday commands

```bash
systemctl status kalshi-bot          # is it running?
journalctl -u kalshi-bot -f          # live service logs
tail -f /opt/nitinjakka/kalshi_bot.out   # bot decision log
systemctl restart kalshi-bot         # manual restart
systemctl stop kalshi-bot            # pause trading
```

After a server reboot, all three services start automatically — no
re-exporting env vars, no manual restart.

## Notes

- Changing `kalshi_bot.py` auto-deploys (bot self-restarts). Changing
  `auto_deploy.sh` or `push_live_logs.sh` needs
  `systemctl restart kalshi-autodeploy` / `kalshi-logpush` once.
- To change a credential or the order cap, edit `/etc/kalshi-bot.env`
  then `systemctl restart kalshi-bot`.
