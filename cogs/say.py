import discord
from discord.ext import commands

class Say(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name="say", description="Makes the bot send a message in a specified channel.")
    async def say(self, ctx, channel: discord.TextChannel, *, message: str):
        # Restrict strictly to your specific User ID
        ALLOWED_USER_ID = 1006250810142883851
        
        if ctx.author.id != ALLOWED_USER_ID:
            await ctx.send("You do not have permission to use this command.", delete_after=5)
            return

        if ctx.message is not None and ctx.interaction is None:
            try:
                await ctx.message.delete()
            except discord.Forbidden:
                pass
        
        await channel.send(message)

    @say.error
    async def say_error(self, ctx, error):
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send("Usage: `,say #channel Your message here`", delete_after=5)

async def setup(bot):
    await bot.add_cog(Say(bot))
