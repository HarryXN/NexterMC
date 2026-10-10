"""Online Minecraft player browser and profile inventory controls."""
from __future__ import annotations

import asyncio
import os
import re

import discord
from discord.ext import commands
from mcstatus import JavaServer

from config import MINECRAFT_SERVERS, PANEL_SERVERS
from permissions import is_owner, member_has_permission, has_permissions_or_owner
from utils.pterodactyl import PanelAPIError, run_server_command, send_server_command

PROFILE_SERVERS = ("main", "pvp")  # Player data lives on backend servers, not the Velocity proxy.
MINECRAFT_QUERY_SERVERS = {
    "main": os.getenv("QUERY_SERVER_MAIN", MINECRAFT_SERVERS["Main Server"]).strip(),
    "velocity": os.getenv("QUERY_SERVER_VELOCITY", MINECRAFT_SERVERS["Velocity Proxy"]).strip(),
    "pvp": os.getenv("QUERY_SERVER_PVP", MINECRAFT_SERVERS["PvP Server"]).strip(),
}
NAME_RE = re.compile(r"^[A-Za-z0-9_]{1,16}$")
COLOR_CODE_RE = re.compile(r"\x1b\[[0-9;]*m")
ITEM_ID_RE = re.compile(r'\bid:\s*"?([a-z0-9_.-]+:[a-zA-Z0-9_./-]+)"?')
ITEM_COUNT_RE = re.compile(r"\b(?:count|Count):\s*(\d+)")


async def _online_names(server_key: str) -> list[str]:
    address = MINECRAFT_QUERY_SERVERS.get(server_key)
    if not address:
        return []
    try:
        server = await asyncio.wait_for(JavaServer.async_lookup(address, timeout=2.5), timeout=3)
        response = await asyncio.wait_for(server.async_query(), timeout=3)
        return list(response.players.names)
    except (asyncio.TimeoutError, OSError, ValueError):
        # Status samples are optional and may not include everyone, but they
        # still provide a useful fallback when Query has not been enabled.
        name = PANEL_SERVERS[server_key]["name"]
        status_address = MINECRAFT_SERVERS.get(name)
        if not status_address:
            return []
        try:
            server = await asyncio.wait_for(JavaServer.async_lookup(status_address, timeout=3), timeout=3.5)
            status = await asyncio.wait_for(server.async_status(), timeout=4)
            return [entry.name for entry in (status.players.sample or []) if getattr(entry, "name", None)]
        except (asyncio.TimeoutError, OSError, ValueError):
            return []


async def _all_online_entries() -> list[tuple[str, str]]:
    results = await asyncio.gather(*(_online_names(key) for key in PROFILE_SERVERS))
    entries: list[tuple[str, str]] = []
    seen: set[str] = set()
    for key, names in zip(PROFILE_SERVERS, results):
        for name in names:
            if NAME_RE.fullmatch(name) and name.casefold() not in seen:
                seen.add(name.casefold())
                entries.append((key, name))
    return entries


def _authorized(interaction: discord.Interaction, requester_id: int) -> bool:
    return bool(
        interaction.user.id == requester_id
        and (
            is_owner(interaction.user.id)
            or member_has_permission(interaction.user, "administrator")
        )
    )


async def _profile_embed(server_key: str, player: str) -> discord.Embed:
    embed = discord.Embed(
        title=f"⛏️ Player Profile · {player}",
        description=f"Server: **{PANEL_SERVERS[server_key]['name']}** · currently online",
        color=discord.Color.from_rgb(41, 190, 176),
    )
    # EssentialsX provides first-login and last-seen history on Main. It cannot
    # reliably tell us which backend a player last used across the network.
    history = await _essentials_command(f"seen {player}", player)
    if history:
        embed.add_field(name="🕒 Account history (Main)", value=history[:900], inline=False)
    else:
        embed.add_field(name="🕒 Account history", value="EssentialsX history is unavailable.", inline=False)
    ping = await _console_command(server_key, f"ping {player}", player, timeout=3.5)
    embed.add_field(name="📶 Player ping", value=ping[:300] if ping else "Unavailable on this server", inline=True)

    selector = f"@a[name={player},limit=1]"
    try:
        data = await run_server_command(
            PANEL_SERVERS[server_key]["identifier"],
            f"data get entity {selector}",
            timeout=3.5,
            expected_output=player,
        )
    except PanelAPIError as exc:
        embed.add_field(name="Player data unavailable", value=str(exc), inline=False)
        return embed

    cleaned = COLOR_CODE_RE.sub("", data).replace("\r", " ").replace("\n", " ")
    if not cleaned:
        embed.add_field(
            name="Player data unavailable",
            value="The server returned no console output. The API key may need console websocket access.",
            inline=False,
        )
        return embed
    if "no entity was found" in cleaned.casefold() or "no entities were found" in cleaned.casefold():
        embed.description = "Player is no longer online on this server. Refresh the player list and try again."
        return embed

    for label, pattern in (
        ("UUID", r"\bUUID:\s*(\[[^\]]+\]|[0-9a-fA-F-]{32,36})"),
        ("Health", r"\bHealth:\s*([-\d.]+)"),
        ("Food", r"\bfoodLevel:\s*(\d+)"),
        ("XP level", r"\bXpLevel:\s*(\d+)"),
        ("Game mode", r"\bplayerGameType:\s*(\d+)"),
        ("Dimension", r'\bDimension:\s*"?([a-z0-9_:.-]+)"?'),
        ("Position", r"\bPos:\s*(\[[^\]]+\])"),
    ):
        match = re.search(pattern, cleaned)
        if match:
            value = match.group(1)
            if label == "Game mode":
                value = {"0": "Survival", "1": "Creative", "2": "Adventure", "3": "Spectator"}.get(value, value)
            embed.add_field(name=label, value=value, inline=True)

    for key, label in (("EnderItems", "📦 Ender Chest"),
                       ("ArmorItems", "🛡️ Armor"), ("HandItems", "✋ Hands")):
        items = _format_inventory(_extract_list(cleaned, key))
        if not items:
            embed.add_field(name=f"{label} · 0", value="Empty or not present in the response.", inline=False)
        else:
            for index in range(0, len(items), 15):
                suffix = f" · {index // 15 + 1}" if len(items) > 15 else ""
                embed.add_field(
                    name=f"{label} · {len(items)}{suffix}",
                    value="\n".join(items[index:index + 15]),
                    inline=False,
                )
    embed.set_footer(text="Use InvSee for the plugin's complete console inventory view")
    return embed


async def _essentials_command(command: str, expected_player: str) -> str:
    """Collect EssentialsX console output, returning a short cleaned reply."""
    try:
        response = await run_server_command(
            PANEL_SERVERS["main"]["identifier"],
            command,
            timeout=5,
            expected_output=expected_player,
            collect_all=True,
        )
    except PanelAPIError:
        return ""
    cleaned = COLOR_CODE_RE.sub("", response)
    lines = [re.sub(r"\s+", " ", line).strip() for line in cleaned.splitlines()]
    lines = [line for line in lines if line and not line.startswith("]")]
    # Discord embeds have a hard limit; retain useful plugin output only.
    return "\n".join(lines[-5:])[:900]


async def _console_command(server_key: str, command: str, expected_player: str, *, timeout: float = 5.0) -> str:
    """Return output from a server console command without exposing transport details."""
    try:
        response = await run_server_command(
            PANEL_SERVERS[server_key]["identifier"],
            command,
            timeout=timeout,
            expected_output=expected_player,
            collect_all=True,
        )
    except PanelAPIError:
        return ""
    cleaned = COLOR_CODE_RE.sub("", response)
    lines = [re.sub(r"\s+", " ", line).strip() for line in cleaned.splitlines()]
    lines = [line for line in lines if line and not line.startswith("]")]
    return "\n".join(lines[-12:])[:950]


ISC_CATEGORIES = {
    "inventory": ("📦 Inventory", ("help", "view", "stats", "scan", "find", "clear", "delete", "set", "swap")),
    "armor_shulker": ("🛡️ Armor & Shulker", ("armor_view", "armor_clear", "armor_set", "shulker_view", "shulker_clear")),
    "snapshots": ("📸 Snapshots", ("snapshot_create", "snapshot_list", "snapshot_show", "snapshot_restore", "snapshot_delete")),
    "logs": ("📜 Audit Logs", ("logs_last", "logs_player", "logs_action")),
    "watchlist": ("👁️ Watchlist", ("watchlist_list", "watchlist_add", "watchlist_remove", "watchlist_reload")),
    "safety": ("🧯 Safety", ("undo",)),
}

ISC_ACTIONS = {
    "help": ("Plugin command help", "isc help", "", False),
    "view": ("View inventory", "isc view {player}", "", False),
    "stats": ("Inventory stats", "isc stats {player}", "", False),
    "scan": ("Watchlist scan", "isc scan {player}", "", False),
    "find": ("Find material", "isc find {args}", "Material ID/name", False),
    "clear": ("Clear inventory", "isc clear {player} {args}", "Slot/target arguments", True),
    "delete": ("Delete item/slot", "isc delete {player} {args}", "Slot/item arguments", True),
    "set": ("Set item/slot", "isc set {player} {args}", "Slot and item arguments", True),
    "swap": ("Swap slots", "isc swap {player} {args}", "Two slot arguments", True),
    "armor_view": ("View armor", "isc armor {player} view", "", False),
    "armor_clear": ("Clear armor", "isc armor {player} clear", "", True),
    "armor_set": ("Set armor", "isc armor {player} set {args}", "Slot and item arguments", True),
    "shulker_view": ("View shulker", "isc shulker view {player} {args}", "Shulker slot", False),
    "shulker_clear": ("Clear shulker", "isc shulker clear {player} {args}", "Shulker slot", True),
    "snapshot_create": ("Create snapshot", "isc snapshot create {player}", "", True),
    "snapshot_list": ("List snapshots", "isc snapshot list", "", False),
    "snapshot_show": ("Show snapshot", "isc snapshot show {args}", "Snapshot ID", False),
    "snapshot_restore": ("Restore snapshot", "isc snapshot restore {args}", "Snapshot ID", True),
    "snapshot_delete": ("Delete snapshot", "isc snapshot delete {args}", "Snapshot ID", True),
    "logs_last": ("Recent audit logs", "isc logs last", "", False),
    "logs_player": ("Logs for player", "isc logs player {player}", "", False),
    "logs_action": ("Logs by action", "isc logs action {args}", "Action name", False),
    "watchlist_list": ("List watchlist", "isc watchlist list", "", False),
    "watchlist_add": ("Add to watchlist", "isc watchlist add {player}", "", True),
    "watchlist_remove": ("Remove from watchlist", "isc watchlist remove {player}", "", True),
    "watchlist_reload": ("Reload watchlist", "isc watchlist reload", "", True),
    "undo": ("Undo latest action", "isc undo {player}", "", True),
}


def _isc_output_embed(server_key: str, player: str, command: str, output: str) -> discord.Embed:
    safe_output = output[:3500].replace("```", "~~~")
    embed = discord.Embed(
        title=f"🧰 InvSeeConsole · {player}",
        description=f"**{PANEL_SERVERS[server_key]['name']}** · `/{command}`\n```text\n{safe_output}\n```",
        color=discord.Color.from_rgb(64, 160, 125),
        timestamp=datetime.datetime.now(datetime.timezone.utc),
    )
    embed.set_footer(text="InvSeeConsole server response")
    return embed


async def _run_isc(server_key: str, command: str, player: str) -> str:
    try:
        response = await run_server_command(
            PANEL_SERVERS[server_key]["identifier"],
            command,
            timeout=6,
            expected_output="InvSeeConsole",
            collect_all=True,
            quiet_period=0.6,
            max_output_lines=80,
        )
    except PanelAPIError as exc:
        return f"Console error: {exc}"
    cleaned = COLOR_CODE_RE.sub("", response).replace("\r", "")
    lines = [line.rstrip() for line in cleaned.splitlines() if line.strip()]
    if not lines:
        return "No InvSeeConsole response was received. Check the plugin is installed on this server and the bot has console access."
    return "\n".join(lines[-45:])


_ISC_CONFIRM_RE = re.compile(r"(?:/isc\s+confirm|confirm(?:ation)?(?:\s+code)?\s*[:=])\s*([A-Za-z0-9_-]{3,32})", re.IGNORECASE)
_ISC_ARGS_RE = re.compile(r"^[A-Za-z0-9_.,:#-]+(?:\s+[A-Za-z0-9_.,:#-]+){0,7}$")


async def _send_isc_result(
    interaction: discord.Interaction,
    requester_id: int,
    server_key: str,
    player: str,
    command: str,
):
    output = await _run_isc(server_key, command, player)
    embed = _isc_output_embed(server_key, player, command, output)
    match = _ISC_CONFIRM_RE.search(output)
    view = ISCTokenConfirmView(requester_id, server_key, player, match.group(1)) if match else None
    await interaction.followup.send(embed=embed, view=view, ephemeral=True)


def _isc_category_embed(category: str) -> discord.Embed:
    title, actions = ISC_CATEGORIES[category]
    labels = "\n".join(f"• {ISC_ACTIONS[action][0]}" for action in actions)
    return discord.Embed(
        title=f"🧰 InvSeeConsole · {title}",
        description=f"Choose an operation below. Changes require confirmation.\n\n{labels}",
        color=discord.Color.from_rgb(64, 160, 125),
    )


class ISCCategorySelect(discord.ui.Select):
    def __init__(self, requester_id: int, server_key: str, player: str):
        options = [
            discord.SelectOption(label=title.split(" ", 1)[1], value=key, emoji=title.split(" ", 1)[0])
            for key, (title, _) in ISC_CATEGORIES.items()
        ]
        super().__init__(placeholder="Select InvSeeConsole tools", options=options)
        self.requester_id = requester_id
        self.server_key = server_key
        self.player = player

    async def callback(self, interaction: discord.Interaction):
        if not _authorized(interaction, self.requester_id):
            await interaction.response.send_message("Administrator permission required.", ephemeral=True)
            return
        category = self.values[0]
        await interaction.response.edit_message(
            embed=_isc_category_embed(category),
            view=ISCActionView(self.requester_id, self.server_key, self.player, category),
        )


class InvSeeToolsView(discord.ui.View):
    def __init__(self, requester_id: int, server_key: str, player: str):
        super().__init__(timeout=180)
        self.add_item(ISCCategorySelect(requester_id, server_key, player))
        close = discord.ui.Button(label="Close", style=discord.ButtonStyle.secondary, emoji="✖️", row=1)
        close.callback = self._close
        self.add_item(close)
        self.requester_id = requester_id

    async def _close(self, interaction: discord.Interaction):
        if not _authorized(interaction, self.requester_id):
            await interaction.response.send_message("This tool menu belongs to another administrator.", ephemeral=True)
            return
        await interaction.response.edit_message(content="InvSeeConsole tools closed.", embed=None, view=None)


class ISCActionView(discord.ui.View):
    def __init__(self, requester_id: int, server_key: str, player: str, category: str):
        super().__init__(timeout=180)
        self.requester_id = requester_id
        self.server_key = server_key
        self.player = player
        self.category = category
        title, actions = ISC_CATEGORIES[category]
        options = [discord.SelectOption(label=ISC_ACTIONS[key][0], value=key) for key in actions]
        select = discord.ui.Select(placeholder=f"Choose {title.split(' ', 1)[1]} action", options=options)
        select.callback = self._choose_action
        self.add_item(select)
        back = discord.ui.Button(label="Back", style=discord.ButtonStyle.secondary, emoji="⬅️", row=1)
        back.callback = self._back
        self.add_item(back)

    async def _choose_action(self, interaction: discord.Interaction):
        if not _authorized(interaction, self.requester_id):
            await interaction.response.send_message("Administrator permission required.", ephemeral=True)
            return
        select = next((item for item in self.children if isinstance(item, discord.ui.Select)), None)
        if not select or not select.values:
            return
        action = select.values[0]
        _, template, arg_label, dangerous = ISC_ACTIONS[action]
        if arg_label:
            await interaction.response.send_modal(
                ISCArgumentsModal(self.requester_id, self.server_key, self.player, action)
            )
            return
        command = template.format(player=self.player, args="").strip()
        if dangerous:
            await interaction.response.send_message(
                f"Confirm running `/{command}` on **{PANEL_SERVERS[self.server_key]['name']}**?",
                view=ISCRunConfirmView(self.requester_id, self.server_key, self.player, command),
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        await _send_isc_result(interaction, self.requester_id, self.server_key, self.player, command)

    async def _back(self, interaction: discord.Interaction):
        if not _authorized(interaction, self.requester_id):
            await interaction.response.send_message("This tool menu belongs to another administrator.", ephemeral=True)
            return
        await interaction.response.edit_message(
            embed=discord.Embed(
                title=f"🧰 InvSeeConsole · {self.player}",
                description="Select a tool group to continue.",
                color=discord.Color.from_rgb(64, 160, 125),
            ),
            view=InvSeeToolsView(self.requester_id, self.server_key, self.player),
        )


class ISCArgumentsModal(discord.ui.Modal):
    def __init__(self, requester_id: int, server_key: str, player: str, action: str):
        label, _, prompt, _ = ISC_ACTIONS[action]
        super().__init__(title=f"InvSeeConsole · {label}")
        self.requester_id = requester_id
        self.server_key = server_key
        self.player = player
        self.action = action
        self.arguments = discord.ui.TextInput(
            label=prompt[:45],
            placeholder="Use the plugin's documented argument format",
            max_length=100,
        )
        self.add_item(self.arguments)

    async def on_submit(self, interaction: discord.Interaction):
        if not _authorized(interaction, self.requester_id):
            await interaction.response.send_message("Administrator permission required.", ephemeral=True)
            return
        args = str(self.arguments.value).strip()
        if not _ISC_ARGS_RE.fullmatch(args):
            await interaction.response.send_message(
                "Use only letters, numbers, spaces, `_ . , : # -` in command arguments.", ephemeral=True
            )
            return
        _, template, _, dangerous = ISC_ACTIONS[self.action]
        command = template.format(player=self.player, args=args).strip()
        if dangerous:
            await interaction.response.send_message(
                f"Confirm running `/{command}` on **{PANEL_SERVERS[self.server_key]['name']}**?",
                view=ISCRunConfirmView(self.requester_id, self.server_key, self.player, command),
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        await _send_isc_result(interaction, self.requester_id, self.server_key, self.player, command)


class ISCRunConfirmView(discord.ui.View):
    def __init__(self, requester_id: int, server_key: str, player: str, command: str):
        super().__init__(timeout=60)
        self.requester_id = requester_id
        self.server_key = server_key
        self.player = player
        self.command = command

    @discord.ui.button(label="Confirm command", style=discord.ButtonStyle.danger, emoji="⚠️")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not _authorized(interaction, self.requester_id):
            await interaction.response.send_message("Only the requesting administrator can confirm this command.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        await _send_isc_result(interaction, self.requester_id, self.server_key, self.player, self.command)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not _authorized(interaction, self.requester_id):
            await interaction.response.send_message("Only the requesting administrator can cancel this command.", ephemeral=True)
            return
        await interaction.response.edit_message(content="Command cancelled.", embed=None, view=None)
        self.stop()


class ISCTokenConfirmView(discord.ui.View):
    def __init__(self, requester_id: int, server_key: str, player: str, code: str):
        super().__init__(timeout=60)
        self.requester_id = requester_id
        self.server_key = server_key
        self.player = player
        self.code = code

    @discord.ui.button(label="Confirm plugin code", style=discord.ButtonStyle.danger, emoji="🔐")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not _authorized(interaction, self.requester_id):
            await interaction.response.send_message("Only the requesting administrator can confirm this plugin code.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        command = f"isc confirm {self.code}"
        output = await _run_isc(self.server_key, command, self.player)
        await interaction.edit_original_response(
            embed=_isc_output_embed(self.server_key, self.player, command, output), view=None
        )
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not _authorized(interaction, self.requester_id):
            await interaction.response.send_message("Only the requesting administrator can cancel this plugin code.", ephemeral=True)
            return
        await interaction.response.edit_message(content="Plugin confirmation cancelled.", embed=None, view=None)
        self.stop()


async def _offline_profile_embed(player: str) -> discord.Embed:
    """Show EssentialsX's stored history for an offline/previously seen player."""
    embed = discord.Embed(
        title=f"⛏️ Player Profile · {player}",
        description="Offline · live inventory and ping require the player to be online.",
        color=discord.Color.from_rgb(115, 130, 145),
    )
    history = await _essentials_command(f"seen {player}", player)
    if history:
        embed.add_field(name="🕒 EssentialsX history (Main)", value=history, inline=False)
    else:
        embed.add_field(
            name="History unavailable",
            value="The Main server did not return EssentialsX `/seen` data. The player may be unknown to that server, or console access/EssentialsX may be unavailable.",
            inline=False,
        )
    embed.add_field(name="Last server", value="Not recorded across Main and PvP.", inline=True)
    embed.set_footer(text="Offline inventory and current ping cannot be retrieved")
    return embed


def _extract_list(text: str, key: str) -> str:
    match = re.search(rf"\b{re.escape(key)}:\s*\[", text)
    if not match:
        return ""
    start = match.end() - 1
    depth = 0
    quoted = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if escaped:
            escaped = False
            continue
        if char == "\\" and quoted:
            escaped = True
            continue
        if char == '"':
            quoted = not quoted
        elif not quoted and char == "[":
            depth += 1
        elif not quoted and char == "]":
            depth -= 1
            if depth == 0:
                return text[start + 1:index]
    return ""


def _format_inventory(raw: str) -> list[str]:
    if not raw:
        return []
    stacks: list[str] = []
    depth = 0
    start = None
    quoted = False
    escaped = False
    compounds: list[str] = []
    for index, char in enumerate(raw):
        if escaped:
            escaped = False
            continue
        if char == "\\" and quoted:
            escaped = True
        elif char == '"':
            quoted = not quoted
        elif not quoted and char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif not quoted and char == "}":
            depth -= 1
            if depth == 0 and start is not None:
                compounds.append(raw[start:index + 1])
    for compound in compounds:
        item = ITEM_ID_RE.search(compound)
        if not item:
            continue
        count = ITEM_COUNT_RE.search(compound)
        slot = re.search(r"\bSlot:\s*(-?\d+)b?", compound)
        details = f"×{count.group(1)} " if count else ""
        slot_text = f"Slot {slot.group(1)} · " if slot else ""
        stacks.append(f"{slot_text}{details}`{item.group(1)}`")
    return stacks


class ClearInventoryConfirm(discord.ui.View):
    def __init__(self, requester_id: int, server_key: str, player: str):
        super().__init__(timeout=60)
        self.requester_id = requester_id
        self.server_key = server_key
        self.player = player

    @discord.ui.button(label="Confirm clear inventory", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not _authorized(interaction, self.requester_id):
            await interaction.response.send_message("❌ Only the requesting administrator can confirm this.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            await send_server_command(
                PANEL_SERVERS[self.server_key]["identifier"], f"clear {self.player}"
            )
            await interaction.followup.send(
                f"✅ Clear-inventory command accepted for **{self.player}** on **{PANEL_SERVERS[self.server_key]['name']}**.",
                ephemeral=True,
            )
        except PanelAPIError as exc:
            await interaction.followup.send(f"❌ {exc}", ephemeral=True)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not _authorized(interaction, self.requester_id):
            await interaction.response.send_message("❌ Only the requesting administrator can cancel this.", ephemeral=True)
            return
        await interaction.response.edit_message(content="Inventory clear cancelled.", view=None)
        self.stop()


class ProfileActionView(discord.ui.View):
    def __init__(self, requester_id: int, server_key: str, player: str):
        super().__init__(timeout=180)
        self.requester_id = requester_id
        self.server_key = server_key
        self.player = player

    @discord.ui.button(label="InvSee", style=discord.ButtonStyle.primary, emoji="🎒", row=0)
    async def invsee(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not _authorized(interaction, self.requester_id):
            await interaction.response.send_message("Administrator permission required.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        await _send_isc_result(
            interaction,
            self.requester_id,
            self.server_key,
            self.player,
            f"isc view {self.player}",
        )

    @discord.ui.button(label="Inventory tools", style=discord.ButtonStyle.secondary, emoji="🧰", row=0)
    async def inventory_tools(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not _authorized(interaction, self.requester_id):
            await interaction.response.send_message("Administrator permission required.", ephemeral=True)
            return
        embed = discord.Embed(
            title=f"🧰 InvSeeConsole · {self.player}",
            description="Choose a tool group to inspect or manage this player's inventory.",
            color=discord.Color.from_rgb(64, 160, 125),
        )
        await interaction.response.send_message(
            embed=embed,
            view=InvSeeToolsView(self.requester_id, self.server_key, self.player),
            ephemeral=True,
        )

    @discord.ui.button(label="Clear all inventory", style=discord.ButtonStyle.danger, emoji="🗑️", row=1)
    async def clear_inventory(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not _authorized(interaction, self.requester_id):
            await interaction.response.send_message("❌ Only the requesting administrator can use this control.", ephemeral=True)
            return
        await interaction.response.send_message(
            f"Clear **all inventory items** for **{self.player}** on **{PANEL_SERVERS[self.server_key]['name']}**?",
            view=ClearInventoryConfirm(self.requester_id, self.server_key, self.player),
            ephemeral=True,
        )


class PlayerPicker(discord.ui.View):
    def __init__(self, requester_id: int, entries: list[tuple[str, str]], page: int = 0):
        super().__init__(timeout=180)
        self.requester_id = requester_id
        self.entries = entries
        self.page = page
        self.pages = max(1, (len(entries) + 24) // 25)
        start = page * 25
        page_entries = entries[start:start + 25]
        options = [
            discord.SelectOption(
                label=f"{player} · {PANEL_SERVERS[key]['name']}"[:100],
                value=f"{key}:{player}",
            )
            for key, player in page_entries
        ]
        if options:
            select = discord.ui.Select(
                placeholder=f"Choose an online player · page {page + 1}/{self.pages}",
                options=options,
            )
            select.callback = self._select_player
            self.add_item(select)
        if self.pages > 1:
            previous = discord.ui.Button(label="Previous", style=discord.ButtonStyle.secondary, row=1, disabled=page == 0)
            previous.callback = self._previous
            self.add_item(previous)
            next_button = discord.ui.Button(label="Next", style=discord.ButtonStyle.secondary, row=1, disabled=page + 1 >= self.pages)
            next_button.callback = self._next
            self.add_item(next_button)

    async def _select_player(self, interaction: discord.Interaction):
        if not _authorized(interaction, self.requester_id):
            await interaction.response.send_message("❌ Administrator permission required.", ephemeral=True)
            return
        select = next((child for child in self.children if isinstance(child, discord.ui.Select)), None)
        if not select or not select.values:
            return
        server_key, player = select.values[0].split(":", 1)
        await interaction.response.defer()
        embed = await _profile_embed(server_key, player)
        await interaction.edit_original_response(
            content=None,
            embed=embed,
            view=ProfileActionView(self.requester_id, server_key, player),
        )

    async def _turn_page(self, interaction: discord.Interaction, page: int):
        if not _authorized(interaction, self.requester_id):
            await interaction.response.send_message("❌ Administrator permission required.", ephemeral=True)
            return
        await interaction.response.edit_message(
            embed=_player_list_embed(self.entries),
            view=PlayerPicker(self.requester_id, self.entries, page),
        )

    async def _previous(self, interaction: discord.Interaction):
        await self._turn_page(interaction, max(0, self.page - 1))

    async def _next(self, interaction: discord.Interaction):
        await self._turn_page(interaction, min(self.pages - 1, self.page + 1))


def _player_list_embed(entries: list[tuple[str, str]]) -> discord.Embed:
    embed = discord.Embed(
        title="👥 Online Minecraft Players",
        description=(
            "Choose a player below to open their live profile. Only currently online "
            "players on Main or PvP are listed."
        ),
        color=discord.Color.from_rgb(41, 190, 176),
    )
    if not entries:
        embed.description = "No online players were found. Check that Minecraft Query is enabled and reachable."
    else:
        for key in PROFILE_SERVERS:
            names = [name for entry_key, name in entries if entry_key == key]
            if names:
                embed.add_field(
                    name=f"{PANEL_SERVERS[key]['name']} · {len(names)} online",
                    value=", ".join(f"`{name}`" for name in names)[:1024],
                    inline=False,
                )
    return embed


class MinecraftProfile(commands.Cog):
    @commands.hybrid_command(name="mcprofile")
    @commands.guild_only()
    @has_permissions_or_owner(administrator=True)
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def mcprofile(self, ctx: commands.Context, username: str | None = None):
        entries = await _all_online_entries()
        if username is None:
            await ctx.send(embed=_player_list_embed(entries), view=PlayerPicker(ctx.author.id, entries))
            return
        if not NAME_RE.fullmatch(username):
            await ctx.send("❌ Enter a valid Minecraft username.")
            return
        found = next((item for item in entries if item[1].casefold() == username.casefold()), None)
        if not found:
            loading = await ctx.reply(f"⏳ Looking up **{username}**'s saved player history…", mention_author=False)
            embed = await _offline_profile_embed(username)
            await loading.edit(content=None, embed=embed, view=None)
            return
        loading = await ctx.reply(f"⏳ Loading **{found[1]}**'s Minecraft profile…", mention_author=False)
        embed = await _profile_embed(*found)
        await loading.edit(content=None, embed=embed, view=ProfileActionView(ctx.author.id, *found))


async def setup(bot: commands.Bot):
    await bot.add_cog(MinecraftProfile())
