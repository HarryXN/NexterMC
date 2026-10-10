# cogs/minecraft.py
"""
NexterMC network commands.

,ip      — static connection info (Java + Bedrock).
,status  — actually connects to every configured server node and reports
           real online/offline + player counts, not a guess.

Server list lives in config.py (MINECRAFT_SERVERS) so it's one place to
update if a node's address ever changes.
"""
import asyncio
import datetime

import discord
from discord.ext import commands
from mcstatus import JavaServer

from config import BRAND_NAME, MINECRAFT_SERVERS


async def _check_node(name: str, address: str, timeout: float = 3.0) -> tuple[str, str]:
    """Attempt a real connection to one node. Returns (name, formatted field value)."""
    try:
        server = await asyncio.wait_for(JavaServer.async_lookup(address), timeout=timeout)
        status = await asyncio.wait_for(server.async_status(), timeout=timeout)
        value = (
            f"**Status:** 🟢 Online\n"
            f"**Players:** `{status.players.online}/{status.players.max}`\n"
            f"**Latency:** `{round(status.latency)}ms`\n"
            f"**Address:** `{address}`"
        )
    except asyncio.TimeoutError:
        value = f"**Status:** 🟡 Timeout\n**Address:** `{address}`"
    except Exception:
        value = f"**Status:** 🔴 Offline / Unreachable\n**Address:** `{address}`"
    return name, value


class Minecraft(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.servers = MINECRAFT_SERVERS

    @commands.hybrid_command(name="status", aliases=["mcstatus", "servers"])
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def status(self, ctx):
        embed = discord.Embed(
            title=f"{BRAND_NAME} Network Status",
            description=f"Real-time connection check for every {BRAND_NAME} node.",
            color=discord.Color.blurple(),
        )

        # Check every node concurrently instead of one at a time — with
        # three nodes this is the difference between ~1s and ~3s+ per call.
        results = await asyncio.gather(
            *(_check_node(name, address) for name, address in self.servers.items())
        )
        for name, value in results:
            embed.add_field(name=name, value=value, inline=False)

        embed.timestamp = datetime.datetime.now(datetime.timezone.utc)
        embed.set_footer(text=f"{BRAND_NAME} Network Monitoring")
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="ip", aliases=["serverip", "connect"])
    async def ip(self, ctx):
        embed = discord.Embed(
            title=f"{BRAND_NAME} Connection Info",
            description="Join the network using the details below!",
            color=discord.Color.green(),
        )
        embed.add_field(name="Java IP", value="`play.nextermc.net`", inline=False)
        embed.add_field(name="Bedrock IP", value="`play.nextermc.net`", inline=True)
        embed.add_field(name="Bedrock Port", value="`19132`", inline=True)
        embed.timestamp = datetime.datetime.now(datetime.timezone.utc)
        embed.set_footer(text=f"{BRAND_NAME} Network")
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Minecraft(bot))
