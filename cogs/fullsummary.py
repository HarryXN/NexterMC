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
        help="Compiles a comprehensive, unlimited-history master report of the entire ticket.",
    )
    async def fullsummary(self, ctx):
        loading_msg = await ctx.reply("⏳ Pulling unlimited channel history and compiling full master report...", mention_author=False)

        try:
            messages_history = []
            # limit=None fetches the entire channel history from the beginning
            async for message in ctx.channel.history(limit=None, oldest_first=True):
                content = f"[{message.created_at.strftime('%Y-%m-%d %H:%M')}] {message.author.name}: {message.content}"
                for embed in message.embeds:
                    if embed.title: content += f" | Title: {embed.title}"
                    if embed.description: content += f" | Desc: {embed.description}"
                    for field in embed.fields: content += f" | {field.name}: {field.value}"
                messages_history.append(content)

            if not messages_history:
                await loading_msg.edit(content="❌ No message history found.")
                return

            chat_transcript = "\n".join(messages_history)
            category_id = ctx.channel.category_id if ctx.channel.category else 0
            plan_context = "Free Plan (Invite-based)" if str(category_id) == "1505564682482618368" else ("Paid Plan" if str(category_id) == "1456919500602474651" else "General")

            prompt = (
                f"You are an elite senior auditor for NexterCloud hosting ({plan_context}). "
                "Analyze the ENTIRE ticket history from the very first message to the last. Do not miss any details, bot commands, or user statements. "
                "Provide an exhaustive, factual, eye-catching, professional master report in Markdown. Zero hallucinations.\n\n"
                "Strict format:\n"
                "### 📋 Full Ticket Master Report\n"
                "• **Hosting Context:** " + plan_context + "\n"
                "• **Ticket Origin & Goal:** [Why was this opened and what did the user want?]\n"
                "• **Chronological Timeline:** [Detailed step-by-step breakdown of how the conversation progressed]\n"
                "• **Bot Interactions & Commands:** [All bot commands executed, outputs, invite logs, or verification statuses]\n"
                "• **Staff & User Contributions:** [What staff handled, what proof/information the user provided]\n"
                "• **Final Resolution Status:** [Definitive outcome or standing point of the ticket]\n\n"
                f"--- FULL UNLIMITED TRANSCRIPT ---\n{chat_transcript}"
            )

            chat_completion = self.groq_client.chat.completions.create(
                model=self.model_id,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_completion_tokens=4096,
            )

            embed = discord.Embed(
                title="📋 NexterMC Complete Master Report",
                description=chat_completion.choices[0].message.content,
                color=discord.Color.purple(),
            )
            embed.set_footer(text=f"Requested by {ctx.author.name} • Full History Scanned")
            await loading_msg.delete()
            await ctx.send(embed=embed)

        except Exception as e:
            await loading_msg.edit(content=f"❌ Error: ```python\n{str(e)}\n```")

async def setup(bot):
    await bot.add_cog(FullSummaryCog(bot))