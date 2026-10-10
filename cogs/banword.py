"""Persistent per-server word and phrase filter."""
from __future__ import annotations

import logging
import re
from datetime import timedelta

import discord
from discord.ext import commands

from config import CRASH_LOG_CHANNEL_ID
from permissions import has_permissions_or_owner
from utils import storage

log = logging.getLogger("nextermc.banword")
_FLAG_PREFIX = "banword_filter:"
_MAX_TERM_LENGTH = 100
_BANWORD_LOG_CHANNEL_ID = CRASH_LOG_CHANNEL_ID
_RESTRICTED_PING_EXEMPT_ROLE_IDS = {
    1525152379710734389,
    1499066080390283384,
}
_RESTRICTED_PING_EXEMPT_USER_IDS = {
    1006250810142883851,
    1307545812124827698,
    1514798035379556501,
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
        self._whitelist: dict[int, set[int]] = {}

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

    async def _get_whitelist(self, guild_id: int) -> set[int]:
        if guild_id not in self._whitelist:
            self._whitelist[guild_id] = set(await storage.list_banword_whitelist(guild_id))
        return self._whitelist[guild_id]

    @staticmethod
    def _member_is_filtered(member: discord.abc.User, terms: list[str]) -> bool:
        candidates = {
            str(member.id),
            f"<@{member.id}>",
            f"<@!{member.id}>",
            _clean_term(member.name or ""),
            _clean_term(getattr(member, "display_name", None) or ""),
            _clean_term(getattr(member, "global_name", None) or ""),
            _clean_term("@" + (member.name or "")),
            _clean_term("@" + (getattr(member, "display_name", None) or "")),
        }
        return bool(set(terms).intersection(candidates))

    async def _reply_target_id(self, message: discord.Message) -> int | None:
        reference = message.reference
        if reference is None or reference.message_id is None:
            return None
        # discord.py exposes the resolved reply through MessageReference.resolved;
        # Message.referenced_message is not available in every supported version.
        replied = getattr(reference, "resolved", None)
        if not isinstance(replied, discord.Message):
            replied = None
        if replied is None and reference.channel_id == message.channel.id:
            try:
                replied = await message.channel.fetch_message(reference.message_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                return None
        if replied is None or replied.guild is None or replied.guild.id != message.guild.id:
            return None
        return replied.author.id

    @staticmethod
    def _mentions_filtered_target(
        message: discord.Message,
        terms: list[str],
        ignored_user_id: int | None = None,
    ) -> bool:
        filtered = set(terms)
        # Raw mention markup still contains the user ID even if discord.py
        # could not resolve the mentioned member into Message.mentions.
        for mentioned_id in re.findall(r"<@!?(\d+)>", message.content):
            if mentioned_id in filtered and mentioned_id != str(ignored_user_id):
                return True
            if message.guild is not None:
                mentioned_member = message.guild.get_member(int(mentioned_id))
                if (
                    mentioned_member is not None
                    and mentioned_member.id != ignored_user_id
                    and BanwordCog._member_is_filtered(mentioned_member, terms)
                ):
                    return True
        for member in message.mentions:
            # Discord may include the replied-to author as an implicit mention.
            # Do not treat that reply context alone as a restricted ping.
            if ignored_user_id is not None and member.id == ignored_user_id:
                continue
            if BanwordCog._member_is_filtered(member, terms):
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

    async def _log_action(
        self,
        message: discord.Message,
        strikes: int,
        action: str,
        reason: str,
        dm_delivered: bool,
        timeout_failure: str | None = None,
    ) -> None:
        channel = self.bot.get_channel(_BANWORD_LOG_CHANNEL_ID)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(_BANWORD_LOG_CHANNEL_ID)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                log.exception("Cannot access banword audit/crash channel %s", _BANWORD_LOG_CHANNEL_ID)
                return

        member = message.author
        embed = discord.Embed(
            title="🛡️ Banword moderation action",
            description=f"**Action:** {action}",
            color=discord.Color.red() if "timeout" in action.casefold() else discord.Color.orange(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="Member", value=f"{discord.utils.escape_markdown(member.display_name)} (`{member.id}`)", inline=False)
        embed.add_field(name="Infractions in 24h", value=str(strikes), inline=True)
        embed.add_field(name="DM delivered", value="Yes" if dm_delivered else "No (privacy settings or unavailable)", inline=True)
        embed.add_field(name="Rule", value=reason, inline=True)
        embed.add_field(name="Source", value=f"{message.channel.mention} (`{message.channel.id}`)", inline=False)
        if timeout_failure:
            embed.add_field(name="Timeout note", value=timeout_failure[:1024], inline=False)
        embed.set_footer(text=f"Guild: {message.guild.name} · NexterMC moderation audit")
        try:
            await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            log.exception("Failed to send banword audit action to channel %s", _BANWORD_LOG_CHANNEL_ID)

    async def _dm_member(self, member: discord.abc.User, embed: discord.Embed) -> bool:
        try:
            await member.send(embed=embed)
            return True
        except discord.HTTPException:
            # DMs commonly fail because users disable server DMs. Record the
            # delivery state in the moderation audit; the channel notice stays.
            log.info("Banword DM could not be delivered (user_id=%s)", member.id)
            return False

    async def _handle_violation(self, message: discord.Message, reason: str) -> None:
        message_deleted = True
        try:
            await message.delete()
        except discord.NotFound:
            pass
        except discord.Forbidden:
            message_deleted = False
            log.error(
                "Banword action could not delete message (guild_id=%s channel_id=%s message_id=%s user_id=%s); missing Manage Messages",
                message.guild.id, message.channel.id, message.id, message.author.id,
            )
        except discord.HTTPException:
            message_deleted = False
            log.exception(
                "Banword message deletion failed (guild_id=%s channel_id=%s message_id=%s user_id=%s)",
                message.guild.id, message.channel.id, message.id, message.author.id,
            )

        strikes = await storage.record_banword_strike(message.guild.id, message.author.id)
        member = message.author
        timed_out = False
        timeout_failure = None
        # Strike 1 is a warning. A second violation within 24 hours triggers
        # the timeout. Subsequent violations in that window also trigger it.
        if strikes >= 2 and isinstance(member, discord.Member):
            bot_member = message.guild.me
            if member == message.guild.owner:
                timeout_failure = "Discord does not allow timing out the server owner."
            elif member.guild_permissions.administrator:
                timeout_failure = "Discord does not allow timing out an administrator."
            elif bot_member is None or not bot_member.guild_permissions.moderate_members:
                timeout_failure = "The bot is missing Moderate Members permission."
            elif bot_member.top_role <= member.top_role:
                timeout_failure = "The bot's highest role must be above the member's highest role."
            else:
                try:
                    await member.timeout(
                        timedelta(hours=1),
                        reason="Repeated violation of the server's banword filter within 24 hours",
                    )
                    timed_out = True
                except discord.HTTPException:
                    timeout_failure = "Discord rejected the timeout; check Moderate Members permission and role hierarchy."
                    log.exception("Banword timeout failed (guild_id=%s user_id=%s)", message.guild.id, member.id)
            if timeout_failure:
                log.error(
                    "Banword timeout not applied (guild_id=%s channel_id=%s user_id=%s): %s",
                    message.guild.id, message.channel.id, member.id, timeout_failure,
                )

        action = "One-hour timeout applied" if timed_out else "Warning issued" if strikes == 1 else "Repeated violation; timeout failed"
        dm_title = "⏱️ NexterMC · 1-hour timeout" if timed_out else "⚠️ NexterMC · Formal filter warning" if strikes == 1 else "⚠️ NexterMC · Filter violation"
        deletion_text = "Your message was removed." if message_deleted else "I could not remove your message because the bot needs Manage Messages in that channel."
        if timed_out:
            dm_description = (
                f"A message in **{message.guild.name}** matched the server's chat filter ({reason}). "
                f"{deletion_text} A **1-hour timeout** has been applied. If you believe this was a mistake, contact the moderation team."
            )
        elif strikes == 1:
            dm_description = (
                f"A message in **{message.guild.name}** matched the server's chat filter ({reason}). "
                f"{deletion_text} This is your warning; another filter violation within 24 hours may result in a **1-hour timeout**. "
                "If you think this was a mistake, contact the moderation team."
            )
        else:
            dm_description = (
                f"A message in **{message.guild.name}** matched the server's chat filter ({reason}), but the timeout could not be applied. "
                f"{timeout_failure or 'Please contact a moderator.'}"
            )
        dm_embed = discord.Embed(
            title=dm_title,
            description=dm_description,
            color=discord.Color.red() if timed_out else discord.Color.orange(),
            timestamp=discord.utils.utcnow(),
        )
        dm_embed.set_footer(text="NexterMC moderation · Contact staff if you need clarification")
        dm_delivered = await self._dm_member(member, dm_embed)

        deletion_text = "The offending message was removed." if message_deleted else "I could not remove the message; the bot needs Manage Messages in this channel."
        if timed_out:
            title = "⏱️ 1-hour timeout applied"
            description = f"{message.author.mention}, {deletion_text} A repeat filter violation within 24 hours triggered a one-hour timeout. Details were sent by DM."
            color = discord.Color.red()
        elif strikes == 1:
            title = "⚠️ Official warning · 1 of 2"
            description = f"{message.author.mention}, {deletion_text} This is your first warning. Another violation within 24 hours may result in a one-hour timeout."
            color = discord.Color.orange()
        else:
            title = "⚠️ Filter violation · timeout not applied"
            description = f"{message.author.mention}, {deletion_text} I couldn’t apply the timeout: {timeout_failure or 'please contact a moderator.'}"
            color = discord.Color.orange()
        if not dm_delivered:
            description += " I couldn’t deliver the DM; please check your server privacy settings."
        warning = discord.Embed(title=title, description=description, color=color, timestamp=discord.utils.utcnow())
        warning.set_footer(text="NexterMC · Automated moderation · Contact staff to appeal")

        await self._log_action(message, strikes, action, reason, dm_delivered, timeout_failure)
        fallback = f"⚠️ {message.author.mention}: {description}"
        await self._send_warning(message, warning, fallback, "banword moderation")

    async def _send_warning(
        self,
        message: discord.Message,
        embed: discord.Embed,
        fallback_text: str,
        action_label: str,
    ) -> None:
        try:
            await message.channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
            return
        except discord.HTTPException:
            log.exception(
                "Could not send %s warning embed (guild_id=%s channel_id=%s message_id=%s)",
                action_label, message.guild.id, message.channel.id, message.id,
            )
        try:
            await message.channel.send(fallback_text, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            log.exception(
                "Could not send %s warning fallback; check Send Messages permission (guild_id=%s channel_id=%s message_id=%s)",
                action_label, message.guild.id, message.channel.id, message.id,
            )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        try:
            await self._process_message(message)
        except Exception:
            log.exception(
                "Banword listener failed (guild_id=%s channel_id=%s message_id=%s author_id=%s); review this error in the crash channel",
                getattr(message.guild, "id", None),
                getattr(message.channel, "id", None),
                getattr(message, "id", None),
                getattr(message.author, "id", None),
            )

    async def _process_message(self, message: discord.Message):
        if message.guild is None or message.author.bot or message.webhook_id:
            return
        # Keep the moderation controls usable even if an administrator's input
        # contains the term they are trying to add or remove.
        if message.content.casefold().lstrip().startswith(",banword "):
            return
        if not await self._is_enabled(message.guild.id):
            return
        if message.author.id in await self._get_whitelist(message.guild.id):
            return

        terms = await self._get_terms(message.guild.id)
        try:
            reply_target_id = await self._reply_target_id(message)
        except Exception:
            # A failure to resolve reply metadata must never prevent normal
            # word/mention moderation from processing the message.
            log.exception("Could not resolve reply metadata in channel %s", message.channel.id)
            reply_target_id = None
        ignored_reply_target_id = None
        if reply_target_id is not None:
            reply_target = message.guild.get_member(reply_target_id)
            if reply_target is None:
                try:
                    reply_target = await message.guild.fetch_member(reply_target_id)
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    reply_target = None
            if reply_target is not None and self._member_is_filtered(reply_target, terms):
                ignored_reply_target_id = reply_target_id

        if self._mentions_filtered_target(message, terms, ignored_reply_target_id):
            author = message.author
            if author.id in _RESTRICTED_PING_EXEMPT_USER_IDS or (
                isinstance(author, discord.Member)
                and any(role.id in _RESTRICTED_PING_EXEMPT_ROLE_IDS for role in author.roles)
            ):
                # These legacy exemptions intentionally make the restricted
                # ping itself a no-op.
                return
            await self._handle_violation(message, "restricted member or role mention")
            return
        filter_content = message.content
        if ignored_reply_target_id is not None:
            # Discord may include the replied-to author's implicit mention in
            # content. Strip just that reference token so a stored user ID or
            # mention token does not trip the ordinary word matcher either.
            reply_mention = re.compile(rf"<@!?{ignored_reply_target_id}>")
            filter_content = reply_mention.sub(" ", filter_content)
        match = next((term for term in terms if _matches(filter_content, term)), None)
        if match is not None:
            await self._handle_violation(message, "filtered word or phrase")

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
            "`enable`, or `disable`. Manage member exemptions with `,banword whitelist <member>` and `,banword whitelist remove <member>`."
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

    @banword.group(name="whitelist", invoke_without_command=True, description="Manage members exempt from the banword filter.")
    @has_permissions_or_owner(manage_messages=True)
    async def whitelist_group(self, ctx: commands.Context, user: discord.User | None = None):
        """Add a member when supplied; otherwise show the whitelist."""
        if ctx.guild is None:
            await ctx.send("Use this command in a server.", ephemeral=ctx.interaction is not None)
            return
        if user is not None:
            await self._add_whitelist_member(ctx, user)
            return
        await self._show_whitelist(ctx)

    async def _add_whitelist_member(self, ctx: commands.Context, user: discord.User):
        whitelist = await self._get_whitelist(ctx.guild.id)
        added = await storage.add_banword_whitelist(ctx.guild.id, user.id, ctx.author.id)
        whitelist.add(user.id)
        embed = discord.Embed(
            title="✅ Member whitelisted" if added else "ℹ️ Already whitelisted",
            description=f"{user.mention} (`{user.id}`) is {'now exempt from' if added else 'already exempt from'} all banword checks in this server.",
            color=discord.Color.green() if added else discord.Color.blurple(),
        )
        await ctx.send(embed=embed, ephemeral=ctx.interaction is not None)

    @whitelist_group.command(name="add", description="Exempt a member from this server's banword filter.")
    @has_permissions_or_owner(manage_messages=True)
    async def whitelist_add(self, ctx: commands.Context, user: discord.User):
        if ctx.guild is None:
            await ctx.send("Use this command in a server.", ephemeral=ctx.interaction is not None)
            return
        await self._add_whitelist_member(ctx, user)

    @whitelist_group.command(name="remove", description="Remove a member from this server's banword whitelist.")
    @has_permissions_or_owner(manage_messages=True)
    async def whitelist_remove(self, ctx: commands.Context, user: discord.User):
        if ctx.guild is None:
            await ctx.send("Use this command in a server.", ephemeral=ctx.interaction is not None)
            return
        whitelist = await self._get_whitelist(ctx.guild.id)
        removed = await storage.remove_banword_whitelist(ctx.guild.id, user.id)
        whitelist.discard(user.id)
        await ctx.send(
            embed=discord.Embed(
                title="✅ Whitelist entry removed" if removed else "ℹ️ Member was not whitelisted",
                description=f"{user.mention} (`{user.id}`) {'will be checked by' if removed else 'is not currently exempt from'} the banword filter.",
                color=discord.Color.green() if removed else discord.Color.blurple(),
            ),
            ephemeral=ctx.interaction is not None,
        )

    @whitelist_group.command(name="list", description="List this server's banword-whitelisted members.")
    @has_permissions_or_owner(manage_messages=True)
    async def whitelist_list(self, ctx: commands.Context):
        await self._show_whitelist(ctx)

    async def _show_whitelist(self, ctx: commands.Context):
        if ctx.guild is None:
            await ctx.send("Use this command in a server.", ephemeral=ctx.interaction is not None)
            return
        user_ids = sorted(await self._get_whitelist(ctx.guild.id))
        if user_ids:
            lines = [f"• <@{user_id}> · `{user_id}`" for user_id in user_ids[:35]]
            if len(user_ids) > 35:
                lines.append(f"…and {len(user_ids) - 35} more")
            description = "\n".join(lines)
        else:
            description = "No members are currently whitelisted."
        embed = discord.Embed(
            title="📋 NexterMC · Banword Whitelist",
            description=description,
            color=discord.Color.blurple(),
        )
        embed.set_footer(text="Whitelisted members bypass all banword checks in this server")
        await ctx.send(embed=embed, ephemeral=ctx.interaction is not None)


async def setup(bot: commands.Bot):
    await bot.add_cog(BanwordCog(bot))
