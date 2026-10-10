# Staff application and reporting commands

This update adds `,startinterview @member`, `,ai detect`, `,interview analyze`,
`,staffcheck`, `,staffactivity`, and `,staffinfo @member`, plus the Staff Apply
category in `,help`.

## Install

Upload `staff-application-and-tools-update.zip` to `/root/nextermc-bot/`, then:

```bash
cd /root/nextermc-bot
mkdir -p backups
cp -a cogs/helpcmd.py "backups/helpcmd.py.before-staff-tools.$(date +%Y%m%d-%H%M%S)"
unzip -o staff-application-and-tools-update.zip -d /root/nextermc-bot
systemctl restart nextermc-bot.service
```

Commands are restricted to the bot owner or Discord administrators. The
existing summaries-only role restriction remains in place. `startinterview`
also needs the bot's Manage Messages permission in that channel to remove the
invocation after posting.

## Tracking limits

- Role assignment timestamps and activity tracking begin when this update is
  installed. Discord does not provide the bot a complete historical role
  assignment ledger, so earlier dates show as not tracked.
- Discord does not expose a member's true last-seen time to this bot. `staffinfo`
  reports the most recent tracked message time and channel instead; it does not
  store message contents.
- `staffactivity` scans accessible ticket text-channel and active-thread history
  back to UTC midnight each time it runs. Ticket channels are detected using
  the configured Free/Paid ticket categories and channel/category names
  containing `ticket` or `support`; inaccessible channels are disclosed.
- `staffinfo` message metadata is collected after installation. Only message
  time, channel, and counts are saved; message contents are not stored.
- AI grading is an assistive recommendation, not a substitute for a human
  reviewer. Text-only AI detection is uncertain and must not be treated as proof
  of AI use or the sole reason to reject/blacklist an applicant.

The scored questions are Q1-Q6 and Q11-Q13, for 16 points total. Q7-Q10 are
general questions and are unscored. Q6 applies the supplied invite deductions:
17 - 4 - 6 - 4 - 2 = 1 valid invite; no-bio/PFP and onboarding do not deduct.
