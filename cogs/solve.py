# cogs/solve.py
import os
import discord
from discord.ext import commands
from groq import Groq

class SolveCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        groq_api_key = os.getenv("GROQ_API_KEY")
        self.groq_client = Groq(api_key=groq_api_key)
        self.model_id = "openai/gpt-oss-120b"

    @commands.command(
        name="solve",
        help="Analyzes the ticket and user problem to provide a step-by-step solution, or asks clarifying questions if info is missing.",
    )
    async def solve(self, ctx):
        loading_msg = await ctx.reply("🧠 Analyzing ticket context and problem parameters...", mention_author=False)

        try:
            messages_history = []
            async for message in ctx.channel.history(limit=150, oldest_first=True):
                content = f"{message.author.name}: {message.content}"
                for embed in message.embeds:
                    if embed.title: content += f" [Embed: {embed.title}]"
                    if embed.description: content += f" [Desc: {embed.description}]"
                    for field in embed.fields: content += f" [{field.name}: {field.value}]"
                messages_history.append(content)

            if not messages_history:
                await loading_msg.edit(content="❌ No history found to analyze.")
                return

            chat_transcript = "\n".join(messages_history)
            category_id = ctx.channel.category_id if ctx.channel.category else 0
            plan_context = "Free Plan (Invite-based - Category: 1505564682482618368)" if str(category_id) == "1505564682482618368" else ("Paid Plan (Category: 1456919500602474651)" if str(category_id) == "1456919500602474651" else "General Support")

            prompt = (
                f"You are an expert lead technical support engineer for NexterCloud hosting ({plan_context}). "
                "Analyze the support ticket conversation. Determine if you have enough information to solve the user's issue.\n\n"
                "CRITICAL INSTRUCTION:\n"
                "1. If critical information or proof is missing (e.g., error codes, server UID, screenshot details, invite proof, account age), "
                "your output MUST list specific, clear **Clarifying Questions** that staff or the user must answer before a final fix can be given.\n"
                "2. If you have enough information, output a professional, easy-to-understand, **Step-by-Step Resolution Guide** tailored to NexterMC hosting systems.\n\n"
                "Format using clean Markdown:\n"
                "### 🛠️ NexterMC Problem Resolution Analyzer\n"
                "• **Hosting Context:** " + plan_context + "\n"
                "• **Identified Problem:** [Summary of user's issue]\n"
                "• **Analysis & Status:** [Ready to Solve / Missing Information]\n"
                "• **Required Clarifying Questions (if info is missing):** [List 1-3 questions for user/staff, or write 'None - Ready to resolve']\n"
                "• **Step-by-Step Solution:** [Clear, bulleted instructions to resolve the issue]\n\n"
                f"--- TICKET TRANSCRIPT ---\n{chat_transcript}"
            )

            chat_completion = self.groq_client.chat.completions.create(
                model=self.model_id,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_completion_tokens=2048,
            )

            embed = discord.Embed(
                title="🧠 NexterMC Interactive Problem Solver",
                description=chat_completion.choices[0].message.content,
                color=discord.Color.gold(),
            )
            embed.set_footer(text=f"Requested by {ctx.author.name} • Interactive Diagnostics")
            await loading_msg.delete()
            await ctx.send(embed=embed)

        except Exception as e:
            await loading_msg.edit(content=f"❌ Error: ```python\n{str(e)}\n```")

async def setup(bot):
    await bot.add_cog(SolveCog(bot))