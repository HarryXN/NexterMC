import datetime
import os

import discord
from discord.ext import commands

from config import BRAND_NAME


class PyFiles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _list_dir(self, path: str) -> list[str]:
        if not os.path.isdir(path):
            return []
        return sorted(f for f in os.listdir(path) if os.path.isfile(os.path.join(path, f)))

    @commands.hybrid_command(name="pyfiles", aliases=["files", "directory"])
    async def pyfiles(self, ctx):
        root_dir = os.getcwd()

        root_files = self._list_dir(root_dir)
        cogs_files = self._list_dir(os.path.join(root_dir, "cogs"))
        utils_files = self._list_dir(os.path.join(root_dir, "utils"))

        def fmt(files, icon):
            return "\n".join(f"{icon} `{f}`" for f in files) or "No files found"

        embed = discord.Embed(
            title=f"📁 {BRAND_NAME} Project Directory Structure",
            description="Live inventory of all source files loaded in the bot repository.",
            color=discord.Color.dark_teal(),
        )
        embed.add_field(name="Root Workspace Files", value=fmt(root_files, "📄")[:1024], inline=False)
        embed.add_field(name="Cogs (`/cogs`)", value=fmt(cogs_files, "⚙️")[:1024], inline=False)
        embed.add_field(name="Shared Utilities (`/utils`)", value=fmt(utils_files, "🧩")[:1024], inline=False)
        embed.timestamp = datetime.datetime.now(datetime.timezone.utc)
        embed.set_footer(text=f"{BRAND_NAME} Deployment Inspector")

        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(PyFiles(bot))
