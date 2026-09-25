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
        help="Performs a rigorous invite and reward audit parsing bot command logs, invite stats, profile age checks, and event rules.",
    )
    async def invsummary(self, ctx):
        loading_msg = await ctx.reply("⏳ Parsing event rules, bot command outputs (-i, -invited, -accage), and calculating final invite audit...", mention_author=False)

        try:
            messages_history = []
            async for message in ctx.channel.history(limit=150, oldest_first=True):
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
                await loading_msg.edit(content="❌ No message history found to audit.")
                return

            chat_transcript = "\n".join(messages_history)

            # Fetch Event Rules dynamically
            rules_transcript = "No event rules channel found or accessible."
            rules_channel = self.bot.get_channel(EVENT_RULES_CHANNEL_ID)
            
            if rules_channel:
                try:
                    rules_messages = []
                    async for r_msg in rules_channel.history(limit=50, oldest_first=True):
                        r_content = r_msg.content
                        for r_emb in r_msg.embeds:
                            if r_emb.description:
                                r_content += f"\n{r_emb.description}"
                        rules_messages.append(r_content)
                    if rules_messages:
                        rules_transcript = "\n".join(rules_messages)
                except Exception as e:
                    rules_transcript = f"⚠️ Could not load rules channel: {e}"

            prompt = (
                "You are an elite, highly rigorous reward auditor and security supervisor for NexterMC. "
                "Analyze the official Event Rules and the entire Ticket Transcript. Pay strict attention to bot command usages "
                "(such as -i invite logs showing Joins, Left, Fakes, Rejoins, command outputs for -invited, and -accage checks). "
                "Perform a thorough, bug-proof mathematical audit. If penalties, fakes, leaves, or rule violations drop the total below zero, "
                "you MUST accurately reflect the negative number in the final count.\n\n"
                "Provide a long, professional, and structured report using clean Markdown bullet points. No tables, no HTML.\n\n"
                "Strictly use this layout:\n"
                "### 🎁 Advanced Invite & Reward Audit Report\n"
                "• **Claimed Invites:** [Number claimed by the user in chat]\n"
                "• **Bot Tracking Log Data:** [Detailed breakdown of Joins, Left, Fakes, and Re-joins found in bot command logs like Falcon]\n"
                "• **Account Age & Profile Compliance (-accage checks):** [Analysis of invited user profiles, alt checks, missing bio/pfp status]\n"
                "• **Deductions & Rule Violations:** [Explicit arithmetic breakdown of penalties applied according to event rules]\n"
                "• **FINAL INVITES COUNT:** [The definitive net invite count computed after all rules and deductions—can be negative if penalties exceed valid joins]\n"
                "• **Reward Eligibility Status:** [Fully Met / Not Met, detailing missing evidence or requirements]\n"
                "• **Definitive Staff Action Verdict:** [Precise 1-2 sentence instruction telling staff what action to take next]\n\n"
                f"--- OFFICIAL EVENT RULES ---\n{rules_transcript}\n\n"
                f"--- TICKET TRANSCRIPT & BOT COMMAND LOGS ---\n{chat_transcript}"
            )

            chat_completion = self.groq_client.chat.completions.create(
                model=self.model_id,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_completion_tokens=3072,
            )

            summary_text = chat_completion.choices[0].message.content

            embed = discord.Embed(
                title="🎁 NexterMC Invite Audit & Reward Verification",
                description=summary_text,
                color=discord.Color.green(),
            )
            embed.set_footer(text=f"Requested by {ctx.author.name} • Audited against Rules ID: {EVENT_RULES_CHANNEL_ID}")
            
            await loading_msg.delete()
            await ctx.send(embed=embed)

        except Exception as e:
            error_msg = f"❌ **Error in invsummary command:**\n```python\n{str(e)}\n```"
            await loading_msg.edit(content=error_msg)

async def setup(bot):
    await bot.add_cog(InvSummaryCog(bot))