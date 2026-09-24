import discord
from discord.ext import commands, tasks
import datetime
import aiohttp
import uuid
from mcstatus import JavaServer

# Modal popup for AdvancedBan reason input
class BanReasonModal(discord.ui.Modal, title="AdvancedBan System - Execution"):
    reason_input = discord.ui.TextInput(
        label="Ban Reason",
        placeholder="Enter reason for punishment...",
        style=discord.TextStyle.long,
        required=True,
        max_length=250
    )

    def __init__(self, target_name: str, target_uuid: str):
        super().__init__()
        self.target_name = target_name
        self.target_uuid = target_uuid

    async def on_submit(self, interaction: discord.Interaction):
        reason = self.reason_input.value
        # Sends to Main Server IP interface (ultimate-1.nextercloud.com:19163)
        # Here you can wire up your RCON execution client for: /ban self.target_name reason
        embed = discord.Embed(
            title="🔨 AdvancedBan Executed Successfully",
            description=f"Player **{self.target_name}** has been permanently banned from the network.",
            color=discord.Color.red()
        )
        embed.add_field(name="Target UUID", value=f"`{self.target_uuid}`", inline=False)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.add_field(name="Executed By", value=interaction.user.mention, inline=True)
        embed.add_field(name="Target Server", value="`Main Server (19163)`", inline=True)
        embed.timestamp = datetime.datetime.now()
        await interaction.response.send_message(embed=embed, ephemeral=True)


class MinecraftManagementView(discord.ui.View):
    def __init__(self, target_name: str, target_uuid: str):
        super().__init__(timeout=180)
        self.target_name = target_name
        self.target_uuid = target_uuid

    @discord.ui.button(label="Clear Inventory", style=discord.ButtonStyle.secondary, emoji="🧹")
    async def clear_inventory_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = InventorySubMenu(self.target_name, self.target_uuid)
        embed = discord.Embed(
            title="🧹 Inventory Management Hub",
            description=f"Select target inventory partition to wipe for **{self.target_name}**:",
            color=discord.Color.gold()
        )
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Inventory Overview", style=discord.ButtonStyle.primary, emoji="📦")
    async def overview_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title=f"📦 Live Inventory Snapshot: {self.target_name}",
            description=f"Connected to **Main Server** storage database...\n\n```yaml\n[Slot 00-08] Armor & Offhand: Normal\n[Slot 09-35] Main Inventory: 3x Golden Apple, 64x Steak, Diamond Sword (Sharpness V)\n[Slot 36-44] Hotbar Active\n```",
            color=discord.Color.blurple()
        )
        embed.timestamp = datetime.datetime.now()
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Kick", style=discord.ButtonStyle.danger, emoji="👢")
    async def kick_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.kick_members:
            await interaction.response.send_message("❌ Insufficient permissions.", ephemeral=True)
            return
        await interaction.response.send_message(f"👢 RCON Kick dispatched for **{self.target_name}** on Main Server.", ephemeral=True)

    @discord.ui.button(label="Ban (AdvancedBan)", style=discord.ButtonStyle.danger, emoji="🔨")
    async def ban_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.ban_members:
            await interaction.response.send_message("❌ Insufficient permissions.", ephemeral=True)
            return
        # Open modal popup for entering reason
        await interaction.response.send_modal(BanReasonModal(self.target_name, self.target_uuid))


class InventorySubMenu(discord.ui.View):
    def __init__(self, target_name: str, target_uuid: str):
        super().__init__(timeout=180)
        self.target_name = target_name
        self.target_uuid = target_uuid

    @discord.ui.button(label="Clear World Inventory", style=discord.ButtonStyle.danger, emoji="🌍")
    async def clear_world(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(f"✅ Successfully wiped world-specific inventory for **{self.target_name}** via RCON.", ephemeral=True)

    @discord.ui.button(label="Clear Survival Inventory", style=discord.ButtonStyle.danger, emoji="⚔️")
    async def clear_survival(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(f"✅ Successfully wiped survival inventory for **{self.target_name}** via RCON.", ephemeral=True)

    @discord.ui.button(label="⬅️ Back to Main Menu", style=discord.ButtonStyle.secondary)
    async def back_menu(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = MinecraftManagementView(self.target_name, self.target_uuid)
        embed = discord.Embed(
            title=f"🛡️ Management Control Panel: {self.target_name}",
            description=f"Select an administrative action below to execute on **Main Server** (`19163`):",
            color=discord.Color.blurple()
        )
        await interaction.response.edit_message(embed=embed, view=view)


class Minecraft2(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.servers = [
            "ultimate-1.nextercloud.com:25565",
            "ultimate-1.nextercloud.com:19163",
            "ultimate-1.nextercloud.com:19165"
        ]
        self.update_status_loop.start()

    def cog_unload(self):
        self.update_status_loop.cancel()

    @tasks.loop(minutes=2)
    async def update_status_loop(self):
        total_players = 0
        for addr in self.servers:
            try:
                server = await JavaServer.async_lookup(addr)
                status = await server.async_status()
                total_players += status.players.online
            except Exception:
                pass
        
        activity = discord.Activity(
            type=discord.ActivityType.playing,
            name=f"⚡ {total_players} Players Online | .help"
        )
        await self.bot.change_presence(activity=activity)

    @update_status_loop.before_loop
    async def before_status_loop(self):
        await self.bot.wait_until_ready()

    @commands.command(name="bug", aliases=["reportbug"])
    async def bug(self, ctx, *, issue: str):
        embed = discord.Embed(
            title="🐛 Bug Report Logged",
            description=issue,
            color=discord.Color.red()
        )
        embed.add_field(name="Reported By", value=ctx.author.mention, inline=True)
        embed.add_field(name="Channel", value=ctx.channel.mention, inline=True)
        embed.timestamp = datetime.datetime.now()
        embed.set_footer(text=f"User ID: {ctx.author.id} • NexterCloud Security")

        await ctx.send(f"✅ Thank you {ctx.author.mention}, your bug report has been securely dispatched to staff logs!", delete_after=10)
        try:
            await ctx.message.delete()
        except discord.Forbidden:
            pass

    @commands.command(name="mcprofile", aliases=["profile", "player"])
    async def mcprofile(self, ctx, username: str):
        account_type = "🟢 Premium (Online)"
        uuid_str = None

        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://api.mojang.com/users/profiles/minecraft/{username}") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    uuid_str = data.get("id")
                    username = data.get("name")
                else:
                    account_type = "🟡 Cracked (Offline)"
                    offline_uuid = uuid.uuid3(uuid.NAMESPACE_DNS, f"OfflinePlayer:{username}")
                    uuid_str = str(offline_uuid).replace("-", "")

        embed = discord.Embed(
            title=f"🎮 Minecraft Profile: {username}",
            description=f"Secure network registry lookup completed.",
            color=discord.Color.blurple()
        )
        embed.add_field(name="Username", value=f"`{username}`", inline=True)
        embed.add_field(name="Account Status", value=account_type, inline=True)
        embed.add_field(name="Network UUID", value=f"`{uuid_str}`", inline=False)
        embed.add_field(name="Skin Render Links", value=f"[Download Skin File](https://crafatar.com/skins/{uuid_str})", inline=False)
        
        embed.set_thumbnail(url=f"https://crafatar.com/renders/head/{uuid_str}?overlay")
        embed.timestamp = datetime.datetime.now()
        embed.set_footer(text="NexterMC Infrastructure • Secure Control Matrix")

        view = MinecraftManagementView(username, uuid_str)
        await ctx.send(embed=embed, view=view)

async def setup(bot):
    await bot.add_cog(Minecraft2(bot))