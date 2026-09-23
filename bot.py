import discord
from discord.ext import commands
import datetime

intents = discord.Intents.default()
intents.message_content = True
intents.members = True  # Required for lookups and timeouts

bot = commands.Bot(command_prefix=",", intents=intents)

# Remove default help so our custom embed works
bot.remove_command('help')

@bot.event
async def on_ready():
    print(f"NexterMC is logged in and ready as {bot.user}!")

# ==================== HELP COMMAND ====================
@bot.command()
async def help(ctx):
    embed = discord.Embed(
        title="🛡️ NexterMC Moderation & Utility Help",
        description="Here is a list of all available commands. Use prefix `,`",
        color=discord.Color.blurple()
    )
    
    embed.add_field(
        name="🛠️ Moderation Commands",
        value=(
            "`,warn <user> [reason]` - Warns a user.\n"
            "`,warn remove <user> <warn_id>` - Removes a warning.\n"
            "`,ban <user> [reason]` - Bans a user.\n"
            "`,unban <user_id_or_name> [reason]` - Unbans a user.\n"
            "`,timeout <user> [reason]` - Timeouts a user for 10 minutes.\n"
            "`,untimeout <user>` - Removes timeout.\n"
            "`,kick <user> [reason]` - Kicks a user."
        ),
        inline=False
    )
    
    embed.add_field(
        name="🎮 Utility Commands",
        value=(
            "`,ping` - Checks if bot is online.\n"
            "`,say <message>` - Makes bot say something.\n"
            "`,coinflip` - Flips a coin."
        ),
        inline=False
    )
    
    embed.set_footer(text="NexterMC • Powered by Railway")
    embed.timestamp = datetime.datetime.now()
    await ctx.send(embed=embed)

# ==================== UTILITY ====================
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

# ==================== MODERATION ====================

@bot.group(invoke_without_command=True)
async def warn(ctx, user: discord.User, *, reason: str = "None"):
    warn_id = abs(hash(f"{user.id}-{datetime.datetime.now()}")) % 10000
    embed = discord.Embed(title="⚠️ User Warned", color=discord.Color.orange())
    embed.add_field(name="User", value=user.mention, inline=True)
    embed.add_field(name="Warn ID", value=str(warn_id), inline=True)
    embed.add_field(name="Moderator", value=ctx.author.mention, inline=True)
    embed.add_field(name="Reason", value=reason, inline=False)
    await ctx.send(embed=embed)

@warn.command(name="remove")
async def warn_remove(ctx, user: discord.User, warn_id: int):
    embed = discord.Embed(title="✅ Warning Removed", color=discord.Color.green())
    embed.description = f"Successfully removed warning ID **{warn_id}** from {user.mention}."
    await ctx.send(embed=embed)

@bot.command()
@commands.has_permissions(ban_members=True)
async def ban(ctx, user: discord.User, *, reason: str = "None"):
    await ctx.guild.ban(user, reason=reason)
    embed = discord.Embed(title="🔨 User Banned", color=discord.Color.red())
    embed.add_field(name="User", value=str(user), inline=True)
    embed.add_field(name="Reason", value=reason, inline=True)
    await ctx.send(embed=embed)

@bot.command()
@commands.has_permissions(ban_members=True)
async def unban(ctx, *, user_name_or_id):
    banned_entries = await ctx.guild.bans()
    target_user = None
    for entry in banned_entries:
        user = entry.user
        if str(user.id) == user_name_or_id or str(user).lower() == user_name_or_id.lower():
            target_user = user
            break
            
    if target_user:
        await ctx.guild.unban(target_user)
        await ctx.send(f"Successfully unbanned **{target_user}**.")
    else:
        await ctx.send(f"Could not find a banned user matching `{user_name_or_id}`.")

@bot.command()
@commands.has_permissions(moderate_members=True)
async def timeout(ctx, member: discord.Member, *, reason: str = "None"):
    duration = datetime.timedelta(minutes=10)
    await member.timeout(duration, reason=reason)
    embed = discord.Embed(title="⏳ User Timed Out", color=discord.Color.gold())
    embed.add_field(name="User", value=member.mention, inline=True)
    embed.add_field(name="Duration", value="10 Minutes", inline=True)
    embed.add_field(name="Reason", value=reason, inline=False)
    await ctx.send(embed=embed)

@bot.command()
@commands.has_permissions(moderate_members=True)
async def untimeout(ctx, member: discord.Member):
    await member.timeout(None)
    await ctx.send(f"Successfully removed timeout from {member.mention}.")

@bot.command()
@commands.has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason: str = "None"):
    await member.kick(reason=reason)
    embed = discord.Embed(title="👢 User Kicked", color=discord.Color.dark_red())
    embed.add_field(name="User", value=str(member), inline=True)
    embed.add_field(name="Reason", value=reason, inline=True)
    await ctx.send(embed=embed)

import os
bot.run(os.getenv("DISCORD_TOKEN"))