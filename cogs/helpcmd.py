"""Interactive, category-based help menu."""
from __future__ import annotations

import datetime
import re

import discord
from discord.ext import commands

from config import BRAND_NAME
from permissions import is_owner

HELP_SECTIONS = {
    "general": {
        "title": "🌟 General Commands",
        "color": discord.Color.blurple(),
        "body": (
            "`ping` — Check the bot's response time.\n"
            "`help` — Open this interactive command guide.\n"
            "`say <message>` — Send a staff announcement.\n"
            "`avgviews <YouTube URL>` — View channel and recent-video analytics.\n"
            "`,moderation enable` / `/moderation enable` · `,moderation disable` / `/moderation disable` — Owner-only moderation switch.\n"
            "`,disablecmds disable|enable <command>` · `,disablecmds list` — Owner-only command controls; changes apply to prefix and slash commands."
        ),
    },
    "moderation": {
        "title": "🛡️ Moderation",
        "color": discord.Color.red(),
        "body": (
            "`warn issue <user> [reason]` — Issue a tracked warning.\n"
            "`warn remove <id>` · `warn list [user]` — Manage warnings.\n"
            "`,banword add <word, phrase, user ID, or mention>` · `,banword remove <term>` · `,banword list` — Manage the server filter.\n"
            "`,banword enable|disable` — Toggle word and restricted-mention filtering. Requires Manage Messages.\n"
            "A ping matching a configured user ID/name or role ID/name is deleted; a repeat within 24h triggers a 1-hour timeout.\n"
            "Restricted-target ping exemptions: roles `1525152379710734389`, `1499066080390283384`, and `1469259811186278597`.\n"
            "`ban <user> [reason]` · `unban <user>` — Manage server bans.\n"
            "`timeout <user> [minutes] [reason]` · `untimeout <user>`\n"
            "`kick <user> [reason]` — Remove a member from the server."
        ),
    },
    "minecraft": {
        "title": "⛏️ Minecraft Administration",
        "color": discord.Color.from_rgb(83, 177, 91),
        "body": (
            "`panel` — Open live server controls, player list, and latency.\n"
            "`whitelist <add|remove> <player> [main|pvp|both]`\n"
            "`broadcast <message>` · `mcban <main|pvp> <player> [reason]`\n"
            "`mckick <main|pvp> <player> [reason]` · `mcunban <main|pvp> <player>`\n"
            "`weather <clear|rain|thunder> [seconds] [main|pvp|both]`\n"
            "`nick <player> <nickname|off> [main|pvp|both]`\n"
            "`mcprofile [username]` — Browse online players or inspect a profile."
        ),
    },
    "summaries": {
        "title": "🧾 Summaries & Invites",
        "color": discord.Color.orange(),
        "body": (
            "`summary` / `summarize` — Short ticket overview.\n"
            "`fullsummary` — Detailed ticket analysis.\n"
            "`,solve` / `/solve run` — Troubleshoot a ticket; rerun after replies. Owner-only until enabled.\n"
            "`,solve enable|disable` / `/solve enable|disable` — Owner controls Staff-role access.\n"
            "`inv <user>` — Audit invite rewards and ticket rules.\n"
            "`invites [user]` · `invited <user>` · `accage <user>`"
        ),
    },
    "diagnostics": {
        "title": "🔧 Diagnostics & Tools",
        "color": discord.Color.teal(),
        "body": (
            "`check` — Scan Python syntax, bot health, and Minecraft reachability.\n"
            "`status` — Live Minecraft server status.\n"
            "`nodes` — Check node reachability with ICMP; show CPU, location, servers, and capacity.\n"
            "`revo <node>` / `revd <node>` — Manually override the node status label.\n"
            "`revm <node>` — Clear a manual online/offline override.\n"
            "`revadd Name | CPU | Location | Host` — Add a monitored node.\n"
            "`revedit Existing Name | CPU | Location | Host` — Update a node.\n"
            "`revremove <node>` — Remove a node from the bot monitor.\n"
            "`nextermc` — Open the bot service control panel (owner only).\n"
            "Use `|` between fields so names and specs can contain spaces. Admin only.\n"
            "`ip` — Minecraft network connection details.\n"
            "`embed` — Open the interactive embed creator.\n"
            "`pyfiles` — List project files."
        ),
    },
    "staff_apply": {
        "title": "📝 Staff Apply",
        "color": discord.Color.from_rgb(75, 112, 235),
        "body": (
            "`startinterview <member>` — Post the Trainee Staff interview in this channel.\n"
            "`ai detect` — Review interview writing indicators (uncertain; not proof).\n"
            "`interview analyze` — Score the interview with the 16-point rubric.\n"
            "`,behaviour <member>` / `/behaviour <member>` — Review their conduct across accessible tickets; evidence-based AI aid, not a verdict.\n"
            "`staffcheck` — List current Trainee, Helper, Moderator, and Senior Moderator roles.\n"
            "`staffactivity` — Rank tracked ticket messages for today (UTC).\n"
            "`staffinfo <member>` — View staff role tenure and tracked activity.\n\n"
            "Interview management and staff reports require server Administrator or bot owner access."
        ),
    },
    "training": {
        "title": "🎓 Trainee Training",
        "color": discord.Color.from_rgb(70, 170, 145),
        "body": (
            '`traineeguide <Payment|Partnership|"Basic Guidelines"> <member>` — Send a compact topic guide in a ticket.\n'
            "`,traineestart` / `/traineestart` — Owner only: start a trainee test (optionally choose a trainee).\n"
            "`,traineetest [trainee]` / `/traineetest start` — Run 6 random scored questions; sends answers and marks to the review channel.\n"
            "`,traineetest practice [trainee]` — Practice run, not sent for approval. `,traineetest topic <category> [trainee]` — Retry 6 questions from one topic.\n"
            "`,traineetest extend <1-10 minutes>` — Trainer adds answer time (up to 30 extra minutes per question). The timer shows time left; expiry skips that question for 0.\n"
            "`,traineetest stop` — Trainee or trainer stops the active run.\n"
            "`,trainee progress [member]` · `,trainee history [member]` · `,trainee checklist [member]` — View progress, attempts, or training checklist.\n"
            "`,trainee review <attempt ID> <approved|retest|needs_practice|hold> [notes]` — Save trainer decision. Review post buttons also approve or retest in the ticket.\n"
            "`,trainee reset <member>` — Owner-only checklist reset; preserves attempt history.\n"
            "Each scored test selects 6 from 40 questions; no exact consecutive repeat. Feedback follows each answer; results are also DM'd to the trainee."
        ),
    },
}


def _is_admin_or_owner(user: discord.abc.User) -> bool:
    return is_owner(user.id) or (
        isinstance(user, discord.Member) and user.guild_permissions.administrator
    )


def _help_embed(section: str, requester: discord.abc.User, disabled_commands=()) -> discord.Embed:
    data = HELP_SECTIONS[section]
    command_formats = "Run commands as `/command` or with the prefix `,command`."
    disabled = {" ".join(str(name).casefold().split()) for name in disabled_commands}

    def is_disabled(entry: str) -> bool:
        path = entry.strip().lstrip(",/").strip().casefold()
        path = re.split(r"\s*[<\[]", path, maxsplit=1)[0].strip()
        if not path:
            return False
        variants = [path]
        parts = path.split()
        if len(parts) > 1 and "|" in parts[-1]:
            variants = [" ".join(parts[:-1] + [choice]) for choice in parts[-1].split("|")]
        return any(any(value == item or value.startswith(item + " ") for item in disabled) for value in variants)

    def annotate_disabled(body: str) -> str:
        def replace(match):
            entry = match.group(1)
            if is_disabled(entry):
                return f"⛔ **{entry.strip()} · DISABLED**"
            return match.group(0)
        return "\n".join(re.sub(r"`([^`]+)`", replace, line) for line in body.splitlines())

    body = annotate_disabled(data["body"])
    embed = discord.Embed(
        title=f"{BRAND_NAME} · {data['title']}",
        description=f"{command_formats}\n\n{body}",
        color=data["color"],
        timestamp=datetime.datetime.now(datetime.timezone.utc),
    )
    if section in {"minecraft", "staff_apply"} and not _is_admin_or_owner(requester):
        embed.description = "🔒 This command section is available to server administrators and the bot owner."
    embed.set_footer(text="✨ Created with care by Harry · Slash and prefix commands · Choose a category below")
    return embed


class HelpCategorySelect(discord.ui.Select):
    def __init__(self, requester_id: int, moderation_enabled: bool, bot):
        options = [
            discord.SelectOption(label="Minecraft", value="minecraft", emoji="⛏️"),
            discord.SelectOption(label="Summaries", value="summaries", emoji="🧾"),
            discord.SelectOption(label="Diagnostics", value="diagnostics", emoji="🔧"),
            discord.SelectOption(label="Staff Apply", value="staff_apply", emoji="📝"),
            discord.SelectOption(label="Trainee Training", value="training", emoji="🎓"),
        ]
        if moderation_enabled:
            options.insert(0, discord.SelectOption(label="Moderation", value="moderation", emoji="🛡️"))
        super().__init__(placeholder="Select more cmds", options=options, row=0)
        self.requester_id = requester_id
        self.bot = bot

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message("This help menu belongs to another user.", ephemeral=True)
            return
        section = self.values[0]
        if section == "moderation" and not getattr(interaction.client, "moderation_enabled", True):
            await interaction.response.send_message("Moderation commands are currently disabled.", ephemeral=True)
            return
        if section == "minecraft" and not _is_admin_or_owner(interaction.user):
            await interaction.response.send_message("Administrator permission is required for Minecraft commands.", ephemeral=True)
            return
        await interaction.response.edit_message(
            embed=_help_embed(section, interaction.user, getattr(self.bot, "disabled_commands", set())),
            view=self.view,
        )


class HelpMenu(discord.ui.View):
    def __init__(self, requester_id: int, moderation_enabled: bool, bot):
        super().__init__(timeout=300)
        self.add_item(HelpCategorySelect(requester_id, moderation_enabled, bot))


class HelpCommandCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name="help")
    async def help_command(self, ctx):
        disabled = getattr(self.bot, "disabled_commands", set())
        await ctx.send(
            embed=_help_embed("general", ctx.author, disabled),
            view=HelpMenu(ctx.author.id, getattr(self.bot, "moderation_enabled", True), self.bot),
        )


async def setup(bot):
    await bot.add_cog(HelpCommandCog(bot))
