# Node monitor crash and Application API diagnostics

This update fixes the `_detail` NameError in the node embed and reports a
sanitized Application API failure reason (for example HTTP 401/403, panel
timeout, or DNS/TLS failure). It never logs or displays the API key.

Upload `nodes-api-diagnostics-fix.zip` to `/root/nextermc-bot/`, then run on the
VPS:

```bash
cd /root/nextermc-bot
mkdir -p backups
cp -a cogs/nodes.py "backups/nodes.py.before-api-diagnostics.$(date +%Y%m%d-%H%M%S)"
unzip -o nodes-api-diagnostics-fix.zip -d /root/nextermc-bot
systemctl restart nextermc-bot.service
```

Run `,nodes` again. If the panel still shows unavailable, inspect the exact
sanitized reason with:

```bash
journalctl -u nextermc-bot.service -n 120 --no-pager | grep -E 'Application API|nextermc.nodes'
```

Interpretation:

- `HTTP 401`: invalid/expired key or the wrong key type. The Application key
  must be used in `PANEL_APP_API_KEY`; a `ptlc_` client key is not an
  Application API key.
- `HTTP 403`: enable **Nodes: Read** for that Application API key. Since this
  monitor requests allocation and server relationships too, grant the matching
  read permissions if the panel rejects those included relationships.
- `PANEL_APP_API_KEY missing at bot startup`: add the variable to
  `/root/nextermc-bot/.env` and restart the service.
- DNS/connection or timeout: the VPS could not reach/resolve the panel then;
  this is separate from API-key validity.

Do not paste `.env`, API keys, or Authorization headers into chat. Share only
the filtered log lines above.
