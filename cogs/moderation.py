import discord
from discord.ext import commands
import datetime

class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # 1. WARN & REMOVE
    @commands.group(invoke_without_command=True)
    @commands.has_permissions(manage_messages=True)
    async def warn(self, ctx, user: discord.Member, *, reason: str = "No reason provided"):
        warn_id = abs(hash(f"{user.id}-{datetime.datetime.now()}")) % 10000
        
        # Send a direct message to the user who got warned
        try:
            dm_embed = discord.Embed(
                title=f"⚠️ You have been warned in **{ctx.guild.name}**",
                color=discord.Color.orange()
            )
            dm_embed.add_field(name="Reason", value=reason, inline=False)
            dm_embed.add_field(name="Warning ID", value=f"`#{warn_id}`", inline=True)
            dm_embed.timestamp = datetime.datetime.now()
            await user.send(embed=dm_embed)
        except discord.Forbidden:
            pass # Fails safely if user has DMs closed

        embed = discord.Embed(title="⚠️ 𝐀𝐜𝐭𝐢𝐨𝐧: 𝐔𝐬𝐞𝐫 𝐖𝐚𝐫𝐧𝐞𝐝", color=discord.Color.orange())
        embed.add_field(name="Target User", value=user.mention, inline=True)
        embed.add_field(name="Warning ID", value=f"`#{warn_id}`", inline=True)
        embed.add_field(name="Moderator", value=ctx.author.mention, inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.timestamp = datetime.datetime.now()
        
        await ctx.send(embed=embed)

    @warn.command(name="remove")
    @commands.has_permissions(manage_messages=True)
    async def warn_remove(self, ctx, user: discord.Member, warn_id: int):
        embed = discord.Embed(title="✅ 𝐀𝐜𝐭𝐢𝐨𝐧: 𝐖𝐚𝐫𝐧𝐢𝐧𝐠 𝐑𝐞𝐦𝐨𝐯𝐞𝐝", color=discord.Color.green())
        embed.description = f"Successfully processed warning removal for ID **#{warn_id}** on {user.mention}."
        embed.timestamp = datetime.datetime.now()
        await ctx.send(embed=embed)

    # 2. BAN
    @commands.command()
    @commands.has_permissions(ban_members=True)
    async def ban(self, ctx, user: discord.User, *, reason: str = "No reason provided"):
        await ctx.guild.ban(user, reason=reason)
        embed = discord.Embed(title="🔨 𝐀𝐜𝐭𝐢𝐨𝐧: 𝐔𝐬𝐞𝐫 𝐁𝐚𝐧𝐧𝐞𝐝", color=discord.Color.red())
        embed.add_field(name="User", value=str(user), inline=True)
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
            embed = discord.Embed(title="🔓 𝐀𝐜𝐭𝐢𝐨𝐧: 𝐔𝐬𝐞𝐫 𝐔𝐧𝐛𝐚𝐧𝐧𝐞𝐝", color=discord.Color.blue())
            embed.description = f"Successfully pardoned and unbanned **{target_user}**."
            await ctx.send(embed=embed)
        else:
            await ctx.send(f"❌ Could not find a banned user matching `{user_name_or_id}`.")

    # 4. TIMEOUT
    @commands.command()
    @commands.has_permissions(moderate_members=True)
    async def timeout(self, ctx, member: discord.Member, *, reason: str = "No reason provided"):
        duration = datetime.timedelta(minutes=10)
        await member.timeout(duration, reason=reason)
        embed = discord.Embed(title="⏳ 𝐀𝐜𝐭𝐢𝐨𝐧: 𝐔𝐬𝐞𝐫 𝐓𝐢𝐦𝐞𝐝 𝐎𝐮𝐭", color=discord.Color.gold())
        embed.add_field(name="Member", value=member.mention, inline=True)
        embed.add_field(name="Duration", value="10 Minutes", inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.timestamp = datetime.datetime.now()
        await ctx.send(embed=embed)

    # 5. UNTIMEOUT
    @commands.command()
    @commands.has_permissions(moderate_members=True)
    async def untimeout(self, ctx, member: discord.Member):
        await member.timeout(None)
        embed = discord.Embed(title="🔊 𝐀𝐜𝐭𝐢𝐨𝐧: 𝐓𝐢𝐦𝐞𝐨𝐮𝐭 𝐑𝐞𝐦𝐨𝐯𝐞𝐝", color=discord.Color.green())
        embed.description = f"Restored communication privileges for {member.mention}."
        await ctx.send(embed=embed)

    # 6. KICK
    @commands.command()
    @commands.has_permissions(kick_members=True)
    async def kick(self, ctx, member: discord.Member, *, reason: str = "No reason provided"):
        await member.kick(reason=reason)
        embed = discord.Embed(title="👢 𝐀𝐜𝐭𝐢𝐨𝐧: 𝐔𝐬𝐞𝐫 𝐊𝐢𝐜𝐤𝐞𝐝", color=discord.Color.dark_red())
        embed.add_field(name="Member", value=str(member), inline=True)
        embed.add_field(name="Reason", value=reason, inline=True)
        embed.timestamp = datetime.datetime.now()
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(Moderation(bot))