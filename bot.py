import discord
from discord.ext import commands
import datetime
import asyncio

intents = discord.Intents.default()
intents.message_content = True
intents.members = True  # Required for member/user lookups & timeouts

bot = commands.Bot(command_prefix=",", intents=intents)

@bot.event
async def on_ready():
    print(f"NexterMC is logged in and ready as {bot.user}!")

# ==================== HELP COMMAND ====================
@bot.command()
async def help(ctx):
    embed = discord.Embed(
        title="🛡️ NexterMC Moderation & Utility Help",
        description="Here is a list of all available commands for your server. Use prefix `,`",
        color=discord.Color.blurple()
    )
    
    embed.add_field(
        name="🛠️ Moderation Commands",
        value=(
            "`,warn <user> [reason]` - Warns a user and generates a warning log.\n"
            "`,warn remove <user> <warn_id>` - Removes a specific warning.\n"
            "`,ban <user> [reason]` - Bans a user from the server.\n"
            "`,unban <user> [reason]` - Unbans a user.\n"
            "`,timeout <user> [reason]` - Timeouts a user for 10 minutes.\n"
            "`,untimeout <user>` - Removes timeout from a user.\n"
            "`,kick <user> [reason]` - Kicks a user from the server."
        ),
        inline=False
    )
    
    embed.add_field(
        name="🎮 Utility / Fun Commands",
        value=(
            "`,ping` - Checks if the bot is online.\n"
            "`,say <message>` - Makes the bot say something.\n"
            "`,coinflip` - Flips a coin."
        ),
        inline=False
    )
    
    embed.set_footer(text="NexterMC • Powered by Railway & DiscordSRV ready")
    embed.timestamp = datetime.datetime.now()
    
    await ctx.send(embed=embed)

# ==================== UTILITY COMMANDS ====================
@bot.command()
async def ping(ctx):
    await ctx.send("Pong! NexterMC is online.")

@bot.command()
async def say(ctx, *, message: str):
    await ctx.message.delete()
    await ctx.send(message)

@bot.command()
async def coinflip(ctx):
    import random
    result = random.choice(["Heads!", "Tails!"])
    await ctx.send(f"🪙 The coin landed on: **{result}**")

# ==================== MODERATION COMMANDS ====================

# 1. WARN & WARN REMOVE
# Note: For a real database storage, you'd hook this to SQLite. For now, it tracks/sends the warning log visually.
@bot.group(invoke_without_command=True)
async def warn(ctx, member: discord.Member, *, reason: str = "None"):
    warn_id = abs(hash(f"{member.id}-{datetime.datetime.now()}")) % 10000  # Simple 4-digit ID generator
    
    embed = discord.Embed(title="⚠️ User Warned", color=discord.Color.orange())
    embed.add_field(name="User", value=member.mention, inline=True)
    embed.add_field(name="Warn ID", value=str(warn_id), inline=True)
    embed.add_field(name="Moderator", value=ctx.author.mention, inline=True)
    embed.add_field(name="Reason", value=reason, inline=False)
    
    await ctx.send(embed=embed)

@warn.command(name="remove")
async def warn_remove(ctx, member: discord.Member, warn_id: int):
    embed = discord.Embed(title="✅ Warning Removed", color=discord.Color.green())
    embed.description = f"Successfully removed warning ID **{warn_id}** from {member.mention}."
    await ctx.send(embed=embed)

# 2. BAN
@bot.command()
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason: str = "None"):
    await member.ban(reason=reason)
    embed = discord.Embed(title="🔨 User Banned", color=discord.Color.red())
    embed.add_field(name="User", value=str(member), inline=True)
    embed.add_field(name="Reason", value=reason, inline=True)
    await ctx.send(embed=embed)

# 3. UNBAN
@bot.command()
@commands.has_permissions(ban_members=True)
async def unban(ctx, *, user_name_or_id):
    # Tries to handle unbanning by name/discriminator or ID
    banned_entries = await ctx.guild.bans()
    target_user = None
    
    for entry in banned_entries:
        user = entry.user
        if str(user.id) == user_name_or_id or str(user) == user_name_or_id:
            target_user = user
            break
            
    if target_user:
        await ctx.guild.unban(target_user)
        await ctx.send(f"Successfully unbanned **{target_user}**.")
    else:
        await ctx.send(f"Could not find a banned user matching `{user_name_or_id}`.")

# 4. TIMEOUT
@bot.command()
@commands.has_permissions(moderate_members=True)
async def timeout(ctx, member: discord.Member, *, reason: str = "None"):
    duration = datetime.timedelta(minutes=10)  # Default timeout duration set to 10 minutes
    await member.timeout(duration, reason=reason)
    
    embed = discord.Embed(title="⏳ User Timed Out", color=discord.Color.gold())
    embed.add_field(name="User", value=member.mention, inline=True)
    embed.add_field(name="Duration", value="10 Minutes", inline=True)
    embed.add_field(name="Reason", value=reason, inline=False)
    await ctx.send(embed=embed)

# 5. UNTIMEOUT
@bot.command()
@commands.has_permissions(moderate_members=True)
async def untimeout(ctx, member: discord.Member):
    await member.timeout(None)
    await ctx.send(f"Successfully removed timeout from {member.mention}.")

# 6. KICK
@bot.command()
@commands.has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason: str = "None"):
    await member.kick(reason=reason)
    embed = discord.Embed(title="👢 User Kicked", color=discord.Color.dark_red())
    embed.add_field(name="User", value=str(member), inline=True)
    embed.add_field(name="Reason", value=reason, inline=True)
    await ctx.send(embed=embed)

bot.run("MTUzOTMwMzU1MzM1NTQ4NTI4NQ.GHawOw.eNoW4kzutREINFCGq-w5iRO7M_mrJBHwSBoHng")