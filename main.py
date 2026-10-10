# main.py
import logging
import os

from dotenv import load_dotenv

load_dotenv()

import discord
from discord.ext import commands, tasks

from config import BRAND_NAME, CRASH_LOG_CHANNEL_ID, SUMMARY_ONLY_ROLE_ID
from logs import configure_discord_crash_logging
from permissions import is_owner, is_staff_member
from utils import storage
from utils.storage import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
log = logging.getLogger("nextermc.main")

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

def _normalize_command_path(value: str) -> str:
    return " ".join(value.casefold().strip().lstrip(",/").split())


def _is_command_disabled(path: str, disabled: set[str]) -> bool:
    path = _normalize_command_path(path)
    if not path or path.split(" ", 1)[0] == "disablecmds":
        return False
    return any(path == item or path.startswith(item + " ") for item in disabled)


class NexterMCTree(discord.app_commands.CommandTree):
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.type is discord.InteractionType.autocomplete:
            path = _normalize_command_path(str((interaction.data or {}).get("name", "")))
            if _is_command_disabled(path, getattr(self.client, "disabled_commands", set())):
                await interaction.response.autocomplete([])
                return False
            return True

        data = interaction.data or {}
        names = [str(data.get("name", ""))]
        options = data.get("options", [])
        while isinstance(options, list):
            child = next((item for item in options if item.get("type") in (1, 2)), None)
            if child is None:
                break
            names.append(str(child.get("name", "")))
            options = child.get("options", [])
        path = _normalize_command_path(" ".join(names))
        if _is_command_disabled(path, getattr(self.client, "disabled_commands", set())):
            if not interaction.response.is_done():
                await interaction.response.send_message(f"⛔ `/{path}` is currently disabled by the bot owner.", ephemeral=True)
            return False
        return True


bot = commands.Bot(command_prefix=",", intents=intents, help_command=None, tree_cls=NexterMCTree)
TOKEN = os.getenv("DISCORD_TOKEN")
_guild_command_cleanup_done = False
_presence_index = 0
PRESENCE_ROTATION = (
    discord.Activity(
        type=discord.ActivityType.watching,
        name="the NexterCloud Network",
        state="✨ Created by Harry",
    ),
    discord.Activity(
        type=discord.ActivityType.playing,
        name="Minecraft • /status",
        state="🌐 NexterMC Network",
    ),
    discord.Activity(
        type=discord.ActivityType.listening,
        name="your support tickets",
        state="🛠️ Staff tools • /help",
    ),
    discord.Activity(
        type=discord.ActivityType.watching,
        name="NexterCloud nodes • /nodes",
        state="⚡ Live network monitor",
    ),
)
ADMIN_MINECRAFT_COMMANDS = {
    "whitelist", "broadcast", "mcban", "mckick", "mcunban", "weather", "nick", "mcprofile", "help",
    "nodes", "revo", "revd", "revm", "revadd", "revremove", "revedit"
}
TRAINING_COMMANDS = {"help", "traineeguide", "traineetest", "trainee"}
TRAINING_ROLE_IDS = {
    1395064815428309066,  # Trainee
    1538892615552868403,  # Helper
    1469259811186278597,  # Moderator
    1485114830313754694,  # Senior Moderator
    1525300305246425240,  # Staff
}


# ==========================================
# GLOBAL PERMISSION CHECK (APPLIES TO ALL COMMANDS)
# ==========================================
@bot.check
async def globally_enforce_owner_or_staff(ctx: commands.Context) -> bool:
    command_path = getattr(ctx.command, "qualified_name", "")
    if _is_command_disabled(command_path, getattr(bot, "disabled_commands", set())):
        raise commands.CheckFailure(f"⛔ `,{command_path}` is currently disabled by the bot owner.")
    if is_owner(ctx.author.id):
        return True

    author_role_ids = {role.id for role in getattr(ctx.author, "roles", [])}
    command_root = getattr(ctx.command, "qualified_name", "").split(" ", 1)[0]
    if command_root in TRAINING_COMMANDS and author_role_ids.intersection(TRAINING_ROLE_IDS):
        return True
    if (
        command_root in TRAINING_COMMANDS
        and getattr(getattr(ctx.author, "guild_permissions", None), "administrator", False)
    ):
        return True

    if SUMMARY_ONLY_ROLE_ID in author_role_ids:
        if ctx.command and (
            ctx.command.name in {"summarize", "fullsummary"}
            or getattr(ctx.command, "qualified_name", "").split(" ", 1)[0] == "solve"
        ):
            return True
        raise commands.CheckFailure(
            "❌ This staff role can only use ticket summaries and the Solve assistant when owner-enabled."
        )

    # Admin-only Minecraft commands perform their own administrator check.
    # This narrow exception lets Discord admins reach those checks without
    # granting them access to the rest of the bot's staff commands.
    if (
        ctx.command
        and ctx.command.name in ADMIN_MINECRAFT_COMMANDS
        and getattr(getattr(ctx.author, "guild_permissions", None), "administrator", False)
    ):
        return True

    if is_staff_member(ctx):
        return True
    raise commands.CheckFailure("❌ You don't have permission to use this command!")


@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError):
    # Unwrap discord.py's wrapper so we react to the real error type.
    error = getattr(error, "original", error)
    # Hybrid slash failures are answered by the CommandTree error handler below.
    if getattr(ctx, "interaction", None) is not None:
        return

    if isinstance(error, commands.CheckFailure):
        await ctx.send(str(error) or "❌ You don't have permission to use this command!", delete_after=5)
        return

    if isinstance(error, commands.CommandOnCooldown):
        await ctx.send(
            f"⏳ That command is on cooldown — try again in {error.retry_after:.0f}s.",
            delete_after=5,
        )
        return

    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Missing argument: `{error.param.name}`. Check `,help` for usage.", delete_after=8)
        return

    if isinstance(error, commands.BadArgument):
        await ctx.send("❌ Couldn't understand one of the arguments you gave. Check `,help` for usage.", delete_after=8)
        return

    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ I don't have the Discord permissions needed to do that.", delete_after=8)
        return

    if isinstance(error, commands.CommandNotFound):
        return  # silent — don't spam a 10k-member server with "unknown command" noise

    # Anything else: log the full traceback server-side, tell the user
    # something generic. Never dump raw exception text into a public
    # channel — it can leak internal paths/config details.
    command_name = getattr(ctx.command, "qualified_name", "?")
    error_info = (type(error), error, error.__traceback__) if error.__traceback__ else None
    log.error(
        "Unhandled error in command %s (user_id=%s channel_id=%s)",
        command_name,
        getattr(ctx.author, "id", "?"),
        getattr(ctx.channel, "id", "?"),
        exc_info=error_info,
    )
    await ctx.send("❌ Something went wrong running that command. The issue has been logged.", delete_after=8)


@bot.before_invoke
async def defer_slash_command(ctx: commands.Context):
    """Acknowledge slash commands before slow API or transcript work begins."""
    interaction = getattr(ctx, "interaction", None)
    if interaction is not None and not interaction.response.is_done():
        await interaction.response.defer(thinking=True)


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: Exception):
    """Keep slash-command failures private and log full details server-side."""
    # Old Discord command registrations can still emit autocomplete interactions
    # briefly after a sync failure. Autocomplete requires response type 8, not a
    # normal message response (type 4).
    if interaction.type is discord.InteractionType.autocomplete:
        if not interaction.response.is_done():
            await interaction.response.autocomplete([])
        return

    original = getattr(error, "original", error)
    if isinstance(original, (commands.CheckFailure, discord.app_commands.CheckFailure)):
        message = str(original) or "❌ You don't have permission to use this command."
    elif isinstance(original, (commands.MissingPermissions, discord.app_commands.MissingPermissions)):
        message = "❌ I don't have the Discord permissions needed to do that."
    elif isinstance(original, commands.MissingRequiredArgument):
        message = "❌ A required option is missing. Review this command's options and try again."
    else:
        command = getattr(interaction, "command", None)
        log.error(
            "Unhandled slash command error in %s (user_id=%s channel_id=%s)",
            getattr(command, "qualified_name", "?"),
            getattr(interaction.user, "id", "?"),
            getattr(interaction.channel, "id", "?"),
            exc_info=(type(original), original, original.__traceback__),
        )
        message = "❌ Something went wrong running that command. The issue has been logged."

    try:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    except discord.HTTPException:
        log.debug("Could not respond to failed slash interaction %s", interaction.id, exc_info=True)


def normalize_slash_descriptions():
    """Keep command summaries within Discord's 100-character limit."""
    def normalize(command):
        description = getattr(command, "description", None)
        if isinstance(description, str) and len(description) > 100:
            command.description = description[:97].rstrip() + "..."
            log.warning("Shortened slash description for /%s", getattr(command, "qualified_name", command.name))
        for child in getattr(command, "commands", ()):
            normalize(child)

    for command in bot.tree.get_commands():
        normalize(command)


async def load_cogs():
    cog_folder = "./cogs"
    if not os.path.exists(cog_folder):
        log.warning("Directory %s not found!", cog_folder)
        return

    for filename in sorted(os.listdir(cog_folder)):
        if not filename.endswith(".py") or filename.startswith("_"):
            continue
        module_name = filename[:-3]
        if not module_name.isidentifier():
            log.warning("Skipping cog file with an invalid Python module name: %s", filename)
            continue
        module_path = f"cogs.{module_name}"
        if module_name == "moderation" and not getattr(bot, "moderation_enabled", True):
            log.info("Moderation commands are disabled; skipping extension load.")
            continue
        try:
            await bot.load_extension(module_path)
            log.info("Loaded extension: %s", module_path)
        except Exception:
            log.exception("Failed to load %s", module_path)


@tasks.loop(seconds=45)
async def rotate_presence():
    global _presence_index
    activity = PRESENCE_ROTATION[_presence_index]
    _presence_index = (_presence_index + 1) % len(PRESENCE_ROTATION)
    try:
        await bot.change_presence(status=discord.Status.online, activity=activity)
    except discord.HTTPException:
        log.exception("Could not update the bot's Discord presence")


@rotate_presence.before_loop
async def before_presence_rotation():
    await bot.wait_until_ready()


@bot.event
async def on_ready():
    global _guild_command_cleanup_done
    if not rotate_presence.is_running():
        rotate_presence.start()
    log.info("Logged in as %s (%s)", bot.user, bot.user.id)
    log.info("In %d guild(s), bot is ready.", len(bot.guilds))
    # Remove stale guild-scoped copies. The canonical command set is global;
    # keeping both scopes makes Discord display every command twice.
    if not _guild_command_cleanup_done:
        for guild in bot.guilds:
            try:
                bot.tree.clear_commands(guild=guild)
                synced_guild = await bot.tree.sync(guild=guild)
                log.info("Removed guild-specific slash commands from %s (%s); remaining=%d", guild.name, guild.id, len(synced_guild))
            except Exception:
                log.exception("Could not remove duplicate guild slash commands in guild %s", guild.id)
        _guild_command_cleanup_done = True


@bot.event
async def setup_hook():
    configure_discord_crash_logging(bot)
    log.info("Discord crash-log forwarding configured for channel %s", CRASH_LOG_CHANNEL_ID)
    await init_db()
    bot.moderation_enabled = await storage.get_feature_flag("moderation", default=True)
    bot.disabled_commands = await storage.get_disabled_commands()
    await load_cogs()
    normalize_slash_descriptions()
    try:
        synced = await bot.tree.sync()
        log.info("Synced %d global slash command(s).", len(synced))
    except Exception:
        log.exception("Failed to sync global slash commands")


def main():
    if not TOKEN:
        log.error("DISCORD_TOKEN environment variable is missing! Refusing to start.")
        return
    bot.run(TOKEN, log_handler=None)  # logging already configured above


if __name__ == "__main__":
    main()
