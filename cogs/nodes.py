"""Read-only Pterodactyl node capacity view and admin-managed directory."""
from __future__ import annotations

import asyncio
import datetime
import ipaddress
import json
import logging
import os
import re
import shutil
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

import aiohttp
import discord
from discord.ext import commands

from config import PANEL_APP_API_KEY, PANEL_URL
from permissions import has_permissions_or_owner, is_owner

log = logging.getLogger("nextermc.nodes")
DATA_DIR = Path(__file__).resolve().parents[1] / "data"
OVERRIDES_FILE = DATA_DIR / "node_status_overrides.json"
REGISTRY_FILE = DATA_DIR / "node_registry.json"
HIDDEN_NODES_FILE = DATA_DIR / "node_hidden.json"
DEFAULT_MAINTENANCE = {"cheap-node-1"}
_APP_CACHE_SECONDS = 45
_APP_CACHE = {"updated": 0.0, "value": None}
_APP_LAST_ERROR: str | None = None


def _application_api_failure(status: int) -> str:
    if status == 401:
        return "HTTP 401 · invalid key or wrong key type"
    if status == 403:
        return "HTTP 403 · check Application API Nodes:Read permission"
    if status == 404:
        return "HTTP 404 · check PANEL_URL and the API route"
    if status == 429:
        return "HTTP 429 · panel rate limit; retry shortly"
    if status >= 500:
        return f"HTTP {status} · panel/server error"
    return f"HTTP {status} · request rejected"

DEFAULT_NODES = [
    {"key": "free-node-1", "name": "Free Node 1", "host": "local-it1-free.nextercloud.in", "processor": "Intel Gold", "location": "Europe", "aliases": ["free1", "free-1", "it-i-free", "it-1-free"]},
    {"key": "free-node-2", "name": "Free Node 2", "host": "local-it2-free.nextercloud.in", "processor": "Intel Gold", "location": "Europe", "aliases": ["free2", "free-2", "it-ii-free", "it-2-free"]},
    {"key": "cheap-node-1", "name": "Cheap 1", "host": "cheap-1.nextercloud.com", "processor": "Intel Platinum 8163", "location": "India", "aliases": ["cheap1", "cheap-1", "cf-cheap-1"]},
    {"key": "cheap-node-2", "name": "Cheap 2", "host": "cheap-2.nextercloud.com", "processor": "Intel Xeon 2650 v2", "location": "India", "aliases": ["cheap2", "cheap-2"]},
    {"key": "power-node", "name": "Power Node", "host": "power-1.nextercloud.com", "processor": "AMD EPYC 7513", "location": "India", "aliases": ["power", "power1", "power-1"]},
    {"key": "ultimate-1", "name": "Ultimate 1", "host": "ultimate-1.nextercloud.com", "processor": "AMD EPYC 7542", "location": "India", "aliases": ["ultimate1", "ultimate-1"]},
    {"key": "ultimate-2", "name": "Ultimate 2", "host": "ultimate-2.nextercloud.in", "processor": "Ryzen 7 7700X", "location": "India", "aliases": ["ultimate2", "ultimate-2"]},
    {"key": "ultimate-3", "name": "Ultimate 3 · Titan", "host": "ultimate-3.nextercloud.in", "processor": "Ryzen 7 7700X", "location": "India and Singapore", "aliases": ["ultimate3", "ultimate-3", "titan", "titan-node"]},
]


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _key_for(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")


def _read_nodes() -> list[dict]:
    try:
        content = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
        if isinstance(content, list):
            return [node for node in content if isinstance(node, dict) and node.get("key") and node.get("name")]
    except FileNotFoundError:
        pass
    except (OSError, json.JSONDecodeError):
        log.exception("Could not read node registry; using built-in defaults")
    return [dict(node) for node in DEFAULT_NODES]


def _write_nodes(nodes: list[dict]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    temp_file = REGISTRY_FILE.with_suffix(".tmp")
    temp_file.write_text(json.dumps(nodes, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temp_file, REGISTRY_FILE)


def _read_hidden_nodes() -> set[str]:
    try:
        data = json.loads(HIDDEN_NODES_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return {str(item) for item in data}
    except FileNotFoundError:
        pass
    except (OSError, json.JSONDecodeError):
        log.exception("Could not read hidden node list")
    return set()


def _write_hidden_nodes(nodes: set[str]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    temp_file = HIDDEN_NODES_FILE.with_suffix(".tmp")
    temp_file.write_text(json.dumps(sorted(nodes), indent=2) + "\n", encoding="utf-8")
    os.replace(temp_file, HIDDEN_NODES_FILE)


async def _fetch_application_snapshot() -> tuple[list[dict], dict[str, dict]] | None:
    """Read node and location metadata from Pterodactyl; every request is GET-only."""
    global _APP_LAST_ERROR
    if not PANEL_APP_API_KEY:
        _APP_LAST_ERROR = "PANEL_APP_API_KEY missing at bot startup"
        return None
    if PANEL_APP_API_KEY.casefold().startswith("ptlc_"):
        _APP_LAST_ERROR = "Client API key detected · use an Application API key"
        log.warning("Panel node API not called: PANEL_APP_API_KEY has a client-key prefix")
        return None
    if _APP_CACHE["value"] is not None and time.monotonic() - _APP_CACHE["updated"] < _APP_CACHE_SECONDS:
        _APP_LAST_ERROR = None
        return _APP_CACHE["value"]

    headers = {
        "Authorization": f"Bearer {PANEL_APP_API_KEY}",
        "Accept": "Application/vnd.pterodactyl.v1+json",
    }
    timeout = aiohttp.ClientTimeout(total=12, connect=5)
    try:
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(
                f"{PANEL_URL}/api/application/nodes",
                params={"include": "location,allocations,servers", "per_page": 100},
            ) as response:
                if response.status >= 400:
                    _APP_LAST_ERROR = _application_api_failure(response.status)
                    log.warning("Application API node read failed: %s", _APP_LAST_ERROR)
                    return None
                node_payload = await response.json(content_type=None)
                if not isinstance(node_payload, dict) or not isinstance(node_payload.get("data"), list):
                    _APP_LAST_ERROR = "invalid node-list response"
                    log.warning("Application API node read failed: response did not contain a node list")
                    return None

            location_map: dict[str, dict] = {}
            try:
                async with session.get(
                    f"{PANEL_URL}/api/application/locations", params={"per_page": 100}
                ) as response:
                    if response.status < 400:
                        location_payload = await response.json(content_type=None)
                        for row in location_payload.get("data", []):
                            attrs = row.get("attributes", {})
                            location_map[str(attrs.get("id", row.get("id", "")))] = attrs
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
                log.info("Application API location lookup unavailable; using node metadata only")

        snapshot = (node_payload.get("data", []), location_map)
        _APP_CACHE.update(updated=time.monotonic(), value=snapshot)
        _APP_LAST_ERROR = None
        return snapshot
    except asyncio.TimeoutError:
        _APP_LAST_ERROR = "timeout contacting panel"
        log.warning("Application API node read timed out")
        return None
    except aiohttp.ClientConnectorError as exc:
        _APP_LAST_ERROR = "DNS/connection failure contacting panel"
        log.warning("Application API connection failed (%s)", type(exc).__name__)
        return None
    except aiohttp.ClientError as exc:
        _APP_LAST_ERROR = "network/TLS error contacting panel"
        log.warning("Application API transport failed (%s)", type(exc).__name__)
        return None
    except ValueError as exc:
        _APP_LAST_ERROR = "invalid JSON from panel"
        log.warning("Application API response was invalid JSON (%s)", type(exc).__name__)
        return None


def _api_location(row: dict, location_map: dict[str, dict]) -> str | None:
    relationships = row.get("relationships", {})
    relation = relationships.get("location", {})
    attributes = relation.get("attributes") or {}
    relation_data = relation.get("data") or {}
    if not attributes:
        relation_id = relation_data.get("id") or row.get("attributes", {}).get("location_id")
        attributes = location_map.get(str(relation_id), {})
    return attributes.get("long") or attributes.get("name") or attributes.get("short")


def _merge_api_nodes(api_rows: list[dict], location_map: dict[str, dict], local_nodes: list[dict]) -> list[dict]:
    merged: list[dict] = []
    matched_local_keys: set[str] = set()
    for row in api_rows:
        attrs = row.get("attributes", {})
        panel_name = str(attrs.get("name") or "Unnamed node")
        local = _find_node(panel_name, local_nodes)
        if local:
            matched_local_keys.add(local["key"])
            node = dict(local)
            node["aliases"] = list(local.get("aliases", []))
            # The manually configured host is the public Minecraft/query endpoint.
            # Pterodactyl's fqdn points at its daemon and may use different ports.
            node["host"] = attrs.get("fqdn") if local.get("host_override") else (local.get("host") or attrs.get("fqdn"))
        else:
            node = {
                "key": _key_for(panel_name), "name": panel_name, "host": attrs.get("fqdn"),
                "processor": "Not specified", "location": "Not specified", "aliases": [],
            }

        relationships = row.get("relationships", {})
        server_relation = relationships.get("servers") or {}
        server_data = server_relation.get("data") or []
        server_pagination = (server_relation.get("meta") or {}).get("pagination") or {}
        allocation_relation = relationships.get("allocations") or {}
        allocation_data = allocation_relation.get("data") or []
        allocation_pagination = (allocation_relation.get("meta") or {}).get("pagination") or {}
        free_allocations = sum(
            1 for item in allocation_data
            if (item.get("attributes") or {}).get("assigned") is False
        )
        node.update(
            api_name=panel_name,
            maintenance=bool(attrs.get("maintenance_mode", False)),
            server_count=server_pagination.get("total", len(server_data)),
            server_count_known=("servers" in relationships),
            allocation_count=allocation_pagination.get("total", len(allocation_data)),
            free_allocations=free_allocations,
            allocation_count_known=("allocations" in relationships),
        )
        api_location = _api_location(row, location_map)
        if api_location and node.get("location") in (None, "", "Not specified"):
            node["location"] = str(api_location)
        merged.append(node)

    # Keep manually-added bot-only entries visible as well as panel-owned nodes.
    api_keys = {_slug(node.get("api_name", "")) for node in merged}
    for node in local_nodes:
        if node.get("key") not in matched_local_keys and _slug(node.get("name", "")) not in api_keys:
            copy = dict(node)
            copy["maintenance"] = False
            merged.append(copy)
    return merged


def _read_overrides() -> dict[str, str]:
    try:
        data = json.loads(OVERRIDES_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items() if v in {"up", "down", "auto"}}
    except FileNotFoundError:
        pass
    except (OSError, json.JSONDecodeError):
        log.exception("Could not read node status overrides")
    return {}


def _write_overrides(overrides: dict[str, str]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    temp_file = OVERRIDES_FILE.with_suffix(".tmp")
    temp_file.write_text(json.dumps(overrides, indent=2) + "\n", encoding="utf-8")
    os.replace(temp_file, OVERRIDES_FILE)


def _find_node(value: str, nodes: list[dict]) -> dict | None:
    wanted = _slug(value)
    for node in nodes:
        candidates = [node.get("key", ""), node.get("name", ""), *node.get("aliases", [])]
        if wanted in {_slug(candidate) for candidate in candidates}:
            return node
    return None


def _normalize_host(value: str) -> str | None:
    value = value.strip().strip("`<>")
    if not value or any(character.isspace() for character in value):
        return None
    try:
        parsed = urlsplit(value if "://" in value else f"//{value}")
        host = parsed.hostname
    except ValueError:
        return None
    if not host:
        return None
    host = host.rstrip(".").casefold()
    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        if len(host) > 253 or not re.fullmatch(r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", host):
            return None
        return host


async def _ping(host: str) -> tuple[str, str]:
    """Use ICMP only; do not connect to the Minecraft or Wings service ports."""
    ping_exe = shutil.which("ping")
    if not ping_exe:
        return "Unavailable", "ping utility unavailable"
    args = ([ping_exe, "-n", "3", "-w", "1000", host] if sys.platform == "win32"
            else [ping_exe, "-n", "-c", "3", "-W", "1", host])
    process = None
    try:
        process = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
        )
        output_bytes, _ = await asyncio.wait_for(process.communicate(), timeout=5.5)
    except asyncio.TimeoutError:
        if process and process.returncode is None:
            process.kill()
            await process.wait()
        return "Partial", "ping timed out"
    except OSError:
        log.exception("Could not start ICMP node probe")
        return "Unavailable", "ping could not run"

    output = output_bytes.decode(errors="replace")
    linux = re.search(r"(\d+)\s+packets transmitted,\s*(\d+)\s+(?:packets )?received", output, re.I)
    windows = re.search(r"Packets:\s*Sent\s*=\s*(\d+),\s*Received\s*=\s*(\d+)", output, re.I)
    match = linux or windows
    if match:
        sent, received = int(match.group(1)), int(match.group(2))
    else:
        received = len(re.findall(r"time[=<]\s*[\d.]+\s*ms", output, re.I))
        sent = 3 if received else 0
    if not sent:
        return "Unavailable", "no ping result"
    latency_match = re.search(r"time[=<]\s*([\d.]+)\s*ms", output, re.I)
    latency = f" · {float(latency_match.group(1)):g} ms" if latency_match else ""
    detail = f"{received}/{sent} replies{latency}"
    if received == sent:
        return "Up", detail
    if received:
        return "Partial", detail
    return "Down", detail


async def _node_statuses() -> tuple[list[dict], list[tuple[str, str]], bool]:
    nodes, api_available = await _current_nodes()
    overrides = await asyncio.to_thread(_read_overrides)

    async def check_node(node: dict) -> tuple[str, str]:
        override = overrides.get(node["key"])
        if override == "up":
            return "Manual Up", "staff override"
        if override == "down":
            return "Manual Down", "staff override"
        host = _normalize_host(str(node.get("host", "")))
        if not host:
            return "Unavailable", "no host configured"
        return await _ping(host)

    statuses = await asyncio.gather(*(check_node(node) for node in nodes))
    return nodes, statuses, api_available


async def _current_nodes() -> tuple[list[dict], bool]:
    local_nodes, hidden = await asyncio.gather(
        asyncio.to_thread(_read_nodes), asyncio.to_thread(_read_hidden_nodes),
    )
    snapshot = await _fetch_application_snapshot()
    if snapshot is None:
        nodes = local_nodes
        for node in nodes:
            node.setdefault("maintenance", node.get("key") in DEFAULT_MAINTENANCE)
        api_available = False
    else:
        api_rows, locations = snapshot
        nodes = _merge_api_nodes(api_rows, locations, local_nodes)
        api_available = True
    nodes = [node for node in nodes if node.get("key") not in hidden]
    return nodes, api_available


def _display_status(status: str) -> str:
    return {
        "Manual Up": "MANUAL UP", "Manual Down": "MANUAL DOWN",
    }.get(status, status.upper())


def _safe_text(value: str) -> str:
    return discord.utils.escape_mentions(discord.utils.escape_markdown(value))


def _loading_emoji(guild: discord.Guild | None, frame: int = 0) -> str:
    if guild:
        candidates = [e for e in guild.emojis if e.animated and e.name.casefold() in {
            "loading", "node_loading", "spinner", "sync", "nextermc_loading",
        }]
        if candidates:
            return str(candidates[frame % len(candidates)])
    return ("⏳", "⌛", "🔄")[frame % 3]


def _loading_embed(guild: discord.Guild | None, frame: int = 0) -> discord.Embed:
    steps = (
        "Checking node reachability…",
        "Refreshing server and capacity details…",
        "Preparing the node overview…",
    )
    embed = discord.Embed(
        title=f"{_loading_emoji(guild, frame)}  NEXTERCLOUD · NODE MONITOR",
        description=(
            f"**{steps[frame % len(steps)]}**\n\n"
            "`ICMP reachability`　→　`Server count`　→　`Capacity`"
        ),
        color=discord.Color.from_rgb(45, 190, 165),
    )
    embed.set_footer(text="Secure read-only status refresh")
    return embed


async def _animate_loading_message(message: discord.Message, guild: discord.Guild | None) -> None:
    frame = 1
    while True:
        await asyncio.sleep(1.8)
        try:
            await message.edit(embed=_loading_embed(guild, frame))
        except discord.HTTPException:
            return
        frame += 1


async def _load_nodes_report(message: discord.Message, guild: discord.Guild | None) -> discord.Embed:
    """Fetch node data while showing progress, then stop progress edits before returning."""
    started = time.monotonic()
    animation = asyncio.create_task(_animate_loading_message(message, guild))
    try:
        nodes, statuses, api_available = await asyncio.wait_for(_node_statuses(), timeout=25)
        await asyncio.sleep(max(0, 2.3 - (time.monotonic() - started)))
        log.info("Node monitor refresh completed in %.2fs (nodes=%d, panel_api=%s)",
                 time.monotonic() - started, len(nodes), api_available)
        return _nodes_embed(nodes, statuses, guild, api_available)
    finally:
        # Join the animation before the caller publishes the final result. Otherwise an
        # in-flight progress edit can finish later and replace the completed report.
        animation.cancel()
        await asyncio.gather(animation, return_exceptions=True)


def _node_group(node: dict) -> str:
    text = f"{node.get('key', '')} {node.get('name', '')}".casefold()
    if "free" in text or "it-1" in text or "it-2" in text:
        return "🆓  FREE NODES"
    if "cheap" in text or "cf-cheap" in text:
        return "⚙️  CHEAP NODES"
    if "power" in text:
        return "⚡  POWER NODE"
    if "ultimate" in text or "titan" in text or "sgultimate" in text:
        return "💎  ULTIMATE & TITAN"
    return "🖥️  OTHER NODES"


def _status_icon(status: str) -> str:
    return {
        "Up": "🟢", "Manual Up": "🟢", "Partial": "🟡", "Down": "🔴",
        "Manual Down": "🔴", "Unavailable": "⚪",
    }.get(status, "⚪")


def _nodes_embed(nodes: list[dict], statuses: list[tuple[str, str]], guild: discord.Guild | None,
                 api_available: bool) -> discord.Embed:
    counts = {"Up": 0, "Partial": 0, "Down": 0, "Unavailable": 0, "Maintenance": 0, "Manual": 0}
    full_count = 0
    capacity_known = 0
    lines: list[str] = []
    for node, (status, detail) in zip(nodes, statuses):
        maintenance = bool(node.get("maintenance"))
        if status in ("Manual Up", "Manual Down"):
            counts["Manual"] += 1
        elif status in ("Up", "Partial", "Down", "Unavailable"):
            counts[status] += 1
        counts["Maintenance"] += int(maintenance)
        allocation_known = bool(node.get("allocation_count_known"))
        capacity_known += int(allocation_known)
        full = (
            allocation_known
            and int(node.get("allocation_count") or 0) > 0
            and int(node.get("free_allocations") or 0) == 0
        )
        full_count += int(full)
        processor = _safe_text(str(node.get("processor", "Not specified")))
        location = _safe_text(str(node.get("location", "Not specified")))
        name = _safe_text(str(node.get("name", "Unnamed node")))
        ping_label = _display_status(status).title()
        if status in ("Manual Up", "Manual Down"):
            ping_label += " · Manual"
        heading = f"{_status_icon(status)} **{name}** · `{ping_label}`"
        tags = []
        if maintenance:
            tags.append("🛠️ Maintenance")
        if full:
            tags.append("⚠️ No free allocations")
        if tags:
            heading += " · " + " · ".join(tags)
        details = f"🧠 `{processor}`　·　📍 `{location}`"
        if detail and status not in ("Manual Up", "Manual Down"):
            details += f"\n　└ {_safe_text(detail)}"
        capacity = []
        if node.get("server_count_known"):
            capacity.append(f"🖥️ {node.get('server_count', 0)} servers")
        if allocation_known:
            capacity.append(f"🧩 {node.get('free_allocations', 0)} allocations available")
        if capacity:
            details += "\n　└ " + "　·　".join(capacity)
        lines.append(f"{heading}\n{details}")

    checked_at = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
    if api_available:
        source = "Panel API connected"
    else:
        source = "Panel API unavailable · " + (_APP_LAST_ERROR or "local metadata")
    ping_summary = (
        f"🟢 {counts['Up']}　🟡 {counts['Partial']}　🔴 {counts['Down']}"
        f"　⚪ {counts['Unavailable']} N/A　🛠️ {counts['Maintenance']} maintenance"
    )
    full_summary = f"⚠️ {full_count} full" if capacity_known else "🧩 Allocation data unavailable"
    body = "\n\n──────────────\n\n".join(lines) if lines else "No nodes are configured for monitoring."
    embed = discord.Embed(
        title="🗄️ Node Status",
        description=(
            f"📶 **{counts['Up'] + counts['Partial']}/{len(nodes)} nodes responding**　·　{full_summary}\n"
            f"{ping_summary}\n✅ Updated <t:{checked_at}:R>\n\n{body}"
        ),
        color=(discord.Color.red() if counts["Down"] else discord.Color.gold() if counts["Partial"] or full_count
               else discord.Color.orange() if counts["Maintenance"] else discord.Color.from_rgb(45, 190, 165)),
        timestamp=datetime.datetime.fromtimestamp(checked_at, datetime.timezone.utc),
    )
    capacity_note = "Full = zero unassigned allocations" if capacity_known else "Add panel API read access for capacity"
    embed.set_footer(text=f"{source}　·　ICMP (no reply may be filtered)　·　{capacity_note}　·　Host addresses hidden")
    return embed


class NodeMonitorView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=900)

    @discord.ui.button(label="Refresh status", style=discord.ButtonStyle.primary, emoji="🔄")
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_owner(interaction.user.id) and not getattr(
            getattr(interaction.user, "guild_permissions", None), "administrator", False
        ):
            await interaction.response.send_message("Administrator permission is required to refresh node status.", ephemeral=True)
            return
        button.label, button.disabled = "Loading…", True
        await interaction.response.edit_message(embed=_loading_embed(interaction.guild), view=self)
        try:
            report = await _load_nodes_report(interaction.message, interaction.guild)
        except Exception:
            log.exception("Node status refresh failed")
            button.label, button.disabled = "Refresh status", False
            await interaction.message.edit(content="❌ Node refresh failed or timed out. Check the bot logs.", embed=None, view=self)
            return
        button.label, button.disabled = "Refresh status", False
        await interaction.message.edit(embed=report, view=self)


class RemoveNodeView(discord.ui.View):
    def __init__(self, requester_id: int, node_key: str):
        super().__init__(timeout=60)
        self.requester_id = requester_id
        self.node_key = node_key

    @discord.ui.button(label="Remove node", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def confirm(self, interaction: discord.Interaction, _button: discord.ui.Button):
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message("Only the administrator who started this can confirm.", ephemeral=True)
            return
        hidden = await asyncio.to_thread(_read_hidden_nodes)
        if self.node_key in hidden:
            await interaction.response.edit_message(content="That node is already removed.", embed=None, view=None)
            return
        hidden.add(self.node_key)
        await asyncio.to_thread(_write_hidden_nodes, hidden)
        overrides = await asyncio.to_thread(_read_overrides)
        overrides.pop(self.node_key, None)
        await asyncio.to_thread(_write_overrides, overrides)
        await interaction.response.edit_message(content="✅ Node removed from the bot’s monitor. The hosting server itself was not changed.", embed=None, view=None)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, _button: discord.ui.Button):
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message("This confirmation belongs to another administrator.", ephemeral=True)
            return
        await interaction.response.edit_message(content="Removal cancelled.", embed=None, view=None)


def _parse_node_spec(raw: str) -> tuple[str, str, str, str] | None:
    parts = [part.strip().strip("`") for part in raw.split("|")]
    if len(parts) != 4 or any(not part for part in parts[:3]):
        return None
    name, processor, location, host_raw = parts
    host = _normalize_host(host_raw)
    if not host or len(name) > 60 or len(processor) > 100 or len(location) > 80:
        return None
    return name, processor, location, host


class NodesCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(name="nodes")
    @commands.guild_only()
    @has_permissions_or_owner(administrator=True)
    async def nodes(self, ctx: commands.Context):
        message = await ctx.reply(embed=_loading_embed(ctx.guild), mention_author=False)
        try:
            report = await _load_nodes_report(message, ctx.guild)
            await message.edit(embed=report, view=NodeMonitorView())
        except Exception:
            log.exception("Node status display failed")
            await message.edit(content="❌ Could not load the node overview. Check the bot logs.", embed=None)

    async def _set(self, ctx: commands.Context, node_name: str, value: str):
        nodes, _api_available = await _current_nodes()
        node = _find_node(node_name, nodes)
        if node is None:
            await ctx.send("Unknown node. Use `,nodes` to see the current list.", delete_after=12)
            return
        overrides = await asyncio.to_thread(_read_overrides)
        overrides[node["key"]] = value
        await asyncio.to_thread(_write_overrides, overrides)
        label = {"up": "🟢 manually marked **Online**", "down": "🔴 manually marked **Offline**", "auto": "🔄 restored to automatic status"}[value]
        await ctx.send(f"{_safe_text(node['name'])} {label}. Run `,nodes` to refresh.")

    @commands.hybrid_command(name="revo")
    @commands.guild_only()
    @has_permissions_or_owner(administrator=True)
    async def node_up(self, ctx: commands.Context, *, node: str):
        await self._set(ctx, node, "up")

    @commands.hybrid_command(name="revd")
    @commands.guild_only()
    @has_permissions_or_owner(administrator=True)
    async def node_down(self, ctx: commands.Context, *, node: str):
        await self._set(ctx, node, "down")

    @commands.hybrid_command(name="revm")
    @commands.guild_only()
    @has_permissions_or_owner(administrator=True)
    async def node_auto(self, ctx: commands.Context, *, node: str):
        await self._set(ctx, node, "auto")

    @commands.hybrid_command(name="revadd")
    @commands.guild_only()
    @has_permissions_or_owner(administrator=True)
    async def node_add(self, ctx: commands.Context, *, specification: str):
        parsed = _parse_node_spec(specification)
        if not parsed:
            await ctx.send("Use: `,revadd Name | Processor | Location | host-or-IP`", delete_after=15)
            return
        name, processor, location, host = parsed
        current_nodes, _api_available = await _current_nodes()
        key = _key_for(name)
        hidden = await asyncio.to_thread(_read_hidden_nodes)
        existing = _find_node(name, current_nodes)
        local_nodes = await asyncio.to_thread(_read_nodes)
        local_match = _find_node(name, local_nodes)
        restore_key = existing["key"] if existing else local_match["key"] if local_match else key
        if restore_key in hidden:
            hidden.discard(restore_key)
            await asyncio.to_thread(_write_hidden_nodes, hidden)
            await ctx.send(f"✅ Restored **{_safe_text(existing['name'] if existing else name)}** to the node monitor.")
            return
        if existing or any(_slug(item["key"]) == _slug(key) or _slug(item["name"]) == _slug(name) for item in current_nodes):
            await ctx.send("A node with that name already exists. Use `,revedit` to change it.", delete_after=12)
            return
        nodes = local_nodes
        nodes.append({"key": key, "name": name, "host": host, "processor": processor, "location": location, "aliases": []})
        await asyncio.to_thread(_write_nodes, nodes)
        await ctx.send(f"✅ Added **{_safe_text(name)}** to the node monitor. Host details are hidden. Run `,nodes` to check it.")

    @commands.hybrid_command(name="revedit")
    @commands.guild_only()
    @has_permissions_or_owner(administrator=True)
    async def node_edit(self, ctx: commands.Context, *, specification: str):
        parsed = _parse_node_spec(specification)
        if not parsed:
            await ctx.send("Use: `,revedit Existing Name | Processor | Location | host-or-IP`", delete_after=15)
            return
        name, processor, location, host = parsed
        nodes, _api_available = await _current_nodes()
        node = _find_node(name, nodes)
        if not node:
            await ctx.send("Node not found. Use the exact current node name before the first `|`.", delete_after=12)
            return
        local_nodes = await asyncio.to_thread(_read_nodes)
        local_node = _find_node(name, local_nodes)
        if local_node is None:
            local_node = {
                "key": node["key"], "name": node["name"], "aliases": list(node.get("aliases", [])),
                "host": node.get("host", ""),
            }
            local_nodes.append(local_node)
        local_node.update(processor=processor, location=location, host=host, host_override=True)
        await asyncio.to_thread(_write_nodes, local_nodes)
        await ctx.send(f"✅ Updated **{_safe_text(node['name'])}**. Host details are hidden. Run `,nodes` to check it.")

    @commands.hybrid_command(name="revremove")
    @commands.guild_only()
    @has_permissions_or_owner(administrator=True)
    async def node_remove(self, ctx: commands.Context, *, node_name: str):
        nodes, _api_available = await _current_nodes()
        node = _find_node(node_name, nodes)
        if node is None:
            await ctx.send("Unknown node. Use `,nodes` to see the current list.", delete_after=12)
            return
        embed = discord.Embed(
            title="Remove node from monitor?",
            description=f"Remove **{_safe_text(node['name'])}** from the bot’s node list? This does not affect the hosting server.",
            color=discord.Color.orange(),
        )
        await ctx.send(embed=embed, view=RemoveNodeView(ctx.author.id, node["key"]))


async def setup(bot: commands.Bot):
    await bot.add_cog(NodesCog(bot))
