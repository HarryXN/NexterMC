# cogs/invites.py
"""
Real invite tracking, replacing the file that used to be empty (which made
every startup log a "Failed to load cogs.invites" error, since a cog file
with no setup() function can't be loaded as an extension).

Caches each guild's invite codes and their use-counts on ready, then on
every join diffs the cache against the current invite list to work out
which invite was used, records (guild, inviter, joined member) in the
persistent store, and updates the cache. This is the standard approach
since Discord doesn't tell you directly which invite a member used.

`accage` is a lightweight anti-alt tool: flags accounts younger than a
threshold, useful alongside `invsummary`'s invite-fraud auditing.
"""
import datetime

import discord
from discord.ext import commands

from config import BRAND_NAME
from utils import storage

SUSPICIOUS_ACCOUNT_AGE_DAYS = 7


class Invites(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # {guild_id: {invite_code: uses}}
        self._invite_cache: dict[int, dict[str, int]] = {}

    async def _cache_guild_invites(self, guild: discord.Guild):
        try:
            invites = await guild.invites()
        except discord.Forbidden:
            return  # bot lacks Manage Server in this guild — invite tracking unavailable there
        self._invite_cache[guild.id] = {inv.code: inv.uses or 0 for inv in invites}

    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            await self._cache_guild_invites(guild)

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        await self._cache_guild_invites(guild)

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite):
        self._invite_cache.setdefault(invite.guild.id, {})[invite.code] = invite.uses or 0

    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite):
        self._invite_cache.get(invite.guild.id, {}).pop(invite.code, None)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        guild = member.guild
        before = self._invite_cache.get(guild.id, {})

        try:
            after_invites = await guild.invites()
        except discord.Forbidden:
            return

        used_invite = None
        for inv in after_invites:
            if inv.uses and inv.uses > before.get(inv.code, 0):
                used_invite = inv
                break

        # Refresh cache regardless of whether we found a match
        self._invite_cache[guild.id] = {inv.code: inv.uses or 0 for inv in after_invites}

        if used_invite and used_invite.inviter:
            await storage.record_invite_join(guild.id, used_invite.inviter.id, member.id)

    @commands.hybrid_command(name="invites")
    async def invites_cmd(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        count = await storage.count_invites(ctx.guild.id, member.id)
        embed = discord.Embed(
            title=f"🎟️ Invites — {member}",
            description=f"**{count}** tracked member(s) joined via this user's invites.",
            color=discord.Color.blurple(),
        )
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="invited")
    async def invited_cmd(self, ctx, member: discord.Member):
        inviter_id = await storage.get_inviter(ctx.guild.id, member.id)
        if inviter_id is None:
            await ctx.send(f"❌ No recorded inviter for {member.mention} (they may have joined before tracking started).")
            return
        inviter = ctx.guild.get_member(inviter_id)
        inviter_text = inviter.mention if inviter else f"User ID `{inviter_id}` (no longer in server)"
        embed = discord.Embed(
            title=f"🔎 Invite Origin — {member}",
            description=f"Joined using an invite created by {inviter_text}.",
            color=discord.Color.blurple(),
        )
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="accage", aliases=["accountage"])
    async def accage_cmd(self, ctx, member: discord.Member):
        age = datetime.datetime.now(datetime.timezone.utc) - member.created_at
        days = age.days
        suspicious = days < SUSPICIOUS_ACCOUNT_AGE_DAYS

        embed = discord.Embed(
            title=f"🕒 Account Age — {member}",
            color=discord.Color.red() if suspicious else discord.Color.green(),
        )
        embed.add_field(name="Account Created", value=discord.utils.format_dt(member.created_at, style="F"), inline=False)
        embed.add_field(name="Age", value=f"{days} day(s)", inline=True)
        embed.add_field(
            name="Flag",
            value="🚩 Younger than 7 days — review before granting invite rewards." if suspicious else "🟢 Not flagged.",
            inline=True,
        )
        embed.set_footer(text=f"{BRAND_NAME} • Invite Fraud Screening")
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Invites(bot))
