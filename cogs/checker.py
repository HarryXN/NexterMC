import asyncio
import ast
import datetime
import io
import os

import discord
import psutil
from discord.ext import commands
from mcstatus import JavaServer

from config import BRAND_NAME, MINECRAFT_SERVERS
from permissions import has_permissions_or_owner


def _scan_syntax(root_dir: str) -> tuple[int, list[str]]:
    """Runs in a worker thread — walks the repo and parses every .py file.
    Kept synchronous-but-offloaded so a large codebase doesn't stall the
    bot's event loop while it scans."""
    syntax_errors = []
    python_file_count = 0
    excluded = {".git", "__pycache__", "venv", ".venv", "backups"}
    for root, dirs, files in os.walk(root_dir):
        dirs[:] = [directory for directory in dirs if directory not in excluded and not directory.startswith("deploy")]
        for file in files:
            if not file.endswith(".py"):
                continue
            python_file_count += 1
            file_path = os.path.join(root, file)
            rel_path = os.path.relpath(file_path, root_dir)
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    source = f.read()
                ast.parse(source)
            except SyntaxError as e:
                syntax_errors.append(f"`{rel_path}`: Line {e.lineno} - {e.msg}")
            except Exception as e:
                syntax_errors.append(f"`{rel_path}`: {e}")
    return python_file_count, syntax_errors


class PyChecker(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.servers = list(MINECRAFT_SERVERS.values())

    @commands.hybrid_command(name="check", aliases=["diagnostics", "debug", "health"])
    @has_permissions_or_owner(administrator=True)
    @commands.cooldown(1, 15, commands.BucketType.guild)
    async def check(self, ctx):
        embed = discord.Embed(
            title=f"🔍 {BRAND_NAME} System Diagnostics Inspector",
            description="Running a deep scan across source code, memory usage, environment variables, and node connections...",
            color=discord.Color.gold(),
        )
        msg = await ctx.send(embed=embed)

        # 1. Syntax / file integrity — offloaded so it can't block the gateway heartbeat
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        python_file_count, syntax_errors = await asyncio.to_thread(_scan_syntax, project_root)

        # 2. Environment variables
        token_status = "🟢 Loaded" if os.getenv("DISCORD_TOKEN") else "🔴 Missing (DISCORD_TOKEN)"
        groq_status = "🟢 Loaded" if os.getenv("GROQ_API_KEY") else "🔴 Missing (GROQ_API_KEY — AI commands disabled)"

        # 3. Resource usage — interval=None gives an instant (non-blocking) reading
        #    relative to the last call, instead of sleeping the event loop.
        process = psutil.Process(os.getpid())
        ram_usage = round(process.memory_info().rss / 1024 / 1024, 2)
        cpu_usage = process.cpu_percent(interval=None)

        # 4. Minecraft node status
        node_results = []
        for addr in self.servers:
            try:
                server = await asyncio.wait_for(JavaServer.async_lookup(addr), timeout=2.0)
                status = await server.async_status()
                node_results.append(
                    f"🟢 `{addr}` — Online ({status.players.online} players, {round(status.latency, 1)}ms)"
                )
            except asyncio.TimeoutError:
                node_results.append(f"🟡 `{addr}` — Timeout / Unreachable")
            except Exception:
                node_results.append(f"🔴 `{addr}` — Offline / Down")

        latency = round(self.bot.latency * 1000)

        final_embed = discord.Embed(
            title=f"🛡️ {BRAND_NAME} Advanced Diagnostic Report",
            description=f"Scanned **{python_file_count} active Python files** plus host and server health.",
            color=discord.Color.green() if not syntax_errors else discord.Color.red(),
        )

        if syntax_errors:
            error_text = "\n".join(syntax_errors)
            preview = error_text[:2800]
            final_embed.add_field(
                name="❌ Python Syntax / Read Errors",
                value=preview,
                inline=False,
            )
            if len(error_text) > len(preview):
                final_embed.add_field(
                    name="📎 Full error list",
                    value="The complete list is attached as `python-scan-errors.txt`.",
                    inline=False,
                )
        else:
            final_embed.add_field(
                name="📄 Code Integrity",
                value="🟢 All Python files parsed successfully with zero syntax errors.",
                inline=False,
            )

        final_embed.add_field(
            name="⚙️ Environment & Host Performance",
            value=(
                f"• Bot Token: {token_status}\n"
                f"• Groq API Key: {groq_status}\n"
                f"• Gateway Latency: `{latency}ms`\n"
                f"• RAM Usage: `{ram_usage} MB`\n"
                f"• CPU Usage: `{cpu_usage}%`\n"
                f"• Guilds: `{len(self.bot.guilds)}` • Loaded Cogs: `{len(self.bot.cogs)}`"
            ),
            inline=False,
        )

        final_embed.add_field(
            name="🌍 Minecraft Server Nodes",
            value="\n".join(node_results),
            inline=False,
        )

        final_embed.timestamp = datetime.datetime.now(datetime.timezone.utc)
        final_embed.set_footer(text=f"{BRAND_NAME} Bot Inspector • Secure Diagnostics")

        await msg.edit(embed=final_embed)
        if syntax_errors and len(error_text) > len(preview):
            await ctx.send(
                file=discord.File(io.BytesIO(error_text.encode("utf-8")), filename="python-scan-errors.txt")
            )


async def setup(bot):
    await bot.add_cog(PyChecker(bot))
