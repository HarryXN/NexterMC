# cogs/summary.py
import os
import discord
from discord.ext import commands
from groq import Groq

EVENT_RULES_CHANNEL_ID = 1419933431399452753

class SummaryCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        groq_api_key = os.getenv("GROQ_API_KEY")
        if not groq_api_key:
            print("WARNING: GROQ_API_KEY is missing from environment variables!")
        self.groq_client = Groq(api_key=groq_api_key)
        # Using the verified working model from your Groq playground
        self.model_id = "openai/gpt-oss-120b"

    @commands.command(
        name="summarize",
        help="Summarizes ticket transcripts, checks event rules, and evaluates invite requirements.",
    )
    async def summarize(self, ctx):
        loading_msg = await ctx.reply("⏳ Fetching channel data and analyzing rules...", mention_author=False)

        try:
            # 1. Fetch Ticket Channel History (Up to 100 messages)
            messages_history = []
            async for message in ctx.channel.history(limit=100, oldest_first=True):
                if not message.author.bot:
                    messages_history.append(f"{message.author.name}: {message.content}")

            if not messages_history:
                await loading_msg.edit(content="❌ No user messages found in this channel to summarize.")
                return

            chat_transcript = "\n".join(messages_history)

            # 2. Fetch Event Rules Channel Messages dynamically
            rules_transcript = "No event rules channel found or accessible."
            rules_channel = self.bot.get_channel(EVENT_RULES_CHANNEL_ID)
            
            if rules_channel:
                try:
                    rules_messages = []
                    async for r_msg in rules_channel.history(limit=50, oldest_first=True):
                        rules_messages.append(r_msg.content)
                    if rules_messages:
                        rules_transcript = "\n".join(rules_messages)
                except discord.Forbidden:
                    rules_transcript = "⚠️ Bot lacks permission to read the event rules channel."
                except Exception as e:
                    rules_transcript = f"⚠️ Could not load rules due to error: {e}"
            else:
                rules_transcript = "⚠️ Event rules channel ID not found or bot cannot see it."

            # 3. Construct the comprehensive AI prompt
            prompt = (
                "You are an expert support supervisor and server auditor. "
                "Review the following official Event Rules and the ongoing Support/Reward Ticket Transcript. "
                "Provide a structured executive summary covering:\n"
                "1. **User Issue / Core Problem**\n"
                "2. **Troubleshooting Steps Taken**\n"
                "3. **Resolution Status (Resolved/Pending)**\n"
                "4. **Possible Easy Solutions / Next Steps**\n"
                "5. **Invite & Rule Evaluation (ONLY IF THIS IS AN INVITE/REWARD TICKET):** "
                "Analyze the event rules provided below against the user's claims in the ticket. State clearly whether they qualify, if any invites should be deducted/verified, and why.\n\n"
                f"--- OFFICIAL EVENT RULES ---\n{rules_transcript}\n\n"
                f"--- TICKET TRANSCRIPT ---\n{chat_transcript}"
            )

            # 4. Call Groq API matching your playground structure
            chat_completion = self.groq_client.chat.completions.create(
                model=self.model_id,
                messages=[
                    {
                        "role": "user",
                        "content": f"You are a precise server management assistant. Evaluate rule compliance accurately.\n\n{prompt}"
                    }
                ],
                temperature=0.2,
                max_completion_tokens=2048,
            )

            if not chat_completion.choices or not chat_completion.choices[0].message.content:
                raise ValueError("Groq returned an empty response.")

            summary_text = chat_completion.choices[0].message.content

            embed = discord.Embed(
                title="🤖 AI Ticket Summary & Invite Audit",
                description=summary_text,
                color=discord.Color.blue(),
            )
            embed.set_footer(text=f"Requested by {ctx.author.name} | Audited against Rules Channel ID: {EVENT_RULES_CHANNEL_ID}")
            
            await loading_msg.delete()
            await ctx.send(embed=embed)

        except Exception as e:
            error_msg = f"❌ **Bug / Error Encountered in Summarize Command:**\n```python\n{str(e)}\n```"
            print(f"Summarize Error: {e}")
            try:
                await loading_msg.edit(content=error_msg)
            except Exception:
                await ctx.send(error_msg)

async def setup(bot):
    await bot.add_cog(SummaryCog(bot))