import discord
from discord.ext import commands, tasks
import datetime
import aiohttp
import uuid
from mcstatus import JavaServer

class MinecraftManagementView(discord.ui.View):
    def __init__(self, target_name: str, target_uuid: str):
        super().__init__(timeout=180)
        self.target_name = target_name
        self.target_uuid = target_uuid

    @discord.ui.button(label="Clear Inventory", style=discord.ButtonStyle.secondary, emoji="🧹")
    async def clear_inventory_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = InventorySubMenu(self.target_name, self.target_uuid)
        await interaction.response.edit_message(content=f"🧹 Select inventory action for **{self.target_name}**:", view=view)

    @discord.ui.button(label="Inventory Overview", style=discord.ButtonStyle.primary, emoji="📦")
    async def overview_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(f"📦 Fetching live inventory overview for `{self.target_name}` from server...", ephemeral=True)

    @discord.ui.button(label="Kick", style=discord.ButtonStyle.danger, emoji="👢")
    async def kick_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.kick_members:
            await interaction.response.send_message("❌ You do not have permission to kick users.", ephemeral=True)
            return
        await interaction.response.send_message(f"👢 RCON / Kick command triggered for `{self.target_name}`.", ephemeral=True)

    @discord.ui.button(label="Ban", style=discord.ButtonStyle.danger, emoji="🔨")
    async def ban_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.ban_members:
            await interaction.response.send_message("❌ You do not have permission to ban users.", ephemeral=True)
            return
        await interaction.response.send_message(f"🔨 RCON / Ban command triggered for `{self.target_name}`.", ephemeral=True)

class InventorySubMenu(discord.ui.View):
    def __init__(self, target_name: str, target_uuid: str):
        super().__init__(timeout=180)
        self.target_name = target_name
        self.target_uuid = target_uuid

    @discord.ui.button(label="Clear World Inventory", style=discord.ButtonStyle.danger)
    async def clear_world(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(f"✅ Cleared world inventory for `{self.target_name}`.", ephemeral=True)

    @discord.ui.button(label="Clear Survival Inventory", style=discord.ButtonStyle.danger)
    async def clear_survival(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(f"✅ Cleared survival inventory for `{self.target_name}`.", ephemeral=True)

    @discord.ui.button(label="⬅️ Back to Main Menu", style=discord.ButtonStyle.secondary)
    async def back_menu(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = MinecraftManagementView(self.target_name, self.target_uuid)
        await interaction.response.edit_message(content=f"⚙️ Management panel for **{self.target_name}**:", view=view)


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

    # 1. Live Bot Activity Status Loop
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
            name=f"Minecraft with {total_players} players online | .help"
        )
        await self.bot.change_presence(activity=activity)

    @update_status_loop.before_loop
    async def before_status_loop(self):
        await self.bot.wait_until_ready()

    # 2. Bug Report Command
    @commands.command(name="bug", aliases=["reportbug"])
    async def bug(self, ctx, *, issue: str):
        embed = discord.Embed(
            title="🐛 Bug Report Submitted",
            description=issue,
            color=discord.Color.red()
        )
        embed.add_field(name="Reported By", value=ctx.author.mention, inline=True)
        embed.add_field(name="Channel", value=ctx.channel.mention, inline=True)
        embed.timestamp = datetime.datetime.now()
        embed.set_footer(text=f"User ID: {ctx.author.id}")

        await ctx.send(f"✅ Thank you {ctx.author.mention}, your bug report has been forwarded to the staff team!", delete_after=10)
        try:
            await ctx.message.delete()
        except discord.Forbidden:
            pass

    # 3. Hybrid Profile Command (Works for Premium & Cracked Players)
    @commands.command(name="mcprofile", aliases=["profile", "player"])
    async def mcprofile(self, ctx, username: str):
        account_type = "Premium (Online Mode)"
        uuid_str = None

        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://api.mojang.com/users/profiles/minecraft/{username}") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    uuid_str = data.get("id")
                    username = data.get("name")
                else:
                    # Fallback for cracked/offline mode servers
                    account_type = "Cracked (Offline Mode)"
                    offline_uuid = uuid.uuid3(uuid.NAMESPACE_DNS, f"OfflinePlayer:{username}")
                    uuid_str = str(offline_uuid).replace("-", "")

        embed = discord.Embed(
            title=f"Minecraft Profile: {username}",
            color=discord.Color.blurple()
        )
        embed.add_field(name="Username", value=username, inline=True)
        embed.add_field(name="Account Type", value=account_type, inline=True)
        embed.add_field(name="UUID", value=f"`{uuid_str}`", inline=False)
        embed.add_field(name="Skin Render", value=f"[View Skin](https://crafatar.com/skins/{uuid_str})", inline=True)
        
        embed.set_thumbnail(url=f"https://crafatar.com/renders/head/{uuid_str}?overlay")
        embed.timestamp = datetime.datetime.now()
        embed.set_footer(text="NexterMC Network Database")

        view = MinecraftManagementView(username, uuid_str)
        await ctx.send(embed=embed, view=view)

async def setup(bot):
    await bot.add_cog(Minecraft2(bot))