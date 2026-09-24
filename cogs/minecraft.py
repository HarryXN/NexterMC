import discord
from discord.ext import commands
import datetime
from mcstatus import JavaServer

class Minecraft(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Define your network endpoints
        self.servers = {
            "Velocity Proxy": "ultimate-1.nextercloud.com:25565",
            "Main Server": "ultimate-1.nextercloud.com:19163",
            "PvP Server": "ultimate-1.nextercloud.com:19165"
        }

    @commands.command(name="status", aliases=["mcstatus", "servers"])
    async def status(self, ctx):
        embed = discord.Embed(
            title="NexterMC Network Status",
            description="Real-time health check for NexterMC Network hosted by NexterCloud",
            color=discord.Color.blurple()
        )
        embed.timestamp = datetime.datetime.now()

        for name, address in self.servers.items():
            try:
                # Lookup server asynchronously
                server = await JavaServer.async_lookup(address)
                status = await server.async_status()
                
                info_text = (
                    f"**Status:** 🟢 Online\n"
                    f"**Players:** `{status.players.online}/{status.players.max}`\n"
                    f"**Latency:** `{round(status.latency)}ms`\n"
                    f"**Address:** `{address}`"
                )
                embed.add_field(name=name, value=info_text, inline=False)
            except Exception:
                info_text = (
                    f"**Status:** 🔴 Offline / Unreachable\n"
                    f"**Address:** `{address}`"
                )
                embed.add_field(name=name, value=info_text, inline=False)

        embed.set_footer(text="NexterMC Network Monitoring")
        await ctx.send(embed=embed)

    @commands.command(name="ip", aliases=["serverip", "connect"])
    async def ip(self, ctx):
        embed = discord.Embed(
            title="NexterMC Connection Info",
            description="Join our Minecraft network using the details below!",
            color=discord.Color.green()
        )
        embed.add_field(name="Server IP Java/Bedrock", value="`play.nextermc.net`", inline=False)
        embed.add_field(name="Bedrock Port", value="`19132` (via Geyser)", inline=False)
        embed.timestamp = datetime.datetime.now()
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(Minecraft(bot))