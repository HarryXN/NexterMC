"""Persistent per-server word and phrase filter."""
from __future__ import annotations

import logging
import re
from datetime import timedelta

import discord
from discord.ext import commands

from permissions import has_permissions_or_owner
from utils import storage

log = logging.getLogger("nextermc.banword")
_FLAG_PREFIX = "banword_filter:"
_MAX_TERM_LENGTH = 100
_RESTRICTED_PING_EXEMPT_ROLE_IDS = {
    1525152379710734389,
    1499066080390283384,
    1469259811186278597,
}


def _clean_term(value: str) -> str:
    return " ".join(value.strip().casefold().split())


def _matches(content: str, term: str) -> bool:
    normalized = " ".join(content.casefold().split())
    pattern = re.compile(r"(?<!\w)" + re.escape(term) + r"(?!\w)", re.UNICODE)
    return pattern.search(normalized) is not None


class BanwordCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._terms: dict[int, list[str]] = {}
        self._enabled: dict[int, bool] = {}

    async def _get_terms(self, guild_id: int) -> list[str]:
        if guild_id not in self._terms:
            self._terms[guild_id] = await storage.list_banned_words(guild_id)
        return self._terms[guild_id]

    async def _is_enabled(self, guild_id: int) -> bool:
        if guild_id not in self._enabled:
            self._enabled[guild_id] = await storage.get_feature_flag(
                f"{_FLAG_PREFIX}{guild_id}", default=True
            )
        return self._enabled[guild_id]

    @staticmethod
    def _mentions_filtered_target(message: discord.Message, terms: list[str]) -> bool:
        filtered = set(terms)
        for member in message.mentions:
            candidates = {
                str(member.id),
                f"<@{member.id}>",
                f"<@!{member.id}>",
                _clean_term(member.name or ""),
                _clean_term(member.display_name or ""),
                _clean_term(getattr(member, "global_name", None) or ""),
                _clean_term("@" + (member.name or "")),
                _clean_term("@" + (member.display_name or "")),
            }
            if filtered.intersection(candidates):
                return True
        for role in message.role_mentions:
            candidates = {
                str(role.id),
                f"<@&{role.id}>",
                _clean_term(role.name or ""),
                _clean_term("@" + (role.name or "")),
            }
            if filtered.intersection(candidates):
                return True
        return False

    async def _handle_filtered_target_ping(self, message: discord.Message) -> None:
        try:
            await message.delete()
        except discord.NotFound:
            return
        except discord.Forbidden:
            log.warning("Cannot remove a ping to a filtered target in channel %s", message.channel.id)
            return
        except discord.HTTPException:
            log.exception("Failed to remove a ping to a filtered target in channel %s", message.channel.id)
            return

        strikes = await storage.record_restricted_mention(message.guild.id, message.author.id)
        member = message.author
        timed_out = False
        if strikes >= 2 and isinstance(member, discord.Member):
            # Discord prevents timing out administrators, guild owners, and
            # members whose roles outrank the bot. Handle that without claiming
            # a timeout succeeded when it did not.
            bot_member = message.guild.me
            if (
                member != message.guild.owner
                and not member.guild_permissions.administrator
                and bot_member is not None
                and bot_member.guild_permissions.moderate_members
                and bot_member.top_role > member.top_role
            ):
                try:
                    await member.timeout(
                        timedelta(hours=1),
                        reason="Repeatedly pinged a target on the server's banword list after being warned",
                    )
                    timed_out = True
                except discord.Forbidden:
                    log.warning("Bot cannot timeout repeat filtered-target pinger %s in guild %s", member.id, message.guild.id)
                except discord.HTTPException:
                    log.exception("Failed to timeout repeat filtered-target pinger %s", member.id)

        if timed_out:
            title = "⏱️ One-hour timeout applied"
            detail = f"{member.mention}, your message was removed. Repeating this restricted-target ping within 24 hours after a warning resulted in this 1-hour timeout."
            color = discord.Color.red()
        elif strikes >= 2:
            title = "⚠️ Repeated restricted-target ping removed"
            detail = f"{member.mention}, your message was removed, but I couldn’t apply the 1-hour timeout. Please stop pinging this restricted target and contact a moderator if needed."
            color = discord.Color.orange()
        else:
            title = "⚠️ Please don’t ping this target repeatedly"
            detail = f"{member.mention}, your message was removed. Please don’t ping this restricted target again within 24 hours; another ping will result in a **1-hour timeout**."
            color = discord.Color.orange()
        warning = discord.Embed(title=title, description=detail, color=color)
        warning.set_footer(text="NexterMC · Automated restricted-mention rule")
        try:
            warning_message = await message.channel.send(
                embed=warning,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            await warning_message.delete(delay=10)
        except discord.Forbidden:
            log.warning("Cannot post restricted-mention warning in channel %s", message.channel.id)
        except discord.HTTPException:
            log.exception("Failed to post restricted-mention warning in channel %s", message.channel.id)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.guild is None or message.author.bot or message.webhook_id:
            return
        # Keep the moderation controls usable even if an administrator's input
        # contains the term they are trying to add or remove.
        if message.content.casefold().lstrip().startswith(",banword "):
            return
        if not await self._is_enabled(message.guild.id):
            return

        terms = await self._get_terms(message.guild.id)
        if self._mentions_filtered_target(message, terms):
            author = message.author
            if isinstance(author, discord.Member) and any(
                role.id in _RESTRICTED_PING_EXEMPT_ROLE_IDS for role in author.roles
            ):
                # These roles may ping configured restricted targets. The
                # regular banned-word filter still applies to their messages.
                return
            await self._handle_filtered_target_ping(message)
            return
        match = next((term for term in terms if _matches(message.content, term)), None)
        if match is None:
            return

        try:
            await message.delete()
        except discord.NotFound:
            return
        except discord.Forbidden:
            log.warning(
                "Cannot remove a filtered message: missing Manage Messages in guild %s channel %s",
                message.guild.id,
                message.channel.id,
            )
            return
        except discord.HTTPException:
            log.exception("Failed to remove a filtered message in channel %s", message.channel.id)
            return

        warning = discord.Embed(
            title="🛡️ Please keep the chat respectful",
            description=f"{message.author.mention}, that message was removed by the server filter. Please don’t use that word or phrase again.",
            color=discord.Color.orange(),
        )
        warning.set_footer(text="NexterMC · Automated word filter")
        try:
            warning_message = await message.channel.send(
                embed=warning,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            await warning_message.delete(delay=8)
        except discord.Forbidden:
            log.warning("Cannot post word-filter warning in channel %s", message.channel.id)
        except discord.HTTPException:
            log.exception("Failed to post word-filter warning in channel %s", message.channel.id)

    @commands.hybrid_group(
        name="banword",
        invoke_without_command=True,
        description="Manage this server's word and phrase filter.",
    )
    @has_permissions_or_owner(manage_messages=True)
    async def banword(self, ctx: commands.Context):
        if ctx.guild is None:
            await ctx.send("This command can only be used in a server.", ephemeral=ctx.interaction is not None)
            return
        terms = await self._get_terms(ctx.guild.id)
        enabled = await self._is_enabled(ctx.guild.id)
        status = "🟢 Enabled" if enabled else "⚫ Disabled"
        description = (
            f"**Filter:** {status}\n**Terms:** {len(terms)}\n\n"
            "Use `,banword add <word or phrase>`, `remove <word or phrase>`, `list`, "
            "`enable`, or `disable`."
        )
        await ctx.send(
            embed=discord.Embed(
                title="🛡️ NexterMC · Word Filter",
                description=description,
                color=discord.Color.green() if enabled else discord.Color.dark_grey(),
            ),
            ephemeral=ctx.interaction is not None,
        )

    @banword.command(name="add", description="Add a word, phrase, user ID, or mention to the filter.")
    @has_permissions_or_owner(manage_messages=True)
    async def add_term(self, ctx: commands.Context, *, term: str):
        if ctx.guild is None:
            await ctx.send("Use this command in a server.", ephemeral=ctx.interaction is not None)
            return
        term = _clean_term(term)
        if not term or len(term) > _MAX_TERM_LENGTH:
            await ctx.send(f"Enter a word or phrase from 1 to {_MAX_TERM_LENGTH} characters.", ephemeral=ctx.interaction is not None)
            return
        added = await storage.add_banned_word(ctx.guild.id, term, ctx.author.id)
        self._terms.setdefault(ctx.guild.id, await storage.list_banned_words(ctx.guild.id))
        if added and term not in self._terms[ctx.guild.id]:
            self._terms[ctx.guild.id].append(term)
        if added:
            embed = discord.Embed(
                title="✅ Filter term added",
                description=f"**Term:** `{discord.utils.escape_markdown(term)}`\nNew messages containing this whole word or phrase will be removed.",
                color=discord.Color.green(),
            )
        else:
            embed = discord.Embed(
                title="ℹ️ Already in the filter",
                description=f"`{discord.utils.escape_markdown(term)}` is already blocked in this server.",
                color=discord.Color.blurple(),
            )
        embed.set_footer(text="Only new messages are checked")
        await ctx.send(embed=embed)

    @banword.command(name="remove", description="Remove a word or phrase from the filter.")
    @has_permissions_or_owner(manage_messages=True)
    async def remove_term(self, ctx: commands.Context, *, term: str):
        if ctx.guild is None:
            await ctx.send("Use this command in a server.", ephemeral=ctx.interaction is not None)
            return
        term = _clean_term(term)
        removed = await storage.remove_banned_word(ctx.guild.id, term)
        if ctx.guild.id in self._terms:
            self._terms[ctx.guild.id] = [item for item in self._terms[ctx.guild.id] if item != term]
        await ctx.send(
            embed=discord.Embed(
                title="✅ Filter term removed" if removed else "❓ Term not found",
                description=(
                    f"`{discord.utils.escape_markdown(term)}` is no longer filtered."
                    if removed else f"`{discord.utils.escape_markdown(term)}` was not in this server’s filter."
                ),
                color=discord.Color.green() if removed else discord.Color.orange(),
            )
        )

    @banword.command(name="list", description="Show this server's filtered words and phrases.")
    @has_permissions_or_owner(manage_messages=True)
    async def list_terms(self, ctx: commands.Context):
        if ctx.guild is None:
            await ctx.send("Use this command in a server.", ephemeral=ctx.interaction is not None)
            return
        terms = await storage.list_banned_words(ctx.guild.id)
        self._terms[ctx.guild.id] = terms
        if not terms:
            description = "No words or phrases are configured yet."
        else:
            description = "\n".join(f"• `{discord.utils.escape_markdown(term)}`" for term in terms[:40])
            if len(terms) > 40:
                description += f"\n…and {len(terms) - 40} more."
        enabled = await self._is_enabled(ctx.guild.id)
        embed = discord.Embed(
            title="📋 NexterMC · Filter Terms",
            description=description,
            color=discord.Color.green() if enabled else discord.Color.dark_grey(),
        )
        embed.set_footer(text=f"Filter {'enabled' if enabled else 'disabled'} · {len(terms)} term(s)")
        await ctx.send(embed=embed, ephemeral=ctx.interaction is not None)

    async def _set_enabled(self, ctx: commands.Context, enabled: bool):
        if ctx.guild is None:
            await ctx.send("Use this command in a server.", ephemeral=ctx.interaction is not None)
            return
        await storage.set_feature_flag(f"{_FLAG_PREFIX}{ctx.guild.id}", enabled)
        self._enabled[ctx.guild.id] = enabled
        if enabled:
            await ctx.send(embed=discord.Embed(
                title="🟢 Word filter enabled",
                description="New messages will be checked against this server’s filter terms.",
                color=discord.Color.green(),
            ))
        else:
            await ctx.send(embed=discord.Embed(
                title="⚫ Word filter disabled",
                description="Messages will no longer be removed by the word filter. Your saved terms are kept.",
                color=discord.Color.dark_grey(),
            ))

    @banword.command(name="enable", description="Enable this server's word filter.")
    @has_permissions_or_owner(manage_messages=True)
    async def enable_filter(self, ctx: commands.Context):
        await self._set_enabled(ctx, True)

    @banword.command(name="disable", description="Disable this server's word filter.")
    @has_permissions_or_owner(manage_messages=True)
    async def disable_filter(self, ctx: commands.Context):
        await self._set_enabled(ctx, False)


async def setup(bot: commands.Bot):
    await bot.add_cog(BanwordCog(bot))
