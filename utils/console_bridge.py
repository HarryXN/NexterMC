# utils/console_bridge.py
"""
Single, shared path for anything the bot sends to the Minecraft console
bridge channel (DiscordSRV-style: a Discord message in this channel is
read as a console command by the server).

Centralizing this means the sanitization logic only has to be right once.
Free-text fields (ban/kick reasons, usernames) get funneled through here
before ever reaching the bridge, so a newline in a reason can't be read as
a second console command.
"""
from discord.ext import commands

from config import MAIN_SERVER_CONSOLE_ID


def sanitize_console_arg(text: str, max_len: int = 200) -> str:
    if not text:
        return "No reason provided"
    cleaned = text.replace("\n", " ").replace("\r", " ").strip()
    return cleaned[:max_len] if cleaned else "No reason provided"


async def dispatch_console(bot: commands.Bot, command: str) -> bool:
    """Send one sanitized line to the console-bridge channel.
    Returns False if the channel couldn't be reached, so callers can tell
    the user honestly whether anything actually happened."""
    channel = bot.get_channel(MAIN_SERVER_CONSOLE_ID)
    if channel is None:
        return False
    await channel.send(sanitize_console_arg(command, max_len=400))
    return True
