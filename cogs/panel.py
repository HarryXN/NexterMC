"""Interactive, permission-gated control panel for NexterCloud servers."""
from __future__ import annotations

import asyncio
import datetime
import os
import re

import discord
from discord.ext import commands

from config import BRAND_NAME, MINECRAFT_SERVERS, PANEL_SERVERS
from permissions import has_permissions_or_owner, member_has_permission
from mcstatus import JavaServer
from utils.pterodactyl import (
    PanelAPIError,
    get_server_resources,
    send_server_command,
    set_server_power,
)

PLAYER_NAME_RE = re.compile(r"^[A-Za-z0-9_]{1,16}$")
PANEL_COLOR = discord.Color.from_rgb(41, 190, 176)
MINECRAFT_QUERY_SERVERS = {
    "main": os.getenv("QUERY_SERVER_MAIN", MINECRAFT_SERVERS["Main Server"]).strip(),
    "velocity": os.getenv("QUERY_SERVER_VELOCITY", MINECRAFT_SERVERS["Velocity Proxy"]).strip(),
    "pvp": os.getenv("QUERY_SERVER_PVP", MINECRAFT_SERVERS["PvP Server"]).strip(),
}


def _duration(value: int | None) -> str:
    if value is None:
        return "—"
    if value < 1024**3:
        return f"{value / 1024**2:.0f} MiB"
    return f"{value / 1024**3:.2f} GiB"


def _split_player_list(header: str, lines: list[str], limit: int = 1850) -> list[str]:
    """Keep large online rosters below Discord's message length limit."""
    chunks: list[str] = []
    current = header
    for line in lines:
        addition = f"\n{line}"
        if len(current) + len(addition) > limit and current:
            chunks.append(current)
            current = "👥 **Player list continued:**"
        current += f"\n{line}"
    if current:
        chunks.append(current)
    return chunks


def _one_server_embed(key: str, status: dict | Exception) -> discord.Embed:
    server = PANEL_SERVERS[key]
    embed = discord.Embed(
        title=f"🖥️ {BRAND_NAME} • {server['name']}",
        color=discord.Color.red() if isinstance(status, Exception) else PANEL_COLOR,
        timestamp=datetime.datetime.now(datetime.timezone.utc),
    )
    if isinstance(status, Exception):
        embed.description = f"⚠️ Panel status unavailable: {status}"
    else:
        resources = status["resources"]
        state = status["state"].replace("_", " ").title()
        embed.color = (
            discord.Color.green() if state.casefold() == "running"
            else discord.Color.red() if state.casefold() in {"offline", "stopped"}
            else discord.Color.gold()
        )
        indicator = "🟢" if state.casefold() == "running" else "🔴" if state.casefold() == "offline" else "🟡"
        embed.description = f"{indicator} **{state}**" + (" · Suspended" if status["suspended"] else "")
        embed.add_field(name="Memory", value=_duration(resources.get("memory_bytes")), inline=True)
        embed.add_field(
            name="CPU",
            value=(f"{resources['cpu_absolute']:.1f}%" if isinstance(resources.get("cpu_absolute"), (int, float)) else "—"),
            inline=True,
        )
        embed.add_field(name="Disk", value=_duration(resources.get("disk_bytes")), inline=True)
        uptime = resources.get("uptime")
        if isinstance(uptime, (int, float)) and uptime > 0:
            embed.add_field(name="Uptime", value=f"{uptime / 1000 / 3600:.1f} hours", inline=True)
    embed.set_footer(text="Live values from the NexterCloud panel API")
    return embed


async def _check_admin(interaction: discord.Interaction, author_id: int) -> bool:
    if interaction.user.id == author_id and member_has_permission(interaction.user, "administrator"):
        return True
    message = "This control panel belongs to another staff member." if interaction.user.id != author_id else "Administrator permission required."
    if not interaction.response.is_done():
        await interaction.response.send_message(f"❌ {message}", ephemeral=True)
    else:
        await interaction.followup.send(f"❌ {message}", ephemeral=True)
    return False


class ConfirmActionView(discord.ui.View):
    def __init__(self, author_id: int, action: str, server_key: str, *, command: str | None = None):
        super().__init__(timeout=90)
        self.author_id = author_id
        self.action = action
        self.server_key = server_key
        self.command = command

    @discord.ui.button(label="Confirm action", style=discord.ButtonStyle.danger, emoji="⚠️")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await _check_admin(interaction, self.author_id):
            return
        server = PANEL_SERVERS[self.server_key]
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            if self.command is not None:
                await send_server_command(server["identifier"], self.command)
            else:
                await set_server_power(server["identifier"], self.action)
            await interaction.followup.send(
                f"✅ **{self.action.replace('_', ' ').title()}** was accepted for **{server['name']}**.",
                ephemeral=True,
            )
        except PanelAPIError as exc:
            await interaction.followup.send(f"❌ {exc}", ephemeral=True)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await _check_admin(interaction, self.author_id):
            return
        await interaction.response.edit_message(content="Action cancelled.", embed=None, view=None)
        self.stop()


class PlayerActionModal(discord.ui.Modal):
    def __init__(self, author_id: int, server_key: str, action: str):
        super().__init__(title=f"{action.title()} player · {PANEL_SERVERS[server_key]['name']}")
        self.author_id = author_id
        self.server_key = server_key
        self.action = action
        self.player = discord.ui.TextInput(
            label="Minecraft username", placeholder="PlayerName", max_length=16
        )
        self.reason = discord.ui.TextInput(
            label="Reason", placeholder="Reason shown in the punishment message",
            style=discord.TextStyle.paragraph, max_length=180, required=False,
        )
        self.add_item(self.player)
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction):
        if not await _check_admin(interaction, self.author_id):
            return
        username = str(self.player.value).strip()
        if not PLAYER_NAME_RE.fullmatch(username):
            await interaction.response.send_message(
                "❌ Enter a Minecraft Java username using letters, numbers, or underscores (1–16 characters).",
                ephemeral=True,
            )
            return

        reason = re.sub(r"[\x00-\x1f\x7f]", " ", str(self.reason.value)).strip()
        reason = reason[:180] or "Rule violation"
        command = f"{self.action} {username} {reason}"
        server = PANEL_SERVERS[self.server_key]
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            await send_server_command(server["identifier"], command)
            scope = "This punishment is local to this server's configured punishment storage."
            if self.server_key == "main":
                scope = "Submitted to Main's AdvancedBan console."
            elif self.server_key == "pvp":
                scope = "Submitted as a vanilla Minecraft command to PvP."
            await interaction.followup.send(
                f"✅ `{self.action}` for **{username}** was submitted to **{server['name']}**.\n{scope}",
                ephemeral=True,
            )
        except PanelAPIError as exc:
            await interaction.followup.send(f"❌ {exc}", ephemeral=True)


class MaintenanceConfirmView(discord.ui.View):
    def __init__(self, author_id: int, enable: bool):
        super().__init__(timeout=90)
        self.author_id = author_id
        self.enable = enable

    @discord.ui.button(label="Confirm network maintenance", style=discord.ButtonStyle.danger, emoji="🛠️")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await _check_admin(interaction, self.author_id):
            return
        action = "on" if self.enable else "off"
        command = f"maintenance {action} global"
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            await send_server_command(PANEL_SERVERS["velocity"]["identifier"], command)
            state = "ON" if self.enable else "OFF"
            await interaction.followup.send(
                f"✅ Sent `{command}` to the Velocity console. Network maintenance **{state}** was accepted; this blocks/allows network joins.",
                ephemeral=True,
            )
        except PanelAPIError as exc:
            await interaction.followup.send(f"❌ {exc}", ephemeral=True)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await _check_admin(interaction, self.author_id):
            return
        await interaction.response.edit_message(content="Maintenance change cancelled.", embed=None, view=None)
        self.stop()


class ServerPanelView(discord.ui.View):
    def __init__(self, author_id: int, selected: str = "main"):
        super().__init__(timeout=600)
        self.author_id = author_id
        self.selected = selected
        self.message: discord.Message | None = None
        self.controls_loaded = False
        self.hidden_controls = [child for child in self.children if isinstance(child, discord.ui.Button)]
        for child in self.hidden_controls:
            self.remove_item(child)
        options = [
            discord.SelectOption(label="Main Server", value="main", emoji="🟩"),
            discord.SelectOption(label="Velocity", value="velocity", emoji="🌐"),
            discord.SelectOption(label="PvP Server", value="pvp", emoji="⚔️"),
        ]
        select = discord.ui.Select(placeholder="Select one", options=options, row=0)
        self.selector = select
        select.callback = self._select_server
        self.add_item(select)

    async def _select_server(self, interaction: discord.Interaction):
        if not await _check_admin(interaction, self.author_id):
            return
        select = next((item for item in self.children if isinstance(item, discord.ui.Select)), None)
        if select and select.values:
            self.selected = select.values[0]
            for option in self.selector.options:
                option.default = option.value == self.selected
        if not self.controls_loaded:
            for button in self.hidden_controls:
                self.add_item(button)
            self.controls_loaded = True
        self.selector.placeholder = f"🧭 {PANEL_SERVERS[self.selected]['name']} · change server"
        await self._refresh(interaction)

    async def _refresh(self, interaction: discord.Interaction):
        server = PANEL_SERVERS[self.selected]
        await interaction.response.defer()
        await interaction.edit_original_response(
            embed=discord.Embed(
                title=f"⏳ Connecting to {server['name']}…",
                description="Fetching live server status and preparing controls.",
                color=discord.Color.blurple(),
            ),
            view=self,
        )
        try:
            status = await get_server_resources(server["identifier"])
            embed = _one_server_embed(self.selected, status)
        except PanelAPIError as exc:
            embed = _one_server_embed(self.selected, exc)
        await interaction.edit_original_response(embed=embed, view=self)

    async def _authorize(self, interaction: discord.Interaction) -> bool:
        return await _check_admin(interaction, self.author_id)

    async def _player_sample(self) -> tuple[int, int, list[str], bool]:
        name = PANEL_SERVERS[self.selected]["name"]
        status_address = MINECRAFT_SERVERS.get(name)
        query_address = MINECRAFT_QUERY_SERVERS.get(self.selected)
        if not status_address or not query_address:
            raise RuntimeError("No Minecraft status or Query address is configured for this server.")

        # Query returns the full online roster when enable-query is enabled and
        # its UDP port is reachable. Java status samples are optional and partial.
        try:
            query_server = await asyncio.wait_for(
                JavaServer.async_lookup(query_address, timeout=3), timeout=4
            )
            query = await asyncio.wait_for(query_server.async_query(), timeout=5)
            return (
                query.players.online,
                query.players.max,
                list(query.players.names),
                True,
            )
        except (asyncio.TimeoutError, OSError, ValueError):
            pass

        # Keep a best-effort fallback, but label its names as a sample rather
        # than implying that the list is complete.
        status_server = await asyncio.wait_for(
            JavaServer.async_lookup(status_address, timeout=4), timeout=5
        )
        status = await asyncio.wait_for(status_server.async_status(), timeout=5)
        sample = getattr(status.players, "sample", None) or []
        names = [player.name for player in sample if getattr(player, "name", None)]
        return status.players.online, status.players.max, names, False

    @discord.ui.button(label="Refresh", style=discord.ButtonStyle.primary, emoji="🔄", row=1)
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await self._authorize(interaction):
            await self._refresh(interaction)

    @discord.ui.button(label="Start", style=discord.ButtonStyle.success, emoji="▶️", row=1)
    async def start(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await self._authorize(interaction):
            name = PANEL_SERVERS[self.selected]["name"]
            await interaction.response.send_message(
                f"Start **{name}**?", view=ConfirmActionView(self.author_id, "start", self.selected), ephemeral=True
            )

    @discord.ui.button(label="Restart", style=discord.ButtonStyle.primary, emoji="🔁", row=1)
    async def restart(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await self._authorize(interaction):
            name = PANEL_SERVERS[self.selected]["name"]
            await interaction.response.send_message(
                f"Restart **{name}**?", view=ConfirmActionView(self.author_id, "restart", self.selected), ephemeral=True
            )

    @discord.ui.button(label="Stop", style=discord.ButtonStyle.danger, emoji="⏹️", row=1)
    async def stop_server(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await self._authorize(interaction):
            name = PANEL_SERVERS[self.selected]["name"]
            await interaction.response.send_message(
                f"Stop **{name}**?", view=ConfirmActionView(self.author_id, "stop", self.selected), ephemeral=True
            )

    @discord.ui.button(label="Ban player", style=discord.ButtonStyle.danger, emoji="🔨", row=2)
    async def ban(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._authorize(interaction):
            return
        if self.selected == "velocity":
            await interaction.response.send_message("Choose Main or PvP for a ban action.", ephemeral=True)
            return
        await interaction.response.send_modal(PlayerActionModal(self.author_id, self.selected, "ban"))

    @discord.ui.button(label="Kick player", style=discord.ButtonStyle.secondary, emoji="👢", row=2)
    async def kick(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._authorize(interaction):
            return
        if self.selected == "velocity":
            await interaction.response.send_message("Choose Main or PvP for a kick action.", ephemeral=True)
            return
        await interaction.response.send_modal(PlayerActionModal(self.author_id, self.selected, "kick"))

    @discord.ui.button(label="Players", style=discord.ButtonStyle.secondary, emoji="👥", row=2)
    async def players(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._authorize(interaction):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            online, maximum, names, complete_roster = await self._player_sample()
            header = f"👥 **{online}/{maximum} players online** on **{PANEL_SERVERS[self.selected]['name']}**."
            lines: list[str] = []
            if names:
                lines.extend(f"• `{discord.utils.escape_mentions(name)}`" for name in names)
                if not complete_roster:
                    lines.extend([
                        "",
                        "⚠️ This is only the server status sample and may be incomplete.",
                        "Enable Minecraft Query to show the full online list.",
                    ])
            elif online == 0:
                lines.append("No players are online.")
                if not complete_roster:
                    lines.append("⚠️ Query is unavailable, so the server status was used.")
            else:
                lines.extend([
                    "The server did not return player names.",
                    "Enable Minecraft Query and check its UDP query port to show the full online list.",
                ])
            chunks = _split_player_list(header, lines)
            await interaction.followup.send(chunks[0], ephemeral=True)
            for chunk in chunks[1:]:
                await interaction.followup.send(chunk, ephemeral=True)
        except (asyncio.TimeoutError, OSError, ValueError, RuntimeError) as exc:
            detail = str(exc) if isinstance(exc, RuntimeError) else "Minecraft status query timed out or is unavailable."
            await interaction.followup.send(f"⚠️ {detail}", ephemeral=True)

    @discord.ui.button(label="Maintenance ON", style=discord.ButtonStyle.danger, emoji="🚧", row=3)
    async def maintenance_on(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await self._authorize(interaction):
            await interaction.response.send_message(
                "This enables maintenance globally on Velocity and prevents players joining the network. Continue?",
                view=MaintenanceConfirmView(self.author_id, True), ephemeral=True,
            )

    @discord.ui.button(label="Maintenance OFF", style=discord.ButtonStyle.success, emoji="✅", row=3)
    async def maintenance_off(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await self._authorize(interaction):
            await interaction.response.send_message(
                "This disables global Velocity maintenance and allows players to join. Continue?",
                view=MaintenanceConfirmView(self.author_id, False), ephemeral=True,
            )

    @discord.ui.button(label="Ping server", style=discord.ButtonStyle.primary, emoji="📶", row=4)
    async def ping_server(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._authorize(interaction):
            return
        server_name = PANEL_SERVERS[self.selected]["name"]
        address = MINECRAFT_SERVERS.get(server_name)
        if not address:
            await interaction.response.send_message("⚠️ No Minecraft address is configured for this server.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            status_server = await asyncio.wait_for(JavaServer.async_lookup(address), timeout=4)
            status = await asyncio.wait_for(status_server.async_status(), timeout=5)
            embed = discord.Embed(
                title=f"📶 {server_name} · Network latency",
                description=f"**{status.latency:.1f} ms**\n🟢 Minecraft status ping succeeded.",
                color=discord.Color.green() if status.latency < 150 else discord.Color.gold(),
                timestamp=datetime.datetime.now(datetime.timezone.utc),
            )
            embed.set_footer(text=f"Probe: {address} · live Java status ping")
        except (asyncio.TimeoutError, OSError, ValueError) as exc:
            embed = discord.Embed(
                title=f"📶 {server_name} · Ping unavailable",
                description="The Minecraft status endpoint did not respond. Check the public host, port, and firewall.",
                color=discord.Color.red(),
                timestamp=datetime.datetime.now(datetime.timezone.utc),
            )
            embed.set_footer(text=f"Probe: {address}")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary, emoji="⬅️", row=4)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._authorize(interaction):
            return
        for control in self.hidden_controls:
            if control in self.children:
                self.remove_item(control)
        self.controls_loaded = False
        self.selected = "main"
        self.selector.placeholder = "Select one"
        for option in self.selector.options:
            option.default = False
        await interaction.response.edit_message(embed=_selector_embed(), view=self)


def _overview_embed(statuses: dict[str, dict | Exception]) -> discord.Embed:
    embed = discord.Embed(
        title=f"🎮 {BRAND_NAME} Server Control",
        description="Choose a server below to inspect live resource status and run approved staff actions.",
        color=PANEL_COLOR,
        timestamp=datetime.datetime.now(datetime.timezone.utc),
    )
    for key, status in statuses.items():
        server = PANEL_SERVERS[key]
        if isinstance(status, Exception):
            value = f"⚠️ Status unavailable: {status}"
        else:
            resources = status["resources"]
            state = status["state"].replace("_", " ").title()
            indicator = "🟢" if state.casefold() == "running" else "🔴" if state.casefold() == "offline" else "🟡"
            cpu = resources.get("cpu_absolute")
            value = f"{indicator} **{state}** · RAM {_duration(resources.get('memory_bytes'))} · CPU {cpu:.1f}%" if isinstance(cpu, (int, float)) else f"{indicator} **{state}** · RAM {_duration(resources.get('memory_bytes'))}"
        embed.add_field(name=server["name"], value=value, inline=False)
    embed.add_field(
        name="Network Maintenance",
        value="Controls global join access through the **Velocity** console; each change asks for confirmation.",
        inline=False,
    )
    embed.set_footer(text="Power and moderation actions are confirmation-gated")
    return embed


def _selector_embed() -> discord.Embed:
    embed = discord.Embed(
        title=f"🎮 {BRAND_NAME} · Server Control",
        description=(
            "Choose a server from **Select one** to open its live dashboard.\n\n"
            "🟩 **Main Server**\n🌐 **Velocity**\n⚔️ **PvP Server**"
        ),
        color=PANEL_COLOR,
        timestamp=datetime.datetime.now(datetime.timezone.utc),
    )
    embed.set_footer(text="Live status · staff controls · network latency")
    return embed


class AdminPanel(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(name="panel", aliases=["adminpanel", "control"])
    @commands.guild_only()
    @has_permissions_or_owner(administrator=True)
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def panel(self, ctx: commands.Context):
        view = ServerPanelView(ctx.author.id)
        message = await ctx.send(embed=_selector_embed(), view=view, delete_after=900)
        view.message = message


async def setup(bot: commands.Bot):
    await bot.add_cog(AdminPanel(bot))
