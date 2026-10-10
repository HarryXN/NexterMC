# cogs/moderation.py
import datetime

import discord
from discord.ext import commands

from utils import storage
from permissions import has_permissions_or_owner


class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def notify_user(self, member: discord.abc.User, title: str, description: str, color: discord.Color):
        try:
            embed = discord.Embed(title=title, description=description, color=color)
            embed.timestamp = datetime.datetime.now(datetime.timezone.utc)
            await member.send(embed=embed)
        except discord.Forbidden:
            pass  # user has DMs closed — fail quietly, don't block the moderation action

    # ------------------------------------------------------------------
    # WARN (persistent, per-guild sequential IDs)
    # ------------------------------------------------------------------
    @commands.hybrid_group(invoke_without_command=True, fallback="issue")
    @has_permissions_or_owner(manage_messages=True)
    async def warn(self, ctx, member: discord.Member, *, reason: str = "No reason provided"):
        warn_id = await storage.add_warning(ctx.guild.id, member.id, reason, str(ctx.author))

        await self.notify_user(
            member,
            title=f"⚠️ Warning Received in {ctx.guild.name}",
            description=f"**Reason:** {reason}\n**Warning ID:** #{warn_id}\n**Moderator:** {ctx.author}",
            color=discord.Color.orange(),
        )

        embed = discord.Embed(title="Action: User Warned", color=discord.Color.orange())
        embed.add_field(name="User", value=f"{member} (`{member.id}`)", inline=False)
        embed.add_field(name="Warning ID", value=f"#{warn_id}", inline=True)
        embed.add_field(name="Moderator", value=ctx.author.mention, inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.timestamp = datetime.datetime.now(datetime.timezone.utc)
        await ctx.send(embed=embed)

    @warn.command(name="remove")
    @has_permissions_or_owner(manage_messages=True)
    async def warn_remove(self, ctx, warn_id: int):
        removed = await storage.remove_warning(ctx.guild.id, warn_id)

        if removed is None:
            await ctx.send(f"❌ Warning ID `#{warn_id}` does not exist in this server.")
            return

        target_user = ctx.guild.get_member(removed["user_id"])
        user_text = f"{target_user} (`{removed['user_id']}`)" if target_user else f"User ID `{removed['user_id']}`"

        embed = discord.Embed(title="Action: Warning Removed", color=discord.Color.green())
        embed.description = f"Successfully removed warning ID **#{warn_id}** belonging to {user_text}."
        embed.timestamp = datetime.datetime.now(datetime.timezone.utc)
        await ctx.send(embed=embed)

    @warn.command(name="list")
    @has_permissions_or_owner(manage_messages=True)
    async def warn_list(self, ctx, member: discord.Member):
        rows = await storage.list_warnings(ctx.guild.id, member.id)

        embed = discord.Embed(
            title=f"📋 Warnings — {member}",
            color=discord.Color.orange() if rows else discord.Color.green(),
        )
        if not rows:
            embed.description = "No warnings on file for this member."
        else:
            for row in rows[:20]:
                embed.add_field(
                    name=f"#{row['warn_id']} • {row['moderator']}",
                    value=f"{row['reason']}\n*{row['created_at']}*",
                    inline=False,
                )
            if len(rows) > 20:
                embed.set_footer(text=f"Showing 20 of {len(rows)} total warnings.")
        await ctx.send(embed=embed)

    # ------------------------------------------------------------------
    # BAN
    # ------------------------------------------------------------------
    @commands.hybrid_command()
    @has_permissions_or_owner(ban_members=True)
    async def ban(self, ctx, member: discord.Member, *, reason: str = "No reason provided"):
        if member == ctx.guild.owner or member == ctx.author:
            await ctx.send("❌ You cannot ban this user.")
            return
        if ctx.guild.me.top_role <= member.top_role and member != ctx.guild.owner:
            await ctx.send("❌ I can't ban this user — their top role is at or above mine.")
            return

        await self.notify_user(
            member,
            title=f"🔨 Banned from {ctx.guild.name}",
            description=f"**Reason:** {reason}\n**Moderator:** {ctx.author}",
            color=discord.Color.red(),
        )

        await ctx.guild.ban(member, reason=reason)
        embed = discord.Embed(title="Action: User Banned", color=discord.Color.red())
        embed.add_field(name="User", value=f"{member} (`{member.id}`)", inline=False)
        embed.add_field(name="Moderator", value=ctx.author.mention, inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.timestamp = datetime.datetime.now(datetime.timezone.utc)
        await ctx.send(embed=embed)

    # ------------------------------------------------------------------
    # UNBAN
    # ------------------------------------------------------------------
    @commands.hybrid_command()
    @has_permissions_or_owner(ban_members=True)
    async def unban(self, ctx, *, user_name_or_id):
        target_user = None
        async for entry in ctx.guild.bans():
            user = entry.user
            if str(user.id) == user_name_or_id or str(user).lower() == user_name_or_id.lower():
                target_user = user
                break

        if target_user:
            await ctx.guild.unban(target_user)
            embed = discord.Embed(title="Action: User Unbanned", color=discord.Color.blue())
            embed.description = f"Successfully unbanned **{target_user}** (`{target_user.id}`)."
            embed.timestamp = datetime.datetime.now(datetime.timezone.utc)
            await ctx.send(embed=embed)
        else:
            await ctx.send(f"❌ Could not find a banned user matching `{user_name_or_id}`.")

    # ------------------------------------------------------------------
    # TIMEOUT / UNTIMEOUT
    # ------------------------------------------------------------------
    @commands.hybrid_command()
    @has_permissions_or_owner(moderate_members=True)
    async def timeout(self, ctx, member: discord.Member, minutes: int = 10, *, reason: str = "No reason provided"):
        if member == ctx.guild.owner or member == ctx.author:
            await ctx.send("❌ You cannot timeout this user.")
            return
        if minutes <= 0 or minutes > 40320:  # Discord's own cap is 28 days
            await ctx.send("❌ Duration must be between 1 minute and 28 days.")
            return

        duration = datetime.timedelta(minutes=minutes)

        await self.notify_user(
            member,
            title=f"⏳ Timed Out in {ctx.guild.name}",
            description=f"**Duration:** {minutes} Minutes\n**Reason:** {reason}\n**Moderator:** {ctx.author}",
            color=discord.Color.gold(),
        )

        try:
            await member.timeout(duration, reason=reason)
        except discord.Forbidden:
            await ctx.send("❌ Failed to timeout user. Make sure my role is higher than theirs!")
            return

        embed = discord.Embed(title="Action: User Timed Out", color=discord.Color.gold())
        embed.add_field(name="Member", value=f"{member} (`{member.id}`)", inline=False)
        embed.add_field(name="Duration", value=f"{minutes} Minutes", inline=True)
        embed.add_field(name="Moderator", value=ctx.author.mention, inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.timestamp = datetime.datetime.now(datetime.timezone.utc)
        await ctx.send(embed=embed)

    @commands.hybrid_command()
    @has_permissions_or_owner(moderate_members=True)
    async def untimeout(self, ctx, member: discord.Member):
        await member.timeout(None)
        embed = discord.Embed(title="Action: Timeout Removed", color=discord.Color.green())
        embed.description = f"Restored communication privileges for {member} (`{member.id}`)."
        embed.timestamp = datetime.datetime.now(datetime.timezone.utc)
        await ctx.send(embed=embed)

    # ------------------------------------------------------------------
    # KICK
    # ------------------------------------------------------------------
    @commands.hybrid_command()
    @has_permissions_or_owner(kick_members=True)
    async def kick(self, ctx, member: discord.Member, *, reason: str = "No reason provided"):
        if member == ctx.guild.owner or member == ctx.author:
            await ctx.send("❌ You cannot kick this user.")
            return

        await self.notify_user(
            member,
            title=f"👢 Kicked from {ctx.guild.name}",
            description=f"**Reason:** {reason}\n**Moderator:** {ctx.author}",
            color=discord.Color.dark_red(),
        )

        await member.kick(reason=reason)
        embed = discord.Embed(title="Action: User Kicked", color=discord.Color.dark_red())
        embed.add_field(name="Member", value=f"{member} (`{member.id}`)", inline=False)
        embed.add_field(name="Moderator", value=ctx.author.mention, inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.timestamp = datetime.datetime.now(datetime.timezone.utc)
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Moderation(bot))
