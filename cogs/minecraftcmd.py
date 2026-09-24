import discord
from discord.ext import commands
import datetime

class MinecraftCmd(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="mcguide", aliases=["minecraftcmds", "mcside"])
    async def mcguide(self, ctx):
        embed = discord.Embed(
            title="NexterMC Network Command Center",
            description="Complete reference guide for Minecraft network management and utilities. Use prefix `,` for all commands.",
            color=discord.Color.blurple()
        )
        
        embed.add_field(
            name="🌍 Network & Status",
            value=(
                "`status` - Checks real-time health, ping & player count across Velocity, Main, and PvP nodes.\n"
                "`ip` - Displays Java and Bedrock connection addresses."
            ),
            inline=False
        )

        embed.add_field(
            name="🎮 Player Management & Profiles",
            value=(
                "`mcprofile <username>` - Opens interactive control panel (Skin views, Inventory clearing, AdvancedBan modal, Kick, Inventory Overview).\n"
                "`bug <issue>` - Submits a bug report securely to staff logs."
            ),
            inline=False
        )

        embed.add_field(
            name="⚡ Administrative Infrastructure Panel",
            value=(
                "`panel` - Opens the executive control dashboard to start, stop, restart nodes or toggle global maintenance mode."
            ),
            inline=False
        )

        embed.set_footer(text="NexterMC • Secure Infrastructure Management", icon_url=ctx.bot.user.avatar.url if ctx.bot.user.avatar else None)
        embed.timestamp = datetime.datetime.now()
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(MinecraftCmd(bot))