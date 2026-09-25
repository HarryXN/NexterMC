# main.py
import os
import discord
from discord.ext import commands
from dotenv import load_dotenv
from permissions import OWNER_ID

load_dotenv()

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix=",", intents=intents, help_command=None)
TOKEN = os.getenv("DISCORD_TOKEN")


# ==========================================
# GLOBAL PERMISSION CHECK (APPLIES TO ALL COMMANDS)
# ==========================================
@bot.check
async def globally_enforce_owner_or_staff(ctx):
    # 1. Always allow you (the Owner) across all bot commands
    if ctx.author.id == OWNER_ID:
        return True
    
    # 2. Allow staff members who have manage_channels permission
    if ctx.channel.permissions_for(ctx.author).manage_channels:
        return True
        
    # Block anyone else and notify them cleanly
    raise commands.CheckFailure("❌ You don't have permission to use this command!")


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CheckFailure):
        await ctx.send(str(error), delete_after=5)
    else:
        print(f"Ignored error in command {ctx.command}: {error}")


async def load_cogs():
    cog_folder = "./cogs"
    if not os.path.exists(cog_folder):
        print(f"Directory {cog_folder} not found!")
        return

    for filename in os.listdir(cog_folder):
        if filename.endswith(".py"):
            module_path = f"cogs.{filename[:-3]}"
            try:
                await bot.load_extension(module_path)
                print(f"Loaded extension: {module_path}")
            except Exception as e:
                print(f"Failed to load {module_path}: {e}")


@bot.event
async def on_ready():
    activity = discord.Activity(
        type=discord.ActivityType.playing, name="NexterMC Moderation"
    )
    await bot.change_presence(activity=activity)
    print(f"Logged in as {bot.user} ({bot.user.id})")
    print("Bot is ready and running!")


@bot.event
async def setup_hook():
    await load_cogs()


if __name__ == "__main__":
    if not TOKEN:
        print("ERROR: DISCORD_TOKEN environment variable is missing!")
    else:
        bot.run(TOKEN)