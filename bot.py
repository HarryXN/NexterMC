import discord
from discord.ext import commands

intents = discord.Intents.default()
intents.message_content = True

# Changed prefix to a comma here:
bot = commands.Bot(command_prefix=",", intents=intents)

@bot.event
async def on_ready():
    print(f"NexterMC is logged in and ready as {bot.user}!")

@bot.command()
async def ping(ctx):
    await ctx.send("Pong! NexterMC is online.")

bot.run("MTUzOTMwMzU1MzM1NTQ4NTI4NQ.GHawOw.eNoW4kzutREINFCGq-w5iRO7M_mrJBHwSBoHng")