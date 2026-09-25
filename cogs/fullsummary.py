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
        help="Compiles an exhaustive master report of long-term tickets with unlimited history scanning.",
    )
    async def fullsummary(self, ctx):
        loading_msg = await ctx.reply("⏳ Scanning full long-term ticket history (unlimited depth)...", mention_author=False)

        try:
            messages_history = []
            # limit=None pulls the entire history from message 1 to the end, safely paginated by Discord.py
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

            # If the ticket is exceptionally long (e.g., thousands of lines), we chunk or fit it into the prompt safely
            chat_transcript = "\n".join(messages_history)
            
            # If transcript is massively long, inform user we are processing heavy data
            if len(messages_history) > 300:
                await loading_msg.edit(content=f"🧠 Processing massive long-term ticket ({len(messages_history)} messages)... Generating master report...")

            category_id = ctx.channel.category_id if ctx.channel.category else 0
            plan_context = "Free Cloud Hosting (Invite-based)" if str(category_id) == "1505564682482618368" else ("Paid Cloud Hosting Plan" if str(category_id) == "1456919500602474651" else "General Support")

            prompt = (
                f"You are an elite senior auditor for NexterCloud hosting ({plan_context}). "
                "Analyze the ENTIRE long-term ticket history provided from start to finish, no matter how long it is. "
                "Do not miss any key developments, recurring issues, bot commands, user claims, or staff directions across time. "
                "Provide an exhaustive, highly detailed, factual, and professional master report in Markdown.\n\n"
                "Strict format:\n"
                "### 📋 Full Long-Term Ticket Master Report\n"
                "• **Hosting Context:** " + plan_context + "\n"
                "• **Ticket Origin & Initial Goal:** [Why was this long-term ticket originally opened?]\n"
                "• **Chronological Progression & Milestones:** [Detailed timeline breakdown of how the case evolved over days/weeks]\n"
                "• **Bot Interactions & Commands History:** [All bot commands executed, invite logs, verifications, or error outputs across time]\n"
                "• **Staff & User Contributions:** [Key actions taken by staff and proofs provided by the user]\n"
                "• **Current Standing & Final Resolution Status:** [Where the ticket stands right now or its final conclusion]\n\n"
                f"--- COMPLETE UNLIMITED TRANSCRIPT ---\n{chat_transcript}"
            )

            chat_completion = self.groq_client.chat.completions.create(
                model=self.model_id,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_completion_tokens=4096,
            )

            summary_text = chat_completion.choices[0].message.content

            # Handle Discord embed character limits safely (split or cap gracefully)
            if len(summary_text) > 4000:
                summary_text = summary_text[:3997] + "..."

            embed = discord.Embed(
                title="📋 NexterCloud Long-Term Master Report",
                description=summary_text,
                color=discord.Color.purple(),
            )
            embed.set_footer(text=f"Requested by {ctx.author.name} • {len(messages_history)} Messages Scanned")
            
            await loading_msg.delete()
            await ctx.send(embed=embed)

        except Exception as e:
            error_details = f"❌ **Error generating fullsummary for long-term ticket:**\n```python\n{str(e)}\n```"
            await loading_msg.edit(content=error_details)

async def setup(bot):
    await bot.add_cog(FullSummaryCog(bot))