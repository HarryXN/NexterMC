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
        help="Provides a clean, concise, and professional general summary of the support ticket.",
    )
    async def summarize(self, ctx):
        loading_msg = await ctx.reply("⏳ Synthesizing general ticket overview...", mention_author=False)

        try:
            messages_history = []
            async for message in ctx.channel.history(limit=100, oldest_first=True):
                content = f"{message.author.name}: {message.content}"
                for embed in message.embeds:
                    if embed.title:
                        content += f" [Embed Title: {embed.title}]"
                    if embed.description:
                        content += f" [Embed Desc: {embed.description}]"
                    for field in embed.fields:
                        content += f" [{field.name}: {field.value}]"
                messages_history.append(content)

            if not messages_history:
                await loading_msg.edit(content="❌ No message history found to summarize.")
                return

            chat_transcript = "\n".join(messages_history)

            prompt = (
                "You are an expert senior support supervisor for NexterCloud Hosting. Review the ticket transcript "
                "and generate a highly professional, clear, concise, and eye-catching general summary using Markdown. "
                "Avoid overly technical jargon; use easy-to-understand, crisp words.\n\n"
                "Strictly follow this layout:\n"
                "### 📌 General Ticket Overview\n"
                "• **Core Issue:** [Brief description of what prompted the ticket]\n"
                "• **Actions Taken:** [What staff and user did so far]\n"
                "• **Current Status:** [Active / Pending / Resolved]\n"
                "• **Recommended Next Step:** [Immediate action needed]\n\n"
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
                title="✨ General Ticket Summary",
                description=summary_text,
                color=discord.Color.blue(),
            )
            embed.set_footer(text=f"Requested by {ctx.author.name} • NexterMC Support")
            
            await loading_msg.delete()
            await ctx.send(embed=embed)

        except Exception as e:
            error_msg = f"❌ **Error in summarize command:**\n```python\n{str(e)}\n```"
            await loading_msg.edit(content=error_msg)

async def setup(bot):
    await bot.add_cog(SummaryCog(bot))