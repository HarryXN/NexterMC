# cogs/invsummary.py
import os
import discord
from discord.ext import commands
from groq import Groq

EVENT_RULES_CHANNEL_ID = 1419933431399452753

class InvSummaryCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        groq_api_key = os.getenv("GROQ_API_KEY")
        self.groq_client = Groq(api_key=groq_api_key)
        self.model_id = "openai/gpt-oss-120b"

    @commands.command(
        name="invsummary",
        help="Audits invite claims against official event rules and calculates final qualified invites.",
    )
    async def invsummary(self, ctx):
        loading_msg = await ctx.reply("⏳ Fetching event rules and auditing invite requirements...", mention_author=False)

        try:
            messages_history = []
            async for message in ctx.channel.history(limit=100, oldest_first=True):
                if not message.author.bot:
                    messages_history.append(f"{message.author.name}: {message.content}")

            if not messages_history:
                await loading_msg.edit(content="❌ No messages found to audit.")
                return

            chat_transcript = "\n".join(messages_history)

            rules_transcript = "No event rules channel found or accessible."
            rules_channel = self.bot.get_channel(EVENT_RULES_CHANNEL_ID)
            
            if rules_channel:
                try:
                    rules_messages = []
                    async for r_msg in rules_channel.history(limit=50, oldest_first=True):
                        rules_messages.append(r_msg.content)
                    if rules_messages:
                        rules_transcript = "\n".join(rules_messages)
                except Exception as e:
                    rules_transcript = f"⚠️ Could not load rules: {e}"

            prompt = (
                "You are an elite reward auditor. Review the official Event Rules and the Ticket Transcript. "
                "Provide a rigorous, clear invite & reward audit using Markdown bullet points. No tables, no HTML.\n\n"
                "Use this exact structure:\n"
                "• **Claimed Invites:** [Number claimed by user]\n"
                "• **Valid Verified Invites:** [Final calculated count after rules]\n"
                "• **Deductions & Violations:** [Missing bio/pfp, fake invites, or rule breaches with reasons]\n"
                "• **Reward Eligibility:** [Met / Not Met, and what proof/requirements are missing]\n"
                "• **Final Staff Verdict:** [1 sentence conclusion and exact next action for staff]\n\n"
                f"--- OFFICIAL EVENT RULES ---\n{rules_transcript}\n\n"
                f"--- TICKET TRANSCRIPT ---\n{chat_transcript}"
            )

            chat_completion = self.groq_client.chat.completions.create(
                model=self.model_id,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_completion_tokens=2048,
            )

            summary_text = chat_completion.choices[0].message.content

            embed = discord.Embed(
                title="🎁 Invite & Reward Audit",
                description=summary_text,
                color=discord.Color.green(),
            )
            embed.set_footer(text=f"Requested by {ctx.author.name} | Audited against Rules ID: {EVENT_RULES_CHANNEL_ID}")
            
            await loading_msg.delete()
            await ctx.send(embed=embed)

        except Exception as e:
            error_msg = f"❌ **Error in invsummary command:**\n```python\n{str(e)}\n```"
            await loading_msg.edit(content=error_msg)

async def setup(bot):
    await bot.add_cog(InvSummaryCog(bot))