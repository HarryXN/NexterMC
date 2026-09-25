# permissions.py
import discord
from discord.ext import commands

# Your specific Owner User ID
OWNER_ID = 1006250810142883851

def is_staff_or_owner():
    """Custom check that allows you (the owner) or users with staff permissions."""
    async def predicate(ctx: commands.Context) -> bool:
        if ctx.author.id == OWNER_ID:
            return True
        if ctx.channel.permissions_for(ctx.author).manage_channels:
            return True
        return False
    return commands.check(predicate)