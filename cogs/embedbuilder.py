"""Interactive Discord embed editor for staff announcements."""
from __future__ import annotations

import datetime
from urllib.parse import urlparse

import discord
from discord.ext import commands

from config import BRAND_NAME
from permissions import has_permissions_or_owner, member_has_permission


DEFAULT_COLOR = "29BEB0"


def _validated_url(value: str) -> str | None:
    value = value.strip()
    if not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Image links must start with http:// or https://.")
    return value


def _build_embed(state: dict) -> discord.Embed:
    title = state["title"].strip()
    description = state["description"].strip()
    color_text = state["color"].strip().removeprefix("#")
    if not color_text:
        color_text = DEFAULT_COLOR
    if len(color_text) != 6 or any(char not in "0123456789abcdefABCDEF" for char in color_text):
        raise ValueError("Color must be a six-digit hex value, such as `29BEB0`.")

    fields = []
    for line_number, line in enumerate(state["fields"].splitlines(), start=1):
        if not line.strip():
            continue
        if "|" not in line:
            raise ValueError(f"Field line {line_number} needs the format `Name | Value`.")
        name, value = (part.strip() for part in line.split("|", 1))
        if not name or not value:
            raise ValueError(f"Field line {line_number} needs both a name and a value.")
        if len(name) > 256 or len(value) > 1024:
            raise ValueError(f"Field line {line_number} is over Discord's name/value limit.")
        fields.append((name, value))
    if len(fields) > 25:
        raise ValueError("An embed can contain at most 25 fields.")
    if not title and not description and not fields:
        raise ValueError("Add a title, description, or at least one field first.")

    embed = discord.Embed(
        title=title or None,
        description=description or None,
        color=discord.Color(int(color_text, 16)),
        timestamp=datetime.datetime.now(datetime.timezone.utc),
    )
    for name, value in fields:
        embed.add_field(name=name, value=value, inline=False)
    if state["author"].strip():
        embed.set_author(name=state["author"].strip()[:256])
    if state["footer"].strip():
        embed.set_footer(text=state["footer"].strip()[:2048])
    image_url = _validated_url(state["image"])
    thumbnail_url = _validated_url(state["thumbnail"])
    if image_url:
        embed.set_image(url=image_url)
    if thumbnail_url:
        embed.set_thumbnail(url=thumbnail_url)
    if len(embed) > 6000:
        raise ValueError("This embed is over Discord's 6,000-character total limit.")
    return embed


async def _is_editor(interaction: discord.Interaction, owner_id: int) -> bool:
    if interaction.user.id == owner_id and member_has_permission(interaction.user, "administrator"):
        return True
    detail = "This embed editor belongs to another staff member." if interaction.user.id != owner_id else "Administrator permission required."
    await interaction.response.send_message(f"❌ {detail}", ephemeral=True)
    return False


class TextStyleModal(discord.ui.Modal):
    def __init__(self, editor: "EmbedEditorView"):
        super().__init__(title="Edit embed text and style")
        self.editor = editor
        self.title_input = discord.ui.TextInput(
            label="Title", default=editor.state["title"][:256], max_length=256, required=False
        )
        self.description_input = discord.ui.TextInput(
            label="Description", default=editor.state["description"][:4000],
            style=discord.TextStyle.paragraph, max_length=4000, required=False,
        )
        self.color_input = discord.ui.TextInput(
            label="Color (hex, no # needed)", default=editor.state["color"][:6], max_length=7, required=False
        )
        self.author_input = discord.ui.TextInput(
            label="Author label", default=editor.state["author"][:256], max_length=256, required=False
        )
        self.footer_input = discord.ui.TextInput(
            label="Footer", default=editor.state["footer"][:2048], max_length=2048, required=False
        )
        for item in (self.title_input, self.description_input, self.color_input, self.author_input, self.footer_input):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction):
        if not await _is_editor(interaction, self.editor.owner_id):
            return
        self.editor.state.update({
            "title": str(self.title_input.value),
            "description": str(self.description_input.value),
            "color": str(self.color_input.value),
            "author": str(self.author_input.value),
            "footer": str(self.footer_input.value),
        })
        await self.editor.refresh_from_modal(interaction)


class MediaFieldsModal(discord.ui.Modal):
    def __init__(self, editor: "EmbedEditorView"):
        super().__init__(title="Edit images and fields")
        self.editor = editor
        self.image_input = discord.ui.TextInput(
            label="Large image URL", default=editor.state["image"][:400], max_length=400, required=False
        )
        self.thumbnail_input = discord.ui.TextInput(
            label="Thumbnail URL", default=editor.state["thumbnail"][:400], max_length=400, required=False
        )
        self.fields_input = discord.ui.TextInput(
            label="Fields: one `Name | Value` per line",
            placeholder="Server | play.example.net\nStatus | Online",
            default=editor.state["fields"][:4000], style=discord.TextStyle.paragraph,
            max_length=4000, required=False,
        )
        for item in (self.image_input, self.thumbnail_input, self.fields_input):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction):
        if not await _is_editor(interaction, self.editor.owner_id):
            return
        self.editor.state.update({
            "image": str(self.image_input.value),
            "thumbnail": str(self.thumbnail_input.value),
            "fields": str(self.fields_input.value),
        })
        await self.editor.refresh_from_modal(interaction)


class EmbedEditorView(discord.ui.View):
    def __init__(self, owner_id: int):
        super().__init__(timeout=600)
        self.owner_id = owner_id
        self.message: discord.Message | None = None
        self.state = {
            "title": "",
            "description": "Write your announcement here…",
            "color": DEFAULT_COLOR,
            "author": BRAND_NAME,
            "footer": "",
            "image": "",
            "thumbnail": "",
            "fields": "",
        }

    async def refresh_from_modal(self, interaction: discord.Interaction):
        try:
            embed = _build_embed(self.state)
        except (ValueError, discord.HTTPException) as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            return
        if self.message is not None:
            await self.message.edit(embed=embed, view=self)
        await interaction.response.send_message("✅ Preview updated.", ephemeral=True)

    @discord.ui.button(label="Edit text & style", style=discord.ButtonStyle.primary, emoji="✏️", row=0)
    async def edit_text(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await _is_editor(interaction, self.owner_id):
            await interaction.response.send_modal(TextStyleModal(self))

    @discord.ui.button(label="Images & fields", style=discord.ButtonStyle.secondary, emoji="🖼️", row=0)
    async def edit_media(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await _is_editor(interaction, self.owner_id):
            await interaction.response.send_modal(MediaFieldsModal(self))

    @discord.ui.button(label="Preview", style=discord.ButtonStyle.secondary, emoji="👁️", row=0)
    async def preview(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await _is_editor(interaction, self.owner_id):
            return
        try:
            embed = _build_embed(self.state)
        except (ValueError, discord.HTTPException) as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            return
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Publish here", style=discord.ButtonStyle.success, emoji="📨", row=0)
    async def publish(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await _is_editor(interaction, self.owner_id):
            return
        try:
            embed = _build_embed(self.state)
        except (ValueError, discord.HTTPException) as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            await interaction.channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
            await interaction.followup.send("✅ Embed published in this channel.", ephemeral=True)
            for child in self.children:
                child.disabled = True
            if self.message is not None:
                await self.message.edit(view=self)
            self.stop()
        except (discord.Forbidden, discord.HTTPException):
            await interaction.followup.send("❌ I couldn't publish here. Check my channel permissions and the embed content.", ephemeral=True)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger, emoji="✖️", row=0)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await _is_editor(interaction, self.owner_id):
            return
        await interaction.response.edit_message(content="Embed draft cancelled.", embed=None, view=None)
        self.stop()


class EmbedBuilder(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(name="embed", aliases=["embedmaker", "embedcreate"])
    @commands.guild_only()
    @has_permissions_or_owner(administrator=True)
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def embed_builder(self, ctx: commands.Context):
        view = EmbedEditorView(ctx.author.id)
        embed = _build_embed(view.state)
        embed.title = "🧩 Embed Creator · Preview"
        embed.description = "Use the controls below to edit the draft. It will only publish when you press Publish."
        embed.set_footer(text="Draft preview · Only you can use these controls")
        message = await ctx.send(embed=embed, view=view, delete_after=600)
        view.message = message


async def setup(bot: commands.Bot):
    await bot.add_cog(EmbedBuilder(bot))
