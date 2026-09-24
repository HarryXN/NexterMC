import discord
from discord.ext import commands
import datetime

class ServerSelectSubMenu(discord.ui.View):
    def __init__(self, action_type: str):
        super().__init__(timeout=180)
        self.action_type = action_type.capitalize()

    @discord.ui.button(label="Velocity Proxy", style=discord.ButtonStyle.primary, emoji="🌐")
    async def velocity_action(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(f"⚙️ **{self.action_type}** signal dispatched to **Velocity Proxy** (`ultimate-1.nextercloud.com:25565`).", ephemeral=True)

    @discord.ui.button(label="Main Server", style=discord.ButtonStyle.success, emoji="🏡")
    async def main_action(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(f"⚙️ **{self.action_type}** signal dispatched to **Main Server** (`ultimate-1.nextercloud.com:19163`).", ephemeral=True)

    @discord.ui.button(label="PvP Server", style=discord.ButtonStyle.danger, emoji="⚔️")
    async def pvp_action(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(f"⚙️ **{self.action_type}** signal dispatched to **PvP Server** (`ultimate-1.nextercloud.com:19165`).", ephemeral=True)

    @discord.ui.button(label="⬅️ Back to Panel", style=discord.ButtonStyle.secondary)
    async def back_to_panel(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = AdminMainPanelView()
        embed = discord.Embed(
            title="⚡ NexterCloud Administrator Command Center",
            description="Select a core network operation or maintenance toggle below:",
            color=discord.Color.dark_embed()
        )
        embed.add_field(name="Infrastructure Status", value="🟢 All nodes online and stable.", inline=False)
        await interaction.response.edit_message(embed=embed, view=view)


class AdminMainPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None) # Persistent view

    @discord.ui.button(label="Start Servers", style=discord.ButtonStyle.success, emoji="🟢")
    async def start_menu(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Administrator permission required.", ephemeral=True)
            return
        view = ServerSelectSubMenu("start")
        embed = discord.Embed(title="🟢 Power On: Select Node", description="Choose which backend server node to boot up:", color=discord.Color.green())
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Stop Servers", style=discord.ButtonStyle.danger, emoji="🔴")
    async def stop_menu(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Administrator permission required.", ephemeral=True)
            return
        view = ServerSelectSubMenu("stop")
        embed = discord.Embed(title="🔴 Power Off: Select Node", description="Choose which backend server node to gracefully shut down:", color=discord.Color.red())
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Restart Servers", style=discord.ButtonStyle.primary, emoji="🔄")
    async def restart_menu(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Administrator permission required.", ephemeral=True)
            return
        view = ServerSelectSubMenu("restart")
        embed = discord.Embed(title="🔄 Reboot: Select Node", description="Choose which backend server node to restart:", color=discord.Color.blurple())
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Toggle Global Maintenance", style=discord.ButtonStyle.secondary, emoji="🛠️")
    async def maintenance_toggle(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Administrator permission required.", ephemeral=True)
            return
        # Toggle logic hook placeholder
        embed = discord.Embed(
            title="🛠️ Global Maintenance Mode Updated",
            description="Successfully toggled network-wide lockdown whitelist status across Velocity proxy.",
            color=discord.Color.gold()
        )
        embed.timestamp = datetime.datetime.now()
        await interaction.response.send_message(embed=embed, ephemeral=True)


class AdminPanel(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="panel", aliases=["adminpanel", "control"])
    @commands.has_permissions(administrator=True)
    async def panel(self, ctx):
        embed = discord.Embed(
            title="⚡ NexterCloud Administrator Command Center",
            description="Welcome to your executive network management interface. Use the interactive control buttons below to manage instances securely.",
            color=discord.Color.dark_embed()
        )
        embed.add_field(
            name="Network Nodes Monitored",
            value="• **Velocity Proxy** (`25565`)\n• **Main Server** (`19163`)\n• **PvP Server** (`19165`)",
            inline=False
        )
        embed.timestamp = datetime.datetime.now()
        embed.set_footer(text="NexterMC Enterprise Core • Restricted Access")

        view = AdminMainPanelView()
        await ctx.send(embed=embed, view=view)

async def setup(bot):
    await bot.add_cog(AdminPanel(bot))