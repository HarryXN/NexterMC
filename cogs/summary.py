# cogs/summary.py
import os
import discord
from discord.ext import commands
from groq import Groq

class SummaryCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        groq_api_key = os.getenv("GROQ_API_KEY")
        self.groq_client = Groq(api_key=groq_api_key)
        self.model_id = "openai/gpt-oss-120b"

    @commands.command(
        name="summarize",
        help="Provides a clean general summary of the support ticket issues and troubleshooting steps.",
    )
    async def summarize(self, ctx):
        loading_msg = await ctx.reply("⏳ Generating general ticket summary...", mention_author=False)

        try:
            messages_history = []
            async for message in ctx.channel.history(limit=100, oldest_first=True):
                if not message.author.bot:
                    messages_history.append(f"{message.author.name}: {message.content}")

            if not messages_history:
                await loading_msg.edit(content="❌ No user messages found to summarize.")
                return

            chat_transcript = "\n".join(messages_history)

            prompt = (
                "You are an expert support supervisor. Review the following support ticket transcript "
                "and provide a clear, concise executive summary using clean Markdown bullet points. No tables, no HTML.\n\n"
                "Use this exact structure:\n"
                "• **Core Problem:** [What is the user's main issue?]\n"
                "• **Troubleshooting Steps:** [What has been tested or done so far?]\n"
                "• **Current Status:** [Pending / Resolved / Escalated]\n"
                "• **Next Steps & Solutions:** [Actionable steps for staff or user to resolve it]\n\n"
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
                title="🤖 General Ticket Summary",
                description=summary_text,
                color=discord.Color.blue(),
            )
            embed.set_footer(text=f"Requested by {ctx.author.name}")
            
            await loading_msg.delete()
            await ctx.send(embed=embed)

        except Exception as e:
            error_msg = f"❌ **Error in summarize command:**\n```python\n{str(e)}\n```"
            await loading_msg.edit(content=error_msg)

async def setup(bot):
    await bot.add_cog(SummaryCog(bot))