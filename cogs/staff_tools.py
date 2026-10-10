"""Staff roster, ticket activity, role tenure, and profile reports."""
from __future__ import annotations

import datetime
import logging
from collections import Counter

import discord
from discord.ext import commands

from config import CATEGORY_FREE_ID, CATEGORY_PAID_ID
from permissions import has_permissions_or_owner
from utils.staff_tracking import (
    get_profile_activity,
    get_role_assignments,
    get_tracking_start,
    init_staff_tracking,
    record_role_change,
    record_staff_message,
)

log = logging.getLogger("nextermc.staff_tools")
STAFF_ROLES = {
    1395064815428309066: "Trainee",
    1538892615552868403: "Helper",
    1469259811186278597: "Moderator",
    1485114830313754694: "Senior Moderator",
}
STAFF_TEAM_ROLE_ID = 1525300305246425240
STAFF_ROLE_IDS = set(STAFF_ROLES) | {STAFF_TEAM_ROLE_ID}
ROSTER_GROUPS = (
    ("Trainees", (1395064815428309066,)),
    ("Moderators", (1469259811186278597, 1485114830313754694)),
    ("Helpers", (1538892615552868403,)),
)

_IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
_MANUAL_STAFF_SINCE = {
    "histopuran": datetime.datetime(2026, 8, 20, 20, 31, tzinfo=_IST),
    "keshav": datetime.datetime(2026, 9, 12, 23, 7, tzinfo=_IST),
    "streamers": datetime.datetime(2026, 9, 17, 21, 17, tzinfo=_IST),
    "doordie": datetime.datetime(2026, 9, 26, 15, 13, tzinfo=_IST),
    "realninja": datetime.datetime(2026, 10, 1, 17, 39, tzinfo=_IST),
}
_NO_ROSTER_DATE_ALIASES = ("harry", "mafia")


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _iso_dt(value: str | None) -> datetime.datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.datetime.fromisoformat(value)
        return parsed.replace(tzinfo=datetime.timezone.utc) if parsed.tzinfo is None else parsed
    except ValueError:
        return None


def _relative(value: datetime.datetime | None) -> str:
    return f"<t:{int(value.timestamp())}:R>" if value else "Not tracked"


def _has_staff_role(member: discord.Member) -> bool:
    return any(role.id in STAFF_ROLE_IDS for role in member.roles)


def _manual_staff_since(member: discord.Member) -> datetime.datetime | None:
    names = (member.display_name, member.name, getattr(member, "global_name", None) or "")
    normalized = ["".join(char for char in name.casefold() if char.isalnum()) for name in names]
    for alias, date in _MANUAL_STAFF_SINCE.items():
        if any(alias in name for name in normalized):
            return date
    return None


def _roster_date_suppressed(member: discord.Member) -> bool:
    names = (member.display_name, member.name, getattr(member, "global_name", None) or "")
    normalized = ["".join(char for char in name.casefold() if char.isalnum()) for name in names]
    return any(alias in name for alias in _NO_ROSTER_DATE_ALIASES for name in normalized)


def _is_ticket_channel(channel: discord.abc.GuildChannel) -> bool:
    parent = getattr(channel, "parent", None) or channel
    name = " ".join((getattr(channel, "name", ""), getattr(parent, "name", ""))).casefold()
    category = getattr(parent, "category", None)
    category_name = getattr(category, "name", "").casefold()
    return (
        getattr(parent, "category_id", None) in {CATEGORY_FREE_ID, CATEGORY_PAID_ID}
        or "ticket" in name
        or "ticket" in category_name
        or "support" in category_name
    )


def _split_field_rows(rows: list[str], limit: int = 1000) -> list[str]:
    """Split roster rows safely under Discord's per-field character limit."""
    fields: list[str] = []
    current: list[str] = []
    length = 0
    for row in rows:
        addition_length = len(row) + (1 if current else 0)
        if current and length + addition_length > limit:
            fields.append("\n".join(current))
            current = []
            length = 0
        current.append(row)
        length += len(row) + (1 if len(current) > 1 else 0)
    if current:
        fields.append("\n".join(current))
    return fields


class StaffToolsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if before.guild.id != after.guild.id:
            return
        old = {role.id for role in before.roles}
        new = {role.id for role in after.roles}
        changed = [(role_id, True) for role_id in new - old if role_id in STAFF_ROLE_IDS]
        changed += [(role_id, False) for role_id in old - new if role_id in STAFF_ROLE_IDS]
        if not changed:
            return
        now = _utc_now().isoformat()
        for role_id, added in changed:
            await record_role_change(after.guild.id, after.id, role_id, added, now)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.guild is None or message.author.bot or not isinstance(message.author, discord.Member):
            return
        if not _has_staff_role(message.author):
            return
        when = message.created_at.astimezone(datetime.timezone.utc)
        try:
            await record_staff_message(
                message.guild.id, message.author.id, when.date().isoformat(),
                message.channel.id, _is_ticket_channel(message.channel), when.isoformat(),
            )
        except Exception:
            log.exception("Could not record staff message metadata")

    @commands.hybrid_command(name="staffcheck")
    @has_permissions_or_owner(administrator=True)
    async def staff_check(self, ctx: commands.Context):
        if ctx.guild is None:
            await ctx.send("Run this in the server whose staff roster you want to check.")
            return
        try:
            assignments = await get_role_assignments(ctx.guild.id)
            embed = discord.Embed(
                title="👥 NexterCloud · Staff Team",
                description="Current team roster · one entry per person · staff dates shown in your local Discord time.",
                color=discord.Color.from_rgb(75, 112, 235),
                timestamp=_utc_now(),
            )
            members = ctx.guild.members
            if not members:
                try:
                    await ctx.guild.chunk(cache=True)
                    members = ctx.guild.members
                except discord.HTTPException:
                    pass
            humans = [member for member in members if not member.bot]
            assigned_group: dict[int, str] = {}
            # Keep multi-role people in one group only, preferring their senior role.
            for member in humans:
                member_role_ids = {role.id for role in member.roles}
                if any(role_id in member_role_ids for role_id in (1469259811186278597, 1485114830313754694)):
                    assigned_group[member.id] = "Moderators"
                elif 1538892615552868403 in member_role_ids:
                    assigned_group[member.id] = "Helpers"
                elif 1395064815428309066 in member_role_ids:
                    assigned_group[member.id] = "Trainees"

            unique_members = {member.id: member for member in humans if member.id in assigned_group}
            for title, role_ids in ROSTER_GROUPS:
                matched = [member for member in unique_members.values() if assigned_group.get(member.id) == title]
                rows = []
                for member in sorted(matched, key=lambda item: item.display_name.casefold()):
                    since = None if _roster_date_suppressed(member) else _manual_staff_since(member)
                    if since is None and not _roster_date_suppressed(member):
                        for role_id in role_ids:
                            tracked = _iso_dt(assignments.get((member.id, role_id)))
                            if tracked is not None:
                                since = tracked
                                break
                    date_text = f" · since <t:{int(since.timestamp())}:f>" if since else ""
                    rows.append(f"• {member.mention}{date_text}")
                values = _split_field_rows(rows) if rows else ["No current members."]
                for part, value in enumerate(values, start=1):
                    suffix = f" · {part}" if len(values) > 1 else ""
                    embed.add_field(name=f"{title} · {len(matched)}{suffix}", value=value, inline=False)
            embed.set_footer(text=f"{len(unique_members)} unique human staff · Bots excluded · Dates are tracked from setup onward")
            await ctx.send(embed=embed)
        except Exception:
            log.exception("Staff roster report failed in guild %s", ctx.guild.id)
            await ctx.send("Could not build the staff roster. The issue was logged.")

    @commands.hybrid_command(name="staffactivity")
    @has_permissions_or_owner(administrator=True)
    async def staff_activity(self, ctx: commands.Context):
        if ctx.guild is None:
            await ctx.send("Run this in the server whose ticket activity you want to review.")
            return
        try:
            now = _utc_now()
            midnight = datetime.datetime.combine(now.date(), datetime.time.min, tzinfo=datetime.timezone.utc)
            bot_member = ctx.guild.me
            channels = [channel for channel in ctx.guild.text_channels if _is_ticket_channel(channel)]
            channels.extend(thread for thread in getattr(ctx.guild, "threads", []) if _is_ticket_channel(thread))
            counts: Counter[int] = Counter()
            inaccessible = 0
            progress = await ctx.reply(
                embed=discord.Embed(
                    title="📈 NexterCloud · Staff Ticket Activity",
                    description=f"⏳ Scanning **{len(channels)}** accessible ticket channels for messages since UTC midnight…",
                    color=discord.Color.blurple(),
                ),
                mention_author=False,
            )
            for index, channel in enumerate(channels, start=1):
                permissions = channel.permissions_for(bot_member) if bot_member else None
                if permissions is None or not permissions.read_message_history:
                    inaccessible += 1
                    continue
                try:
                    async for message in channel.history(limit=None, after=midnight, oldest_first=True):
                        invocation = ctx.message
                        if (invocation is not None and message.id == invocation.id) or message.author.bot:
                            continue
                        author = message.author
                        if isinstance(author, discord.Member) and _has_staff_role(author):
                            counts[author.id] += 1
                except (discord.Forbidden, discord.HTTPException):
                    inaccessible += 1
                if index % 8 == 0:
                    await progress.edit(
                        embed=discord.Embed(
                            title="📈 NexterCloud · Staff Ticket Activity",
                            description=f"⏳ Scanned **{index}/{len(channels)}** ticket channels…",
                            color=discord.Color.blurple(),
                        )
                    )
            started = _iso_dt(await get_tracking_start())
            rows = []
            ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
            for index, (user_id, count) in enumerate(ranked, 1):
                member = ctx.guild.get_member(user_id)
                if member is None or not _has_staff_role(member):
                    continue
                rows.append(f"**{index}.** {member.mention} · **{count}** ticket messages")
            embed = discord.Embed(
                title="📈 NexterCloud · Staff Ticket Activity",
                description=("\n".join(rows[:20]) if rows else "No tracked staff ticket messages today.")
                + "\n\nCounts cover messages since UTC midnight in accessible ticket channels and active ticket threads."
                + (f"\n⚠️ Could not read history in **{inaccessible}** channel(s); totals may be incomplete." if inaccessible else ""),
                color=discord.Color.teal(),
                timestamp=now,
            )
            embed.set_footer(text=f"Today UTC · Metadata tracking began {_relative(started)} · Message contents are not saved")
            await progress.edit(content="", embed=embed)
        except Exception:
            log.exception("Staff activity report failed in guild %s", ctx.guild.id)
            await ctx.send("Could not build the staff activity report. The issue was logged.")

    @commands.hybrid_command(name="staffinfo")
    @has_permissions_or_owner(administrator=True)
    async def staff_info(self, ctx: commands.Context, member: discord.Member):
        if ctx.guild is None:
            await ctx.send("Run this inside the server.")
            return
        try:
            roles = [role for role in member.roles if role.id in STAFF_ROLE_IDS]
            if not roles:
                await ctx.send(f"{member.mention} does not currently hold one of the configured staff roles.")
                return
            assignments = await get_role_assignments(ctx.guild.id)
            activity = await get_profile_activity(ctx.guild.id, member.id, _utc_now().date().isoformat())
            created = int(member.created_at.timestamp())
            joined = int(member.joined_at.timestamp()) if member.joined_at else None
            description = (
                f"👤 {member.mention}\n"
                f"🗓️ Account created <t:{created}:F> · joined server "
                + (f"<t:{joined}:F>" if joined else "date unavailable")
                + f"\n🛡️ Current staff role{'s' if len(roles) != 1 else ''}: "
                + ", ".join(role.name for role in roles)
            )
            embed = discord.Embed(
                title="🧾 NexterCloud · Staff Profile",
                description=description,
                color=discord.Color.from_rgb(75, 112, 235),
                timestamp=_utc_now(),
            )
            tenure_rows = []
            for role in roles:
                assigned = _iso_dt(assignments.get((member.id, role.id)))
                tenure_rows.append(f"• **{role.name}:** " + (f"<t:{int(assigned.timestamp())}:F>" if assigned else "Not tracked before setup"))
            embed.add_field(name="📌 Staff tenure", value="\n".join(tenure_rows), inline=False)
            last_at = _iso_dt(activity.get("last_at"))
            channel_id = activity.get("last_channel")
            last_message = f"{_relative(last_at)} in <#{channel_id}>" if last_at and channel_id else "No message tracked yet"
            embed.add_field(name="💬 Activity today (UTC)", value=f"Ticket messages: **{activity['today_tickets']}** · All-channel messages: **{activity['today_total']}**", inline=True)
            embed.add_field(name="🕘 Last tracked message", value=last_message, inline=True)
            embed.add_field(name="ℹ️ Presence", value="Discord last-seen status is not exposed to this bot; message activity is shown instead.", inline=False)
            embed.set_thumbnail(url=member.display_avatar.url)
            embed.set_footer(text="Message content is not stored · Historical staff dates begin at tracking setup")
            await ctx.send(embed=embed)
        except Exception:
            log.exception("Staff profile report failed for user %s", member.id)
            await ctx.send("Could not build the staff profile. The issue was logged.")


async def setup(bot: commands.Bot):
    await init_staff_tracking()
    await bot.add_cog(StaffToolsCog(bot))
