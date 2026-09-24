import discord
from discord.ext import commands
import os
import ast
import asyncio
import datetime
from mcstatus import JavaServer

class PyChecker(commands.Cog)
    def __init__(self, bot)
        self.bot = bot
        self.servers = [
            ultimate-1.nextercloud.com25565,
            ultimate-1.nextercloud.com19163,
            ultimate-1.nextercloud.com19165
        ]

    @commands.command(name=check, aliases=[diagnostics, debug, health])
    @commands.has_permissions(administrator=True)
    async def check(self, ctx)
        # Initial loading message
        embed = discord.Embed(
            title=🔍 NexterMC System Diagnostics Inspector,
            description=Running deep-scan across source code, environment variables, and node connections...,
            color=discord.Color.gold()
        )
        msg = await ctx.send(embed=embed)

        # 1. Syntax and File Integrity Check
        syntax_errors = []
        root_dir = os.getcwd()
        
        for root, dirs, files in os.walk(root_dir)
            # Skip hidden folders like .git or __pycache__
            if .git in root or __pycache__ in root
                continue
            for file in files
                if file.endswith(.py)
                    file_path = os.path.join(root, file)
                    rel_path = os.path.relpath(file_path, root_dir)
                    try
                        with open(file_path, r, encoding=utf-8) as f
                            node = f.read()
                        ast.parse(node)
                    except SyntaxError as e
                        syntax_errors.append(f`{rel_path}` Line {e.lineno} - {e.msg})
                    except Exception as e
                        syntax_errors.append(f`{rel_path}` {str(e)})

        # 2. Environment Variables Check
        token_status = 🟢 Loaded if os.getenv(DISCORD_TOKEN) else 🔴 Missing (DISCORD_TOKEN)

        # 3. Minecraft Node Status Check
        node_results = []
        for addr in self.servers
            try
                server = await asyncio.wait_for(JavaServer.async_lookup(addr), timeout=2.5)
                status = await server.async_status()
                node_results.append(f🟢 `{addr}` — Online ({status.players.online} players))
            except asyncio.TimeoutError
                node_results.append(f🟡 `{addr}` — Timeout  Unreachable)
            except Exception
                node_results.append(f🔴 `{addr}` — Offline  Down)

        # 4. Latency Check
        latency = round(self.bot.latency  1000)

        # Build Diagnostic Report Embed
        final_embed = discord.Embed(
            title=🛡️ NexterMC Diagnostic & Error Report,
            description=Results of the automated system and code integrity scan.,
            color=discord.Color.green() if not syntax_errors else discord.Color.red()
        )

        # Code Syntax Section
        if syntax_errors
            final_embed.add_field(
                name=❌ Python Syntax Errors Found,
                value=n.join(syntax_errors),
                inline=False
            )
        else
            final_embed.add_field(
                name=📄 Code Integrity,
                value=🟢 All Python files parsed successfully with zero syntax errors.,
                inline=False
            )

        # Environment & Gateway
        final_embed.add_field(
            name=⚙️ Environment & Gateway,
            value=f• Bot Token {token_status}n• Gateway Latency `{latency}ms`n• Loaded Cogs `{len(self.bot.cogs)}` modules,
            inline=False
        )

        # Minecraft Nodes
        final_embed.add_field(
            name=🌍 Minecraft Server Nodes,
            value=n.join(node_results),
            inline=False
        )

        final_embed.timestamp = datetime.datetime.now()
        final_embed.set_footer(text=NexterMC Diagnostic Tool • Secure Inspector)

        await msg.edit(embed=final_embed)

async def setup(bot)
    await bot.add_cog(PyChecker(bot))