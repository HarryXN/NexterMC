"""Forward application error tracebacks to the configured private Discord channel."""
from __future__ import annotations

import asyncio
import datetime
import io
import logging
import os
import re
import time

import discord
from discord.ext import commands

from config import CRASH_LOG_CHANNEL_ID

_handler: DiscordCrashLogHandler | None = None


class DiscordCrashLogHandler(logging.Handler):
    """Queue error records off the logging call path and send them as text files."""

    def __init__(self, bot: commands.Bot):
        super().__init__(level=logging.ERROR)
        self.bot = bot
        self.loop = bot.loop
        self.queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue(maxsize=100)
        self.worker = self.loop.create_task(self._send_logs())
        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        formatter.converter = time.gmtime
        self.setFormatter(formatter)

    def emit(self, record: logging.LogRecord) -> None:
        # The handler is ERROR-level, so this includes application tracebacks
        # and uncaught Discord.py/runtime errors while ignoring normal warnings.
        if record.name == "discord_crash_log":
            return
        try:
            message = self.format(record)
            for secret_name in ("DISCORD_TOKEN", "GROQ_API_KEY", "PANEL_API_KEY"):
                secret = os.getenv(secret_name)
                if secret:
                    message = message.replace(secret, "[REDACTED]")
            if not self.loop.is_closed():
                self.loop.call_soon_threadsafe(self._enqueue, record.name, message)
        except Exception:
            # Never log through logging here or a failed handler can recurse.
            print("Discord crash-log handler could not queue an error record.")

    def _enqueue(self, logger_name: str, message: str) -> None:
        try:
            self.queue.put_nowait((logger_name, message))
        except asyncio.QueueFull:
            print("Discord crash-log queue is full; an error record was dropped.")

    async def _send_logs(self) -> None:
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            logger_name, message = await self.queue.get()
            try:
                channel = self.bot.get_channel(CRASH_LOG_CHANNEL_ID)
                if channel is None:
                    channel = await self.bot.fetch_channel(CRASH_LOG_CHANNEL_ID)
                if not hasattr(channel, "send"):
                    raise TypeError("Configured crash-log channel does not support messages.")

                message = message[:120_000]
                stream = io.BytesIO(message.encode("utf-8", errors="replace"))
                stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
                safe_logger = re.sub(r"[^A-Za-z0-9_-]", "_", logger_name)[:48]
                attachment = discord.File(stream, filename=f"crash-{safe_logger}-{stamp}.txt")
                try:
                    await channel.send(
                        content=f"🚨 **Bot error log** · `{logger_name}` · {stamp} UTC",
                        file=attachment,
                    )
                except discord.HTTPException as exc:
                    # The bot may have Send Messages without Attach Files, or
                    # Discord may reject a large file. Send a short traceback
                    # excerpt as a regular message so the event still reaches staff.
                    excerpt = discord.utils.escape_mentions(message[:1450]).replace("```", "''' ")
                    await channel.send(
                        content=(
                            f"🚨 **Bot error log** · `{logger_name}` · {stamp} UTC\n"
                            f"(Attachment upload failed: {type(exc).__name__})\n"
                            f"```text\n{excerpt}\n```"
                        )
                    )
            except Exception as exc:
                print(
                    f"Could not forward a bot error log to channel {CRASH_LOG_CHANNEL_ID}: "
                    f"{type(exc).__name__}: {exc}"
                )
            finally:
                self.queue.task_done()


def configure_discord_crash_logging(bot: commands.Bot) -> None:
    """Attach one asynchronous error handler to the root logger."""
    global _handler
    if _handler is not None:
        return
    _handler = DiscordCrashLogHandler(bot)
    logging.getLogger().addHandler(_handler)
