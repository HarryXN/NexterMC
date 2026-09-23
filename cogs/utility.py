import discord
from discord.ext import commands
import datetime

class Utility(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="ping")
    async def ping(self, ctx):
        embed = discord.Embed(
            title="Pong!",
            description=f"NexterMC latency is `{round(self.bot.latency * 1000)}ms`.",
            color=discord.Color.green()
        )
        embed.timestamp = datetime.datetime.now()
        await ctx.send(embed=embed)

    @commands.command(name="say")
    @commands.has_permissions(manage_messages=True)
    async def say(self, ctx, *, message: str):
        await ctx.message.delete()
        await ctx.send(message)

async def setup(bot):
    await bot.add_cog(Utility(bot))