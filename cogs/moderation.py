import discord
from discord.ext import commands
import datetime

class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Global server-wide counters and storage:
        self.warning_counters = {}
        self.warnings = {}

    # Helper function to send DMs safely
    async def notify_user(self, member: discord.abc.User, title: str, description: str, color: discord.Color):
        try:
            embed = discord.Embed(title=title, description=description, color=color)
            embed.timestamp = datetime.datetime.now()
            await member.send(embed=embed)
        except discord.Forbidden:
            pass # Fails safely if user has DMs closed

    # 1. WARN SYSTEM (Global Sequential IDs)
    @commands.group(invoke_without_command=True)
    @commands.has_permissions(manage_messages=True)
    async def warn(self, ctx, member: discord.Member, *, reason: str = "No reason provided"):
        guild_id = ctx.guild.id

        if guild_id not in self.warning_counters:
            self.warning_counters[guild_id] = 0
        if guild_id not in self.warnings:
            self.warnings[guild_id] = {}

        # Increment global counter
        self.warning_counters[guild_id] += 1
        warn_id = self.warning_counters[guild_id]

        # Store warning data globally for the guild
        self.warnings[guild_id][warn_id] = {
            "user_id": member.id,
            "reason": reason,
            "moderator": str(ctx.author)
        }

        # Notify User in DMs
        await self.notify_user(
            member,
            title=f"⚠️ Warning Received in {ctx.guild.name}",
            description=f"**Reason:** {reason}\n**Warning ID:** #{warn_id}\n**Moderator:** {ctx.author}",
            color=discord.Color.orange()
        )

        embed = discord.Embed(title="Action: User Warned", color=discord.Color.orange())
        embed.add_field(name="User", value=f"{member} (`{member.id}`)", inline=False)
        embed.add_field(name="Warning ID", value=f"#{warn_id}", inline=True)
        embed.add_field(name="Moderator", value=ctx.author.mention, inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.timestamp = datetime.datetime.now()
        
        await ctx.send(embed=embed)

    @warn.command(name="remove")
    @commands.has_permissions(manage_messages=True)
    async def warn_remove(self, ctx, warn_id: int):
        guild_id = ctx.guild.id

        if guild_id in self.warnings and warn_id in self.warnings[guild_id]:
            removed_warn = self.warnings[guild_id].pop(warn_id)
            target_user_id = removed_warn["user_id"]
            target_user = ctx.guild.get_member(target_user_id)
            user_text = f"{target_user} (`{target_user_id}`)" if target_user else f"User ID `{target_user_id}`"

            embed = discord.Embed(title="Action: Warning Removed", color=discord.Color.green())
            embed.description = f"Successfully removed warning ID **#{warn_id}** belonging to {user_text}."
            embed.timestamp = datetime.datetime.now()
            await ctx.send(embed=embed)
        else:
            await ctx.send(f"❌ Warning ID `#{warn_id}` does not exist in this server.")

    # 2. BAN
    @commands.command()
    @commands.has_permissions(ban_members=True)
    async def ban(self, ctx, member: discord.Member, *, reason: str = "No reason provided"):
        if member == ctx.guild.owner or member == ctx.author:
            await ctx.send("❌ You cannot ban this user.")
            return

        await self.notify_user(
            member,
            title=f"🔨 Banned from {ctx.guild.name}",
            description=f"**Reason:** {reason}\n**Moderator:** {ctx.author}",
            color=discord.Color.red()
        )
        
        await ctx.guild.ban(member, reason=reason)
        embed = discord.Embed(title="Action: User Banned", color=discord.Color.red())
        embed.add_field(name="User", value=f"{member} (`{member.id}`)", inline=False)
        embed.add_field(name="Moderator", value=ctx.author.mention, inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.timestamp = datetime.datetime.now()
        await ctx.send(embed=embed)

    # 3. UNBAN
    @commands.command()
    @commands.has_permissions(ban_members=True)
    async def unban(self, ctx, *, user_name_or_id):
        banned_entries = await ctx.guild.bans()
        target_user = None
        for entry in banned_entries:
            user = entry.user
            if str(user.id) == user_name_or_id or str(user).lower() == user_name_or_id.lower():
                target_user = user
                break
                
        if target_user:
            await ctx.guild.unban(target_user)
            embed = discord.Embed(title="Action: User Unbanned", color=discord.Color.blue())
            embed.description = f"Successfully unbanned **{target_user}** (`{target_user.id}`)."
            await ctx.send(embed=embed)
        else:
            await ctx.send(f"❌ Could not find a banned user matching `{user_name_or_id}`.")

    # 4. TIMEOUT
    @commands.command()
    @commands.has_permissions(moderate_members=True)
    async def timeout(self, ctx, member: discord.Member, minutes: int = 10, *, reason: str = "No reason provided"):
        if member == ctx.guild.owner or member == ctx.author:
            await ctx.send("❌ You cannot timeout this user.")
            return

        duration = datetime.timedelta(minutes=minutes)
        
        await self.notify_user(
            member,
            title=f"⏳ Timed Out in {ctx.guild.name}",
            description=f"**Duration:** {minutes} Minutes\n**Reason:** {reason}\n**Moderator:** {ctx.author}",
            color=discord.Color.gold()
        )

        try:
            await member.timeout(duration, reason=reason)
            embed = discord.Embed(title="Action: User Timed Out", color=discord.Color.gold())
            embed.add_field(name="Member", value=f"{member} (`{member.id}`)", inline=False)
            embed.add_field(name="Duration", value=f"{minutes} Minutes", inline=True)
            embed.add_field(name="Moderator", value=ctx.author.mention, inline=True)
            embed.add_field(name="Reason", value=reason, inline=False)
            embed.timestamp = datetime.datetime.now()
            await ctx.send(embed=embed)
        except Exception:
            await ctx.send(f"❌ Failed to timeout user. Make sure my role is higher than theirs!")

    # 5. UNTIMEOUT
    @commands.command()
    @commands.has_permissions(moderate_members=True)
    async def untimeout(self, ctx, member: discord.Member):
        await member.timeout(None)
        embed = discord.Embed(title="Action: Timeout Removed", color=discord.Color.green())
        embed.description = f"Restored communication privileges for {member} (`{member.id}`)."
        await ctx.send(embed=embed)

    # 6. KICK
    @commands.command()
    @commands.has_permissions(kick_members=True)
    async def kick(self, ctx, member: discord.Member, *, reason: str = "No reason provided"):
        if member == ctx.guild.owner or member == ctx.author:
            await ctx.send("❌ You cannot kick this user.")
            return

        await self.notify_user(
            member,
            title=f"👢 Kicked from {ctx.guild.name}",
            description=f"**Reason:** {reason}\n**Moderator:** {ctx.author}",
            color=discord.Color.dark_red()
        )

        await member.kick(reason=reason)
        embed = discord.Embed(title="Action: User Kicked", color=discord.Color.dark_red())
        embed.add_field(name="Member", value=f"{member} (`{member.id}`)", inline=False)
        embed.add_field(name="Moderator", value=ctx.author.mention, inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.timestamp = datetime.datetime.now()
        await ctx.send(embed=embed)

    # 7. ENHANCED HELP COMMAND
    @commands.command(name="help")
    async def help_command(self, ctx):
        embed = discord.Embed(
            title="🌟 NexterMC Control Panel & Command Center",
            description="Welcome to the administrative dashboard. Use prefix `,` for all commands.",
            color=discord.Color.blurple()
        )
        
        embed.add_field(
            name="🛡️ Moderation Suite",
            value=(
                "`warn <user> [reason]` - Issues a tracked warning with a global ID.\n"
                "`warn remove <id>` - Clears an active warning ID.\n"
                "`ban <user> [reason]` - Permanently bans a disruptive user.\n"
                "`unban <user_id>` - Pardons a banned user ID/name.\n"
                "`timeout <user> [mins] [reason]` - Mutes a user temporarily.\n"
                "`untimeout <user>` - Restores user speaking privileges.\n"
                "`kick <user> [reason]` - Kicks a user from the server."
            ),
            inline=False
        )

        embed.add_field(
            name="🔍 System Diagnostics & Administration",
            value=(
                "`check` - Runs a deep system scan for syntax errors, RAM/CPU load, and Minecraft node health.\n"
                "`pyfiles` - Displays active repository directory structure."
            ),
            inline=False
        )

        embed.add_field(
            name="✨ Utility & Tools",
            value=(
                "`ping` - Checks bot websocket response latency.\n"
                "`say <message>` - Broadcasts an administrative announcement."
            ),
            inline=False
        )

        embed.set_footer(text="NexterMC • Protected Securely", icon_url=ctx.bot.user.avatar.url if ctx.bot.user.avatar else None)
        embed.timestamp = datetime.datetime.now()
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(Moderation(bot))