# cogs/summary.py
import logging

import discord
from discord.ext import commands

from config import AI_COMMAND_COOLDOWN_SECONDS, plan_context_for_category
from utils.ai_client import AIConfigError
from utils.transcript import analyze_transcript, fetch_transcript_lines

log = logging.getLogger("nextermc.summary")


def _build_final_prompt(source_text: str, message_count: int, plan_context: str) -> str:
    return (
        f"You are a support supervisor for NexterCloud hosting ({plan_context}). "
        "Using the material below (either the raw transcript, or condensed notes extracted "
        "from a longer transcript), write a SHORT, direct, factual ticket summary. No filler, "
        "no speculation, no repeating the material verbatim. If something is unclear from the "
        "material, say so plainly rather than guessing.\n\n"
        "Output EXACTLY this Markdown format, nothing before or after it:\n"
        "### 📌 Ticket Overview\n"
        f"• **Plan Type:** {plan_context}\n"
        "• **Core Issue:** [one sentence]\n"
        "• **Actions Taken:** [one or two sentences]\n"
        "• **Status:** [Active / Resolved / Awaiting User Response]\n\n"
        f"--- MATERIAL ({message_count} messages analyzed) ---\n{source_text}"
    )


class SummaryCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(
        name="summarize",
        aliases=["summary"],
        help="Short, accurate ticket overview — analyzes the full channel history, answers in a few bullets.",
    )
    @commands.cooldown(1, AI_COMMAND_COOLDOWN_SECONDS, commands.BucketType.channel)
    async def summarize(self, ctx):
        loading_msg = await ctx.reply("⏳ Analyzing ticket...", mention_author=False)

        try:
            lines = await fetch_transcript_lines(ctx.channel, limit=None)
            if not lines:
                await loading_msg.edit(content="❌ No message history found.")
                return

            category_id = ctx.channel.category_id if ctx.channel.category else None
            plan_context = plan_context_for_category(category_id)

            result = await analyze_transcript(
                lines, lambda src, count: _build_final_prompt(src, count, plan_context)
            )

            embed = discord.Embed(
                title="✨ General Ticket Summary",
                description=result.text,
                color=discord.Color.blue(),
            )
            embed.set_footer(
                text=f"Requested by {ctx.author.name} • {result.message_count} messages analyzed"
            )
            await loading_msg.delete()
            await ctx.send(embed=embed)

        except AIConfigError as e:
            await loading_msg.edit(content=f"❌ {e}")
        except Exception:
            log.exception("summarize failed in channel %s", ctx.channel.id)
            await loading_msg.edit(content="❌ Something went wrong generating the summary. The issue has been logged.")


async def setup(bot):
    await bot.add_cog(SummaryCog(bot))
