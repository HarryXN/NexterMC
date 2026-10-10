# cogs/fullsummary.py
import logging

import discord
from discord.ext import commands

from config import AI_COMMAND_COOLDOWN_SECONDS, plan_context_for_category
from utils.ai_client import AIConfigError, AIResponseError
from utils.transcript import analyze_transcript, chunk_lines, fetch_transcript_lines

log = logging.getLogger("nextermc.fullsummary")


def _build_final_prompt(source_text: str, message_count: int, plan_context: str) -> str:
    return (
        f"You are a senior auditor for NexterCloud hosting ({plan_context}), producing a master "
        "report on a long-running ticket. The material below is either the raw transcript "
        "(if short) or condensed factual notes extracted section-by-section from the full "
        "history (if long) — in the latter case, every part of the ticket has already been read, "
        "so synthesize across all sections rather than treating this as incomplete.\n\n"
        "Be short and direct. This is a report someone will actually read, not an archive — "
        "compress ruthlessly. Each bullet is at most two sentences. No filler, no repeated "
        "phrasing, no restating the plan type more than once.\n\n"
        "Output EXACTLY this Markdown format, nothing before or after it:\n"
        "### 📋 Full Ticket Master Report\n"
        f"• **Hosting Context:** {plan_context}\n"
        "• **Origin & Goal:** [why this ticket was opened]\n"
        "• **Key Milestones:** [the 2-4 developments that actually mattered, chronologically]\n"
        "• **Staff & User Actions:** [what was actually done, by whom]\n"
        "• **Current Status:** [where it stands right now, or the final resolution]\n\n"
        f"--- MATERIAL ({message_count} messages analyzed) ---\n{source_text}"
    )


class FullSummaryCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(
        name="fullsummary",
        help="Deep analysis of the entire ticket history (map-reduced so it scales to any length) — still a short report.",
    )
    @commands.cooldown(1, AI_COMMAND_COOLDOWN_SECONDS, commands.BucketType.channel)
    async def fullsummary(self, ctx):
        loading_msg = await ctx.reply("⏳ Scanning full ticket history...", mention_author=False)
        stage = "reading ticket history"

        try:
            lines = await fetch_transcript_lines(ctx.channel, limit=None)
            if not lines:
                await loading_msg.edit(content="❌ No message history found.")
                return

            section_count = len(chunk_lines(lines))
            await loading_msg.edit(
                content=(
                    f"🧠 Deep-analyzing {len(lines)} messages across {section_count} sections — "
                    "this may take a moment..."
                )
            )

            category_id = ctx.channel.category_id if ctx.channel.category else None
            plan_context = plan_context_for_category(category_id)

            stage = f"analyzing {len(lines)} messages across {section_count} sections"
            result = await analyze_transcript(
                lines,
                lambda src, count: _build_final_prompt(src, count, plan_context),
                final_max_tokens=4096,
            )
            if not result.text.strip():
                raise AIResponseError("The model completed without returning report text.")

            stage = "formatting and sending the report"
            embed = discord.Embed(
                title="📋 NexterCloud Full Ticket Master Report",
                description=result.text[:4000],
                color=discord.Color.purple(),
            )
            embed.set_footer(
                text=(
                    f"Requested by {ctx.author.name} • {result.message_count} messages "
                    f"across {result.chunks_analyzed} section(s) analyzed"
                )
            )
            await ctx.send(embed=embed)
            try:
                await loading_msg.delete()
            except discord.HTTPException:
                pass

        except AIConfigError as e:
            await loading_msg.edit(content=f"❌ {e}")
        except AIResponseError as e:
            log.warning("fullsummary received no usable AI text in channel %s: %s", ctx.channel.id, e)
            await loading_msg.edit(content="❌ The AI returned no usable report text after retrying. Check the model/service logs and try again.")
        except Exception:
            log.exception("fullsummary failed while %s in channel %s", stage, ctx.channel.id)
            await loading_msg.edit(content=f"❌ Full summary failed while {stage}. The detailed error is in the bot logs.")


async def setup(bot):
    await bot.add_cog(FullSummaryCog(bot))
