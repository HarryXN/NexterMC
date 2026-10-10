"""Owner-only controls for the NexterMC systemd service."""
from __future__ import annotations

import asyncio
import datetime
import json
import logging
import socket

import discord
from discord.ext import commands

log = logging.getLogger("nextermc.owner_panel")
OWNER_ID = 1006250810142883851
SOCKET_PATH = "/run/nextermc-control.sock"


def _controller_request(action: str, interaction: discord.Interaction | None = None) -> dict:
    """Talk to the fixed-action local controller; never send shell commands."""
    if action not in {"status", "start", "stop", "restart"}:
        raise ValueError("Unsupported service action")
    request = {"action": action}
    if interaction is not None and action in {"stop", "restart"}:
        request["application_id"] = str(interaction.application_id)
        request["interaction_token"] = interaction.token
    payload = (json.dumps(request) + "\n").encode("utf-8")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(8)
        connection.connect(SOCKET_PATH)
        connection.sendall(payload)
        chunks = []
        while True:
            chunk = connection.recv(2048)
            if not chunk:
                break
            chunks.append(chunk)
            if sum(map(len, chunks)) > 8192:
                raise RuntimeError("Controller response was too large")
    response = json.loads(b"".join(chunks).decode("utf-8"))
    if not isinstance(response, dict):
        raise RuntimeError("Invalid controller response")
    return response


def _status_embed(snapshot: dict | None = None, error: str | None = None) -> discord.Embed:
    now = datetime.datetime.now(datetime.timezone.utc)
    if error:
        return discord.Embed(
            title="🤖 NexterMC · Bot Control",
            description=(
                "⚠️ **Controller unavailable**\n"
                "The local service controller is not responding. Install or start "
                "`nextermc-control.service` on the VPS."
            ),
            color=discord.Color.orange(),
            timestamp=now,
        ).set_footer(text="Private owner controls · No shell access")

    state = (snapshot or {}).get("state", "unknown").lower()
    substate = (snapshot or {}).get("substate", "")
    labels = {
        "active": ("🟢", "Running", discord.Color.green()),
        "inactive": ("🔴", "Stopped", discord.Color.red()),
        "activating": ("🟡", "Starting", discord.Color.orange()),
        "deactivating": ("🟡", "Stopping", discord.Color.orange()),
        "failed": ("🔴", "Failed", discord.Color.red()),
    }
    icon, label, color = labels.get(state, ("⚪", "Unknown", discord.Color.blurple()))
    embed = discord.Embed(
        title="🤖 NexterMC · Bot Control",
        description=(
            "Manage the bot service on the VPS. **Stop** and **Restart** ask for confirmation.\n\n"
            f"{icon} **Service:** {label}"
            + (f" · `{discord.utils.escape_markdown(substate)}`" if substate else "")
        ),
        color=color,
        timestamp=now,
    )
    embed.set_footer(text="Private owner controls · Fixed service actions only")
    return embed


class ConfirmActionView(discord.ui.View):
    def __init__(self, owner_id: int, action: str):
        super().__init__(timeout=45)
        self.owner_id = owner_id
        self.action = action

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id or interaction.user.id != OWNER_ID:
            await interaction.response.send_message("🔒 This control belongs to the bot owner.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger, emoji="⚠️")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content=f"⏳ **{self.action.title()} requested.** Sending the fixed service action to the VPS…",
            embed=None,
            view=None,
        )
        try:
            # The controller sends the final result through this interaction's
            # webhook after systemd completes; the bot itself may be stopping.
            await asyncio.to_thread(_controller_request, self.action, interaction)
        except Exception:
            log.exception("Owner service action failed: %s", self.action)
            try:
                await interaction.followup.send(
                    "❌ The VPS controller could not complete the request. Check its systemd logs.",
                    ephemeral=True,
                )
            except discord.HTTPException:
                pass

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Action cancelled.", embed=None, view=None)


class BotControlView(discord.ui.View):
    def __init__(self, owner_id: int):
        super().__init__(timeout=300)
        self.owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id or interaction.user.id != OWNER_ID:
            await interaction.response.send_message("🔒 This control panel is restricted to the bot owner.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Refresh", style=discord.ButtonStyle.primary, emoji="🔄", row=0)
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        try:
            result = await asyncio.to_thread(_controller_request, "status")
            await interaction.edit_original_response(embed=_status_embed(result), view=self)
            await interaction.followup.send("✅ Refresh successful.", ephemeral=True)
        except Exception:
            log.exception("Could not refresh bot service status")
            await interaction.edit_original_response(embed=_status_embed(error="unavailable"), view=self)

    @discord.ui.button(label="Start", style=discord.ButtonStyle.success, emoji="▶️", row=0)
    async def start(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Acknowledge the component immediately. Discord expires unacknowledged
        # interactions after a few seconds, while systemd may take longer.
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            result = await asyncio.to_thread(_controller_request, "start")
            message = result.get("message", "Start request accepted.")
            await interaction.followup.send(
                content=("✅ Start successful. " if result.get("ok") else "❌ Start failed. ") + message,
                ephemeral=True,
            )
        except Exception:
            log.exception("Could not start bot service")
            await interaction.followup.send(
                "❌ VPS controller unavailable. Check its systemd service and logs.",
                ephemeral=True,
            )

    @discord.ui.button(label="Restart", style=discord.ButtonStyle.primary, emoji="🔁", row=0)
    async def restart(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "Restart the NexterMC bot service? The bot will briefly go offline.",
            view=ConfirmActionView(self.owner_id, "restart"),
            ephemeral=True,
        )

    @discord.ui.button(label="Stop", style=discord.ButtonStyle.danger, emoji="⏹️", row=0)
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "Stop the NexterMC bot service? It will stay offline until started from this controller or the VPS.",
            view=ConfirmActionView(self.owner_id, "stop"),
            ephemeral=True,
        )


class NexterMCControlCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(name="nextermc")
    @commands.check(lambda ctx: ctx.author.id == OWNER_ID)
    async def nextermc(self, ctx: commands.Context):
        """Open the private owner-only bot service controls."""
        if ctx.guild is not None and ctx.message is not None and ctx.interaction is None:
            try:
                await ctx.message.delete()
            except discord.HTTPException:
                pass
        try:
            result = await asyncio.to_thread(_controller_request, "status")
            embed = _status_embed(result)
        except Exception:
            log.exception("VPS service controller is unavailable")
            embed = _status_embed(error="unavailable")
        try:
            await ctx.author.send(embed=embed, view=BotControlView(OWNER_ID))
            if ctx.guild is not None:
                await ctx.send("📬 Check your DMs for the NexterMC bot control panel.", delete_after=12)
        except discord.Forbidden:
            if ctx.guild is not None:
                await ctx.send("🔒 Enable DMs from this server, then run `,nextermc` again.", delete_after=10)
            else:
                await ctx.send("I couldn't send the private control panel. Enable DMs and try again.")


async def setup(bot: commands.Bot):
    await bot.add_cog(NexterMCControlCog(bot))
