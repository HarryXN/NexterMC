"""Owner-only persistent switches for prefix and slash commands."""
from __future__ import annotations

import datetime

import discord
from discord import app_commands
from discord.ext import commands

from permissions import is_owner
from utils import storage

def _normalize(value: str) -> str:
    return " ".join(value.casefold().strip().lstrip(",/").split())


def _owner_prefix(ctx: commands.Context) -> bool:
    return is_owner(ctx.author)


def _owner_slash(interaction: discord.Interaction) -> bool:
    return is_owner(interaction.user)


class DisableCommandsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _known_commands(self) -> set[str]:
        names = {_normalize(command.qualified_name) for command in self.bot.walk_commands()}
        names.update(_normalize(command.qualified_name) for command in self.bot.tree.walk_commands())
        return names

    async def _set(self, ctx: commands.Context, command_path: str, enabled: bool) -> None:
        path = _normalize(command_path)
        if not path:
            await ctx.send("Enter a command name, such as `ping`, `nodes`, or `traineetest stop`.", ephemeral=ctx.interaction is not None)
            return
        if path.split(" ", 1)[0] == "disablecmds":
            await ctx.send("🔒 The `disablecmds` controls cannot be disabled, so you can always restore commands.", ephemeral=ctx.interaction is not None)
            return

        known = self._known_commands()
        if path not in known:
            await ctx.send("❓ I couldn't find that command path. Use `,disablecmds list` to view disabled commands, or enter the command's full path (for example `traineetest stop`).", ephemeral=ctx.interaction is not None)
            return

        disabled = getattr(self.bot, "disabled_commands", set())
        currently_disabled = path in disabled
        should_disable = not enabled
        if currently_disabled == should_disable:
            await ctx.send(f"{'⛔ Already disabled' if should_disable else '✅ Already enabled'}: `{path}`.", ephemeral=ctx.interaction is not None)
            return

        await storage.set_disabled_command(path, ctx.author.id, should_disable)
        if should_disable:
            disabled.add(path)
            self.bot.disabled_commands = disabled
            await ctx.send(f"⛔ Disabled **`{path}`** for prefix and slash commands. The help menu now marks it disabled.")
        else:
            disabled.discard(path)
            self.bot.disabled_commands = disabled
            await ctx.send(f"✅ Enabled **`{path}`** for prefix and slash commands. The help menu is updated.")

    @commands.hybrid_group(name="disablecmds", invoke_without_command=True, description="Owner-only runtime command controls.")
    @commands.check(_owner_prefix)
    @app_commands.check(_owner_slash)
    async def disablecmds(self, ctx: commands.Context):
        await ctx.send("🛠️ Use `,disablecmds disable <command>`, `enable <command>`, or `list`.", ephemeral=ctx.interaction is not None)

    @disablecmds.command(name="disable", description="Disable a bot command by its command path.")
    @commands.check(_owner_prefix)
    @app_commands.check(_owner_slash)
    async def disable_command(self, ctx: commands.Context, *, command: str):
        await self._set(ctx, command, enabled=False)

    @disablecmds.command(name="enable", description="Re-enable a previously disabled command.")
    @commands.check(_owner_prefix)
    @app_commands.check(_owner_slash)
    async def enable_command(self, ctx: commands.Context, *, command: str):
        await self._set(ctx, command, enabled=True)

    @disablecmds.command(name="list", description="List disabled bot commands.")
    @commands.check(_owner_prefix)
    @app_commands.check(_owner_slash)
    async def list_disabled(self, ctx: commands.Context):
        disabled = sorted(getattr(self.bot, "disabled_commands", set()))
        embed = discord.Embed(
            title="🛠️ NexterMC · Disabled Commands",
            description="\n".join(f"⛔ `{name}`" for name in disabled) or "✅ No commands are disabled.",
            color=discord.Color.orange() if disabled else discord.Color.green(),
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        embed.set_footer(text="Owner-only · State is saved across bot restarts")
        await ctx.send(embed=embed, ephemeral=ctx.interaction is not None)


async def setup(bot: commands.Bot):
    await bot.add_cog(DisableCommandsCog(bot))
