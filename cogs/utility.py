# cogs/utility.py
import discord
from discord.ext import commands

from config import BRAND_NAME


class Utility(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name="ping")
    async def ping(self, ctx):
        latency_ms = round(self.bot.latency * 1000)
        embed = discord.Embed(
            title="🏓 Pong!",
            description=f"Websocket latency: `{latency_ms}ms`",
            color=discord.Color.green() if latency_ms < 200 else discord.Color.orange(),
        )
        embed.set_footer(text=BRAND_NAME)
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Utility(bot))
