import discord
from discord.ext import commands
import os
import datetime

class PyFiles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="pyfiles", aliases=["files", "directory"])
    async def pyfiles(self, ctx):
        root_dir = os.getcwd()
        
        root_files = []
        cogs_files = []

        # Scan root directory
        for item in os.listdir(root_dir):
            item_path = os.path.join(root_dir, item)
            if os.path.isfile(item_path):
                root_files.append(item)
            elif item == "cogs" and os.path.isdir(item_path):
                for cog_item in os.listdir(item_path):
                    if os.path.isfile(os.path.join(item_path, cog_item)):
                        cogs_files.append(cog_item)

        root_list = "\n".join([f"📄 `{f}`" for f in sorted(root_files)]) or "No files found"
        cogs_list = "\n".join([f"⚙️ `{f}`" for f in sorted(cogs_files)]) or "No cogs found"

        embed = discord.Embed(
            title="📁 NexterMC Project Directory Structure",
            description="Live inventory of all source files loaded in your bot repository.",
            color=discord.Color.dark_teal()
        )
        embed.add_field(name="Root Workspace Files", value=root_list, inline=False)
        embed.add_field(name="Cogs Module Files (`/cogs`)", value=cogs_list, inline=False)
        embed.timestamp = datetime.datetime.now()
        embed.set_footer(text="NexterMC Deployment Inspector")

        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(PyFiles(bot))