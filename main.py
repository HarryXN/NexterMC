import os
import discord
from discord.ext import commands
from dotenv import load_dotenv
from google import genai

load_dotenv()

# Initialize Gemini Client
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
ai_client = genai.Client(api_key=GEMINI_API_KEY)
MODEL_ID = "gemini-2.5-flash"

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix=",", intents=intents, help_command=None)

TOKEN = os.getenv("DISCORD_TOKEN")

# Dictionary to store invites per guild for the Invite Auditor
invite_cache = {}


async def load_cogs():
  cog_folder = "./cogs"
  if not os.path.exists(cog_folder):
    print(f"Directory {cog_folder} not found!")
    return

  for filename in os.listdir(cog_folder):
    if filename.endswith(".py"):
      module_path = f"cogs.{filename[:-3]}"
      try:
        await bot.load_extension(module_path)
        print(f"Loaded extension: {module_path}")
      except Exception as e:
        print(f"Failed to load {module_path}: {e}")


@bot.event
async def on_ready():
  activity = discord.Activity(
      type=discord.ActivityType.playing, name="NexterMC Moderation"
  )
  await bot.change_presence(activity=activity)

  # Populate cache with active invites for each guild on startup
  for guild in bot.guilds:
    try:
      invites = await guild.invites()
      invite_cache[guild.id] = {invite.code: invite.uses for invite in invites}
    except discord.Forbidden:
      print(f"Missing permissions to fetch invites in guild: {guild.name}")

  print(f"Logged in as {bot.user} ({bot.user.id})")
  print("Bot is ready and running!")


# ==========================================
# 1. ACCURATE INVITE AUDITOR
# ==========================================
@bot.event
async def on_member_join(member: discord.Member):
  guild = member.guild
  if guild.id not in invite_cache:
    return

  old_invites = invite_cache[guild.id]

  try:
    new_invites = await guild.invites()
  except discord.Forbidden:
    return

  used_invite = None
  for new_invite in new_invites:
    code = new_invite.code
    uses = new_invite.uses
    if code in old_invites:
      if uses > old_invites[code]:
        used_invite = new_invite
        break
    elif uses > 0:
      used_invite = new_invite
      break

  invite_cache[guild.id] = {invite.code: invite.uses for invite in new_invites}

  target_channel = guild.system_channel
  if not target_channel:
    for channel in guild.text_channels:
      if channel.permissions_for(guild.me).send_messages:
        target_channel = channel
        break

  if target_channel:
    if used_invite:
      desc = (
          f"**{member.mention}** has joined the server.\n"
          f"🔗 **Invited by:**"
          f" {used_invite.inviter.mention if used_invite.inviter else 'Unknown'}\n"
          f"📌 **Invite Code:** `{used_invite.code}` (Total Uses:"
          f" `{used_invite.uses}`)"
      )
    else:
      desc = (
          f"**{member.mention}** has joined the server, but the specific invite"
          " link couldn't be tracked."
      )

    embed = discord.Embed(
        title="📥 New Member Joined",
        description=desc,
        color=discord.Color.green(),
    )
    await target_channel.send(embed=embed)


@bot.event
async def on_invite_create(invite):
  if invite.guild.id in invite_cache:
    invite_cache[invite.guild.id][invite.code] = invite.uses


@bot.event
async def on_invite_delete(invite):
  if invite.guild.id in invite_cache:
    invite_cache[invite.guild.id].pop(invite.code, None)


# ==========================================
# 2. GEMINI AI TICKET SUMMARIZER COMMAND
# ==========================================
@bot.command(
    name="summarize",
    help="Summarizes the current ticket channel using Gemini AI.",
)
@commands.has_permissions(manage_channels=True)
async def summarize(ctx):
  await ctx.send("⏳ Fetching channel messages and generating AI summary...")

  messages_history = []
  async for message in ctx.channel.history(limit=100, oldest_first=True):
    if not message.author.bot:
      messages_history.append(f"{message.author.name}: {message.content}")

  if not messages_history:
    await ctx.send("❌ No user messages found in this channel to summarize.")
    return

  chat_transcript = "\n".join(messages_history)

  prompt = (
      "You are an expert support supervisor. Read the following support ticket"
      " transcript and provide a concise executive summary covering:\n1."
      " **User Issue / Core Problem**\n2. **Troubleshooting Steps Taken**\n3."
      " **Resolution Status (Resolved/Pending)**\n\nTranscript:\n"
      f"{chat_transcript}"
  )

  try:
    response = ai_client.models.generate_content(
        model=MODEL_ID,
        contents=prompt,
    )

    summary_text = response.text

    embed = discord.Embed(
        title="🤖 AI Ticket Summary",
        description=summary_text,
        color=discord.Color.blue(),
    )
    embed.set_footer(text=f"Requested by {ctx.author.name}")
    await ctx.send(embed=embed)

  except Exception as e:
    await ctx.send(f"❌ Failed to generate AI summary: `{e}`")


@bot.event
async def setup_hook():
  await load_cogs()


if __name__ == "__main__":
  if not TOKEN:
    print("ERROR: DISCORD_TOKEN environment variable is missing!")
  else:
    bot.run(TOKEN)