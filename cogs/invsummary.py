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
        help="Audits invite claims, bot logs, and event rules to calculate final net invite counts.",
    )
    async def invsummary(self, ctx):
        loading_msg = await ctx.reply("⏳ Fetching event rules and parsing invite logs & bot outputs...", mention_author=False)

        try:
            messages_history = []
            async for message in ctx.channel.history(limit=100, oldest_first=True):
                if not message.author.bot or message.author.id == self.bot.user.id:
                    # Keep user messages and bot logs (like Falcon or ticketing bots)
                    messages_history.append(f"{message.author.name}: {message.content}")
                    # Also include embed descriptions if bots use embeds for invite logs
                    for embed in message.embeds:
                        if embed.description:
                            messages_history.append(f"[{message.author.name} Embed]: {embed.description}")
                        for field in embed.fields:
                            messages_history.append(f"[{message.author.name} Field]: {field.name} - {field.value}")

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
                        rules_messages.append(r_msg.s if hasattr(r_msg, 'content') else r_msg.content)
                    if rules_messages:
                        rules_transcript = "\n".join(rules_messages)
                except Exception as e:
                    rules_transcript = f"⚠️ Could not load rules: {e}"

            prompt = (
                "You are an elite, highly rigorous reward and invite auditor. "
                "Analyze the official Event Rules and the entire Ticket Transcript (including bot logs from bots like Falcon showing Joins, Left, Fakes, etc.). "
                "Perform a precise arithmetic and rule-compliance audit. If rules or deductions (leaves, fakes, penalties) drop the count below zero, calculate the actual negative number.\n\n"
                "Provide the response using clean Markdown bullet points. No tables, no HTML.\n\n"
                "Use this exact structure:\n"
                "• **Claimed Invites:** [Number claimed by the user]\n"
                "• **Bot Log Data Found:** [Summary of Joins, Left, Fakes, or net stats reported by invite bots in the transcript]\n"
                "• **Deductions & Rule Violations:** [Explicit breakdown of penalties, leaves, fakes, or missing criteria]\n"
                "• **FINAL INVITES COUNT:** [The exact calculated final count after all rules and deductions—can be negative if penalties exceed valid joins]\n"
                "• **Reward Eligibility:** [Met / Not Met, along with remaining requirements]\n"
                "• **Final Staff Verdict:** [1 sentence conclusion telling staff exact next action]\n\n"
                f"--- OFFICIAL EVENT RULES ---\n{rules_transcript}\n\n"
                f"--- TICKET TRANSCRIPT & BOT LOGS ---\n{chat_transcript}"
            )

            chat_completion = self.groq_client.chat.completions.create(
                model=self.model_id,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_completion_tokens=2048,
            )

            summary_text = chat_completion.choices[0].message.content

            embed = discord.Embed(
                title="🎁 Advanced Invite & Reward Audit",
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
    await bot.add_cog(SummaryCog(bot) if 'SummaryCog' in globals() else InvSummaryCog(bot))