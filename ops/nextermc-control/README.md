# Owner-only NexterMC service controls

This adds `,nextermc`, a private Discord DM panel restricted to owner ID
`1006250810142883851`. The separate root-owned controller remains running when
the bot is stopped. Its Unix socket accepts only `status`, `start`, `stop`, and
`restart` for the fixed `nextermc-bot.service` unit. It does not accept shell
commands, paths, or arbitrary systemd unit names.

## Install on the VPS

Upload `nextermc-owner-control-update.zip` to `/root/nextermc-bot/`. Then run:

```bash
cd /root/nextermc-bot
mkdir -p backups
cp -a cogs/helpcmd.py "backups/helpcmd.py.before-nextermc.$(date +%Y%m%d-%H%M%S)"
unzip -o nextermc-owner-control-update.zip -d /root/nextermc-bot
install -d -m 0755 /opt/nextermc-control
install -m 0755 ops/nextermc-control/controller.py /opt/nextermc-control/controller.py
install -m 0644 ops/nextermc-control/nextermc-control.service /etc/systemd/system/nextermc-control.service
systemctl daemon-reload
systemctl enable --now nextermc-control.service
systemctl restart nextermc-bot.service
```

The bot already auto-loads Python files in `cogs/`; no new Python package is
required. Check controller startup without revealing environment variables:

```bash
systemctl --no-pager --full status nextermc-control.service
test -S /run/nextermc-control.sock && echo "Controller socket ready"
```

Then send `,nextermc` in Discord. The panel is delivered in a DM. Allow DMs from
the server before invoking it. In a server channel, the command confirms that
the panel was sent by DM. Stop and Restart require a second confirmation; the
controller posts the completed result through Discord after systemd finishes,
even when the bot service is stopped or restarting. The controller needs HTTPS
connectivity to `discord.com` for that final confirmation.

## Rollback

```bash
systemctl disable --now nextermc-control.service
rm -f /etc/systemd/system/nextermc-control.service
rm -f /opt/nextermc-control/controller.py
rm -f /root/nextermc-bot/cogs/nextermc.py
systemctl daemon-reload
systemctl restart nextermc-bot.service
```

If `,nextermc` does not load, inspect the bot journal with
`journalctl -u nextermc-bot.service -n 80 --no-pager`. Do not paste `.env` or
API keys into chat.
