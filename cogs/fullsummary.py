# cogs/fullsummary.py
import os
import discord
from discord.ext import commands
from groq import Groq

class FullSummaryCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        groq_api_key = os.getenv("GROQ_API_KEY")
        self.groq_client = Groq(api_key=groq_api_key)
        self.model_id = "openai/gpt-oss-120b"

    @commands.command(
        name="fullsummary",
        help="Provides a comprehensive master summary of the entire ticket history and conversation flow.",
    )
    async def fullsummary(self, ctx):
        loading_msg = await ctx.reply("⏳ Compiling comprehensive ticket master report...", mention_author=False)

        try:
            messages_history = []
            async for message in ctx.channel.history(limit=150, oldest_first=True):
                if not message.author.bot:
                    messages_history.append(f"{message.author.name}: {message.content}")

            if not messages_history:
                await loading_msg.edit(content="❌ No messages found to summarize.")
                return

            chat_transcript = "\n".join(messages_history)

            prompt = (
                "You are an expert senior server administrator. Review the entire ticket conversation transcript "
                "and generate a comprehensive master summary using clean Markdown bullet points. No tables, no HTML.\n\n"
                "Use this exact structure:\n"
                "• **Overview / Objective:** [What started this ticket and what is the user trying to achieve?]\n"
                "• **Conversation Timeline:** [Key milestones, questions asked, and staff responses in chronological order]\n"
                "• **Technical / Reward Status:** [Current standing of the request]\n"
                "• **Outstanding Tasks:** [What is left to complete before closing the ticket?]\n"
                "• **Final Conclusion:** [Crisp final verdict on the ticket outcome]\n\n"
                f"--- FULL TICKET TRANSCRIPT ---\n{chat_transcript}"
            )

            chat_completion = self.groq_client.chat.completions.create(
                model=self.model_id,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_completion_tokens=2048,
            )

            summary_text = chat_completion.choices[0].message.content

            embed = discord.Embed(
                title="📋 Comprehensive Ticket Master Report",
                description=summary_text,
                color=discord.Color.purple(),
            )
            embed.set_footer(text=f"Requested by {ctx.author.name}")
            
            await loading_msg.delete()
            await ctx.send(embed=embed)

        except Exception as e:
            error_msg = f"❌ **Error in fullsummary command:**\n```python\n{str(e)}\n```"
            await loading_msg.edit(content=error_msg)

async def setup(bot):
    await bot.add_cog(FullSummaryCog(bot))