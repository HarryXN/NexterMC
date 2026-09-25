# cogs/helpcmd.py
import discord
from discord.ext import commands
import datetime

class HelpCommandCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="help")
    async def help_command(self, ctx):
        embed = discord.Embed(
            title="🌟 NexterMC Control Panel & Command Center",
            description="Welcome to the administrative dashboard. Use prefix `,` for all commands.",
            color=discord.Color.blurple()
        )
        
        # 1. Moderation Suite
        embed.add_field(
            name="🛡️ Moderation Commands",
            value=(
                "`warn <user> [reason]` - Issues a tracked warning with a global ID.\n"
                "`warn remove <id>` - Clears an active warning ID.\n"
                "`ban <user> [reason]` - Permanently bans a disruptive user.\n"
                "`unban <user_id>` - Pardons a banned user ID/name.\n"
                "`timeout <user> [mins] [reason]` - Mutes a user temporarily.\n"
                "`untimeout <user>` - Restores user speaking privileges.\n"
                "`kick <user> [reason]` - Kicks a user from the server."
            ),
            inline=False
        )

        # 2. AI Ticket Audits & Summaries
        embed.add_field(
            name="🤖 AI Ticket & Summary Suite",
            value=(
                "`summarize` - Generates a clean general ticket and troubleshooting summary.\n"
                "`invsummary` - Audits invite claims against rules, checks deductions, and calculates valid counts.\n"
                "`fullsummary` - Compiles a comprehensive master report of the entire ticket conversation."
            ),
            inline=False
        )

        # 3. System Diagnostics & Minecraft Tools
        embed.add_field(
            name="🔍 System Diagnostics & Administration",
            value=(
                "`check` - Runs a deep system scan for RAM/CPU load and node health.\n"
                "`pyfiles` - Displays active repository directory structure."
            ),
            inline=False
        )

        # 4. Utility Tools
        embed.add_field(
            name="✨ Utility & Tools",
            value=(
                "`ping` - Checks bot websocket response latency."
            ),
            inline=False
        )

        embed.set_footer(
            text="NexterMC • Protected Securely", 
            icon_url=ctx.bot.user.avatar.url if ctx.bot.user.avatar else None
        )
        embed.timestamp = datetime.datetime.now()
        
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(HelpCommandCog(bot))