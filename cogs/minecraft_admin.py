"""Administrator-only Minecraft console commands."""
from __future__ import annotations

import re

import discord
from discord.ext import commands

from config import PANEL_SERVERS
from permissions import has_permissions_or_owner
from utils.pterodactyl import PanelAPIError, send_server_command

PLAYER_RE = re.compile(r"^[A-Za-z0-9_]{1,16}$")
SERVER_ALIASES = {"main": "main", "velocity": "velocity", "proxy": "velocity", "pvp": "pvp"}
NETWORK_BACKENDS = ("main", "pvp")


def _server_key(value: str, *, backends_only: bool = True) -> str:
    key = SERVER_ALIASES.get(value.casefold())
    if key is None or (backends_only and key == "velocity"):
        raise commands.BadArgument("Choose `main` or `pvp`.")
    return key


async def _run(server_key: str, command: str) -> str:
    server = PANEL_SERVERS[server_key]
    try:
        await send_server_command(server["identifier"], command)
        return f"✅ **{server['name']}** — `{command}` accepted."
    except PanelAPIError as exc:
        return f"❌ **{server['name']}** — {exc}"


class MinecraftAdmin(commands.Cog):
    """Staff controls using the Pterodactyl client API."""

    @commands.hybrid_command(name="whitelist")
    @commands.guild_only()
    @has_permissions_or_owner(administrator=True)
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def whitelist(self, ctx: commands.Context, action: str, player: str, server: str = "both"):
        action = action.casefold()
        if action not in {"add", "remove"}:
            await ctx.send("Usage: `,whitelist <add|remove> <player> [main|pvp|both]`")
            return
        if not PLAYER_RE.fullmatch(player):
            await ctx.send("❌ Enter a valid Minecraft username (1–16 letters, numbers, or underscores).")
            return
        keys = NETWORK_BACKENDS if server.casefold() == "both" else (_server_key(server),)
        results = await _run_all(keys, f"whitelist {action} {player}")
        await ctx.send(embed=_result_embed(f"📋 Whitelist · {player}", results))

    @commands.hybrid_command(name="broadcast")
    @commands.guild_only()
    @has_permissions_or_owner(administrator=True)
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def broadcast(self, ctx: commands.Context, *, message: str):
        message = _clean_text(message, 240)
        if not message:
            await ctx.send("❌ Add a message to broadcast.")
            return
        results = await _run_all(NETWORK_BACKENDS, f"say [NexterMC] {message}")
        await ctx.send(embed=_result_embed("📢 Network Broadcast", results))

    @commands.hybrid_command(name="mcban")
    @commands.guild_only()
    @has_permissions_or_owner(administrator=True)
    @commands.cooldown(1, 4, commands.BucketType.user)
    async def mcban(self, ctx: commands.Context, server: str, player: str, *, reason: str = "Banned by staff"):
        await self._punish(ctx, "ban", server, player, reason)

    @commands.hybrid_command(name="mckick")
    @commands.guild_only()
    @has_permissions_or_owner(administrator=True)
    @commands.cooldown(1, 4, commands.BucketType.user)
    async def mckick(self, ctx: commands.Context, server: str, player: str, *, reason: str = "Kicked by staff"):
        await self._punish(ctx, "kick", server, player, reason)

    @commands.hybrid_command(name="mcunban")
    @commands.guild_only()
    @has_permissions_or_owner(administrator=True)
    @commands.cooldown(1, 4, commands.BucketType.user)
    async def mcunban(self, ctx: commands.Context, server: str, player: str):
        if not PLAYER_RE.fullmatch(player):
            await ctx.send("❌ Enter a valid Minecraft username.")
            return
        key = _server_key(server)
        command = f"unban {player}" if key == "main" else f"pardon {player}"
        result = await _run(key, command)
        await ctx.send(embed=_result_embed(f"🔓 Unban · {player}", [result]))

    async def _punish(self, ctx, action: str, server: str, player: str, reason: str):
        if not PLAYER_RE.fullmatch(player):
            await ctx.send("❌ Enter a valid Minecraft username.")
            return
        key = _server_key(server)
        reason = _clean_text(reason, 160) or "Rule violation"
        result = await _run(key, f"{action} {player} {reason}")
        await ctx.send(embed=_result_embed(f"⚒️ {action.title()} · {player}", [result]))

    @commands.hybrid_command(name="weather")
    @commands.guild_only()
    @has_permissions_or_owner(administrator=True)
    @commands.cooldown(1, 4, commands.BucketType.user)
    async def weather(self, ctx: commands.Context, condition: str, duration: int = 600, server: str = "both"):
        condition = condition.casefold()
        if condition not in {"clear", "rain", "thunder"}:
            await ctx.send("Usage: `,weather <clear|rain|thunder> [seconds] [main|pvp|both]`")
            return
        if not 1 <= duration <= 1000000:
            await ctx.send("❌ Duration must be between 1 and 1,000,000 seconds.")
            return
        keys = NETWORK_BACKENDS if server.casefold() == "both" else (_server_key(server),)
        results = await _run_all(keys, f"weather {condition} {duration}")
        await ctx.send(embed=_result_embed(f"🌦️ Weather · {condition.title()}", results))

    @commands.hybrid_command(name="nick")
    @commands.guild_only()
    @has_permissions_or_owner(administrator=True)
    @commands.cooldown(1, 4, commands.BucketType.user)
    async def nick(self, ctx: commands.Context, player: str, nickname: str, server: str = "both"):
        if not PLAYER_RE.fullmatch(player):
            await ctx.send("❌ Enter a valid Minecraft username.")
            return
        nickname = _clean_text(nickname, 32)
        if not nickname:
            await ctx.send("Usage: `,nick <player> <nickname|off> [main|pvp|both]`")
            return
        keys = NETWORK_BACKENDS if server.casefold() == "both" else (_server_key(server),)
        results = await _run_all(keys, f"nick {player} {nickname}")
        await ctx.send(embed=_result_embed(f"🪪 Essentials nickname · {player}", results))


async def _run_all(keys, command: str) -> list[str]:
    results = []
    for key in keys:
        results.append(await _run(key, command))
    return results


def _clean_text(value: str, maximum: int) -> str:
    return re.sub(r"[\x00-\x1f\x7f]", " ", value).strip()[:maximum]


def _result_embed(title: str, results: list[str]) -> discord.Embed:
    embed = discord.Embed(title=title, color=discord.Color.from_rgb(41, 190, 176))
    embed.description = "\n".join(results)
    return embed


async def setup(bot: commands.Bot):
    await bot.add_cog(MinecraftAdmin())
