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
        help="Provides a short, highly accurate general ticket summary.",
    )
    async def summarize(self, ctx):
        loading_msg = await ctx.reply("⏳ Generating precise ticket overview...", mention_author=False)

        try:
            messages_history = []
            async for message in ctx.channel.history(limit=100, oldest_first=True):
                content = f"{message.author.name}: {message.content}"
                for embed in message.embeds:
                    if embed.title: content += f" [Embed: {embed.title}]"
                    if embed.description: content += f" [Desc: {embed.description}]"
                    for field in embed.fields: content += f" [{field.name}: {field.value}]"
                messages_history.append(content)

            if not messages_history:
                await loading_msg.edit(content="❌ No message history found.")
                return

            chat_transcript = "\n".join(messages_history)
            category_name = ctx.channel.category.name if ctx.channel.category else "Uncategorized"
            category_id = ctx.channel.category_id if ctx.channel.category else 0

            context_type = "Free Hosting (Invite-based)" if str(category_id) == "1505564682482618368" else ("Paid Hosting Plan" if str(category_id) == "1456919500602474651" else "General Support")

            prompt = (
                f"You are an expert support supervisor for NexterCloud hosting ({context_type}). "
                "Analyze the ticket transcript and write a SHORT, crisp, and laser-accurate summary using Markdown.\n\n"
                "Strict format:\n"
                "### 📌 Ticket Overview\n"
                "• **Plan Type:** " + context_type + "\n"
                "• **Core Issue:** [1 sentence on the main problem]\n"
                "• **Actions Performed:** [Key troubleshooting or steps taken]\n"
                "• **Status:** [Active / Resolved / Awaiting User Response]\n\n"
                f"--- TRANSCRIPT ---\n{chat_transcript}"
            )

            chat_completion = self.groq_client.chat.completions.create(
                model=self.model_id,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_completion_tokens=1024,
            )

            embed = discord.Embed(
                title="✨ General Ticket Summary",
                description=chat_completion.choices[0].message.content,
                color=discord.Color.blue(),
            )
            embed.set_footer(text=f"Requested by {ctx.author.name} • NexterMC Hosting")
            await loading_msg.delete()
            await ctx.send(embed=embed)

        except Exception as e:
            await loading_msg.edit(content=f"❌ Error: ```python\n{str(e)}\n```")

async def setup(bot):
    await bot.add_cog(SummaryCog(bot))