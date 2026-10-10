"""Owner-only runtime switch for the moderation command extension."""
from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from config import OWNER_ID
from utils import storage

log = logging.getLogger("nextermc.moderation_control")
MODERATION_EXTENSION = "cogs.moderation"


def _owner_ctx(ctx: commands.Context) -> bool:
    return ctx.author.id == OWNER_ID


def _owner_interaction(interaction: discord.Interaction) -> bool:
    return interaction.user.id == OWNER_ID


class ModerationControl(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_group(name="moderation", invoke_without_command=True, description="Enable or disable moderation commands (owner only).")
    async def moderation(self, ctx: commands.Context):
        if not _owner_ctx(ctx):
            await ctx.send("🔒 Only the bot owner can manage moderation commands.")
            return
        await ctx.send("Use `,moderation enable` or `,moderation disable` (also available as slash commands).")

    @moderation.command(name="disable", description="Disable moderation commands and hide their help section.")
    @commands.check(_owner_ctx)
    @app_commands.check(_owner_interaction)
    async def disable_moderation(self, ctx: commands.Context):
        await self._set_enabled(ctx, False)

    @moderation.command(name="enable", description="Enable moderation commands and show their help section.")
    @commands.check(_owner_ctx)
    @app_commands.check(_owner_interaction)
    async def enable_moderation(self, ctx: commands.Context):
        await self._set_enabled(ctx, True)

    async def _set_enabled(self, ctx: commands.Context, enabled: bool) -> None:
        if ctx.interaction:
            await ctx.defer()

        current = bool(getattr(self.bot, "moderation_enabled", True))
        if current == enabled:
            await ctx.send(f"{'✅ Moderation is already enabled.' if enabled else '⛔ Moderation is already disabled.'}")
            return

        if enabled:
            try:
                await self.bot.load_extension(MODERATION_EXTENSION)
                await storage.set_feature_flag("moderation", True)
            except Exception:
                if self.bot.get_cog("Moderation") is not None:
                    await self.bot.unload_extension(MODERATION_EXTENSION)
                log.exception("Could not enable moderation commands")
                await ctx.send("❌ Could not enable moderation. Check the bot logs.")
                return
            self.bot.moderation_enabled = True
            response = "✅ Moderation enabled. Its commands and help section are available again."
        else:
            try:
                await storage.set_feature_flag("moderation", False)
                self.bot.moderation_enabled = False
                if self.bot.get_cog("Moderation") is not None:
                    await self.bot.unload_extension(MODERATION_EXTENSION)
            except Exception:
                # Keep persisted/runtime state aligned if unloading fails.
                await storage.set_feature_flag("moderation", True)
                self.bot.moderation_enabled = True
                log.exception("Could not disable moderation commands")
                await ctx.send("❌ Could not disable moderation. Check the bot logs.")
                return
            response = "⛔ Moderation disabled. Its commands are unavailable and the help section is hidden."

        try:
            await self.bot.tree.sync()
        except Exception:
            log.exception("Moderation changed locally, but global slash-command sync failed")
            response += "\n⚠️ Prefix commands and local checks are updated, but Discord slash-command sync failed; retry after checking the bot logs."
        await ctx.send(response)


async def setup(bot: commands.Bot):
    await bot.add_cog(ModerationControl(bot))
