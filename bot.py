import discord
from discord.ext import commands
import datetime

intents = discord.Intents.default()
intents.message_content = True
intents.members = True  # Required for lookups, timeouts, and roles

bot = commands.Bot(command_prefix=",", intents=intents)

# Remove default help so our custom aesthetic embed works
bot.remove_command('help')

@bot.event
async def on_ready():
    print(f"✨ NexterMC is logged in and ready as {bot.user}!")

# ==================== CUSTOM HELP COMMAND ====================
@bot.command()
async def help(ctx):
    embed = discord.Embed(
        title="🛡️ 𝐍𝐞𝐱𝐭𝐞𝐫𝐌𝐂 • 𝐂𝐨𝐦𝐦𝐚𝐧𝐝 𝐂𝐞𝐧𝐭𝐞𝐫",
        description="Welcome to your advanced server dashboard. Use prefix `,` for all commands.",
        color=discord.Color.from_rgb(88, 101, 242) # Discord Blurple
    )
    
    embed.add_field(
        name="🛠️ 𝐌𝐨𝐝𝐞𝐫𝐚𝐭𝐢𝐨𝐧 𝐒𝐮𝐢𝐭𝐞",
        value=(
            "▫️ `,warn <user> [reason]` - Warns a user and logs an ID.\n"
            "▫️ `,warn remove <user> <id>` - Clears a specific warning ID.\n"
            "▫️ `,ban <user> [reason]` - Permanently bans a disruptive user.\n"
            "▫️ `,unban <user> [reason]` - Revokes a ban via ID or username.\n"
            "▫️ `,timeout <user> [reason]` - Mutes a user for 10 minutes.\n"
            "▫️ `,untimeout <user>` - Restores user's speaking privileges.\n"
            "▫️ `,kick <user> [reason]` - Kicks a user from the server."
        ),
        inline=False
    )
    
    embed.add_field(
        name="🎮 𝐔𝐭𝐢𝐥𝐢𝐭𝐲 & 𝐅𝐮𝐧",
        value=(
            "▫️ `,ping` - Verifies bot response latency.\n"
            "▫️ `,say <message>` - Broadcasts an announcement.\n"
            "▫️ `,coinflip` - Flips a virtual coin."
        ),
        inline=False
    )
    
    embed.set_thumbnail(url=bot.user.avatar.url if bot.user.avatar else None)
    embed.set_footer(text="NexterMC • Powered by Railway & Protected Securely", icon_url=ctx.guild.icon.url if ctx.guild.icon else None)
    embed.timestamp = datetime.datetime.now()
    
    await ctx.send(embed=embed)

# Error handler for missing permissions across commands
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        embed = discord.Embed(
            title="🚫 Access Denied",
            description="You do not possess the required administrative permissions to execute this command.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed, delete_after=5)
    elif isinstance(error, commands.MissingRequiredArgument):
        embed = discord.Embed(
            title="⚠️ Missing Arguments",
            description="You are missing required parts of this command. Check `,help` for proper syntax.",
            color=discord.Color.orange()
        )
        await ctx.send(embed=embed, delete_after=5)

# ==================== UTILITY COMMANDS ====================
@bot.command()
async def ping(ctx):
    embed = discord.Embed(title="🏓 Pong!", description=f"NexterMC is live and operating smoothly! Latency: `{round(bot.latency * 1000)}ms`", color=discord.Color.green())
    await ctx.send(embed=embed)

@bot.command()
async def say(ctx, *, message: str):
    await ctx.message.delete()
    await ctx.send(message)

@bot.command()
async def coinflip(ctx):
    import random
    result = random.choice(["Heads!", "Tails!"])
    embed = discord.Embed(title="🪙 Coin Flip", description=f"The coin landed on: **{result}**", color=discord.Color.gold())
    await ctx.send(embed=embed)

# ==================== MODERATION COMMANDS ====================

# 1. WARN & REMOVE (Protected with Manage Messages / Staff permission)
@bot.group(invoke_without_command=True)
@commands.has_permissions(manage_messages=True)
async def warn(ctx, user: discord.User, *, reason: str = "None"):
    warn_id = abs(hash(f"{user.id}-{datetime.datetime.now()}")) % 10000
    
    embed = discord.Embed(title="⚠️ 𝐀𝐜𝐭𝐢𝐨𝐧: 𝐔𝐬𝐞𝐫 𝐖𝐚𝐫𝐧𝐞𝐝", color=discord.Color.orange())
    embed.add_field(name="Target User", value=user.mention, inline=True)
    embed.add_field(name="Warning ID", value=f"`#{warn_id}`", inline=True)
    embed.add_field(name="Moderator", value=ctx.author.mention, inline=True)
    embed.add_field(name="Reason", value=reason, inline=False)
    embed.timestamp = datetime.datetime.now()
    
    await ctx.send(embed=embed)

@warn.command(name="remove")
@commands.has_permissions(manage_messages=True)
async def warn_remove(ctx, user: discord.User, warn_id: int):
    embed = discord.Embed(title="✅ 𝐀𝐜𝐭𝐢𝐨𝐧: 𝐖𝐚𝐫𝐧𝐢𝐧𝐠 𝐑𝐞𝐦𝐨𝐯𝐞𝐝", color=discord.Color.green())
    embed.description = f"Successfully purged warning ID **#{warn_id}** from {user.mention}."
    embed.timestamp = datetime.datetime.now()
    await ctx.send(embed=embed)

# 2. BAN
@bot.command()
@commands.has_permissions(ban_members=True)
async def ban(ctx, user: discord.User, *, reason: str = "None"):
    await ctx.guild.ban(user, reason=reason)
    embed = discord.Embed(title="🔨 𝐀𝐜𝐭𝐢𝐨𝐧: 𝐔𝐬𝐞𝐫 𝐁𝐚𝐧𝐧𝐞𝐝", color=discord.Color.red())
    embed.add_field(name="User", value=str(user), inline=True)
    embed.add_field(name="Moderator", value=ctx.author.mention, inline=True)
    embed.add_field(name="Reason", value=reason, inline=False)
    embed.timestamp = datetime.datetime.now()
    await ctx.send(embed=embed)

# 3. UNBAN
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
        embed = discord.Embed(title="🔓 𝐀𝐜𝐭𝐢𝐨𝐧: 𝐔𝐬𝐞𝐫 𝐔𝐧𝐛𝐚𝐧𝐧𝐞𝐝", color=discord.Color.blue())
        embed.description = f"Successfully pardoned and unbanned **{target_user}**."
        await ctx.send(embed=embed)
    else:
        await ctx.send(f"❌ Could not find a banned user matching `{user_name_or_id}`.")

# 4. TIMEOUT
@bot.command()
@commands.has_permissions(moderate_members=True)
async def timeout(ctx, member: discord.Member, *, reason: str = "None"):
    duration = datetime.timedelta(minutes=10)
    await member.timeout(duration, reason=reason)
    embed = discord.Embed(title="⏳ 𝐀𝐜𝐭𝐢𝐨𝐧: 𝐔𝐬𝐞𝐫 𝐓𝐢𝐦𝐞𝐝 𝐎𝐮𝐭", color=discord.Color.gold())
    embed.add_field(name="Member", value=member.mention, inline=True)
    embed.add_field(name="Duration", value="10 Minutes", inline=True)
    embed.add_field(name="Reason", value=reason, inline=False)
    embed.timestamp = datetime.datetime.now()
    await ctx.send(embed=embed)

# 5. UNTIMEOUT
@bot.command()
@commands.has_permissions(moderate_members=True)
async def untimeout(ctx, member: discord.Member):
    await member.timeout(None)
    embed = discord.Embed(title="🔊 𝐀𝐜𝐭𝐢𝐨𝐧: 𝐓𝐢𝐦𝐞𝐨𝐮𝐭 𝐑𝐞𝐦𝐨𝐯𝐞𝐝", color=discord.Color.green())
    embed.description = f"Restored communication privileges for {member.mention}."
    await ctx.send(embed=embed)

# 6. KICK
@bot.command()
@commands.has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason: str = "None"):
    await member.kick(reason=reason)
    embed = discord.Embed(title="👢 𝐀𝐜𝐭𝐢𝐨𝐧: 𝐔𝐬𝐞𝐫 𝐊𝐢𝐜𝐤𝐞𝐝", color=discord.Color.dark_red())
    embed.add_field(name="Member", value=str(member), inline=True)
    embed.add_field(name="Reason", value=reason, inline=True)
    embed.timestamp = datetime.datetime.now()
    await ctx.send(embed=embed)

import os
bot.run(os.getenv("DISCORD_TOKEN"))