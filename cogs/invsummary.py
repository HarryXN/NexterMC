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
        help="Audits invite logs, bot commands (-i, -invited, -accage), and event rules to output a precise final invite count.",
    )
    async def invsummary(self, ctx):
        loading_msg = await ctx.reply("⏳ Analyzing invite command outputs, joins/fakes, and event rules...", mention_author=False)

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
                await loading_msg.edit(content="❌ No history found.")
                return

            chat_transcript = "\n".join(messages_history)

            rules_transcript = "Rules channel unreadable."
            rules_channel = self.bot.get_channel(EVENT_RULES_CHANNEL_ID)
            if rules_channel:
                try:
                    r_msgs = []
                    async for r_msg in rules_channel.history(limit=50, oldest_first=True):
                        r_content = r_msg.content
                        for emb in r_msg.embeds:
                            if emb.description: r_content += f"\n{emb.description}"
                        r_msgs.append(r_content)
                    if r_msgs: rules_transcript = "\n".join(r_msgs)
                except Exception:
                    pass

            prompt = (
                "You are an expert NexterMC free-hosting invite and reward auditor (Free Plan Category: 1505564682482618368). "
                "Analyze the Event Rules and Ticket Transcript. Look closely for bot command outputs (like Falcon's -i logs showing Joins, Left, Fakes, Re-joins, "
                "as well as -invited lists and -accage profile checks). Perform a mathematically precise audit. If deductions/penalties exceed joins, "
                "calculate the true negative count.\n\n"
                "Strict format using Markdown bullets:\n"
                "### 🎁 Free Hosting Invite Audit\n"
                "• **Claimed Invites:** [Number claimed by user]\n"
                "• **Bot Tracking Logs:** [Joins, Left, Fakes, Re-joins parsed from bot output]\n"
                "• **Profile & Age Checks (-accage):** [Status of invited accounts, alt or underage flags, missing bios/pfps]\n"
                "• **Deductions & Rule Penalties:** [Exact arithmetic breakdown of rule violations]\n"
                "• **FINAL INVITES COUNT:** [Net total invite count—can be negative if penalties outweigh valid joins]\n"
                "• **Reward Eligibility:** [Met / Not Met with missing requirements]\n"
                "• **Staff Verdict:** [Next definitive action for staff]\n\n"
                f"--- OFFICIAL EVENT RULES ---\n{rules_transcript}\n\n"
                f"--- TRANSCRIPT & BOT LOGS ---\n{chat_transcript}"
            )

            chat_completion = self.groq_client.chat.completions.create(
                model=self.model_id,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_completion_tokens=2048,
            )

            embed = discord.Embed(
                title="🎁 NexterMC Free Plan Invite Audit",
                description=chat_completion.choices[0].message.content,
                color=discord.Color.green(),
            )
            embed.set_footer(text=f"Requested by {ctx.author.name} • Free Plan Verification")
            await loading_msg.delete()
            await ctx.send(embed=embed)

        except Exception as e:
            await loading_msg.edit(content=f"❌ Error: ```python\n{str(e)}\n```")

async def setup(bot):
    await bot.add_cog(InvSummaryCog(bot))