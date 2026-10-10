# cogs/invsummary.py
"""Ticket-wide invite and event-rule audit."""
from __future__ import annotations

import datetime
import logging
import re

import discord
from discord.ext import commands

from config import (
    AI_COMMAND_COOLDOWN_SECONDS,
    EVENT_RULES_CHANNEL_ID,
    EVENT_RULES_TEXT,
    INVITE_UNDERAGE_ACCOUNT_DAYS,
)
from utils.ai_client import AIConfigError, AIResponseError
from utils.transcript import analyze_transcript, fetch_transcript_lines

log = logging.getLogger("nextermc.invsummary")

_USER_ID_RE = re.compile(r"\d{15,22}")
_INVITED_HEADER_RE = re.compile(r"invited\s+list\s+of\s+([^\n|:]+)", re.IGNORECASE)
_MENTION_RE = re.compile(r"<@!?(\d{15,22})>")
_PAGE_RE = re.compile(r"\bpage\s*(\d+)\s*(?:/|of)\s*(\d+)\b", re.IGNORECASE)

_REPORT_SECTIONS = {
    "claimed invites": "Claimed Invites",
    "verified invited accounts": "Verified Invited Accounts",
    "rule checks": "Rule Checks",
    "deductions": "Deductions",
    "final count": "Final Count",
    "reward decision": "Reward Decision",
    "staff next step": "Staff Next Step",
}


def _parse_report(text: str) -> dict[str, str]:
    """Turn the model's labeled response into clean Discord embed sections."""
    sections: dict[str, list[str]] = {}
    current = None
    for raw in text.replace("```markdown", "").replace("```", "").splitlines():
        line = raw.strip()
        if not line:
            continue
        clean = re.sub(r"^[#*•\-\s]+|[*\s]+$", "", line)
        clean = clean.replace("**", "").strip()
        matched = None
        remainder = ""
        for key, title in _REPORT_SECTIONS.items():
            if clean.casefold() == key or clean.casefold().startswith(key + ":"):
                matched = title
                remainder = clean[len(key):].lstrip(": ").strip()
                break
        if matched:
            current = matched
            sections.setdefault(current, [])
            if remainder:
                sections[current].append(remainder)
        elif current:
            sections[current].append(line)

    parsed = {name: "\n".join(parts).strip() for name, parts in sections.items()}
    if "Rule Checks" in parsed:
        parsed["Rule Checks"] = _format_rule_checks(parsed["Rule Checks"])
    return parsed


def _format_rule_checks(text: str) -> str:
    """Convert Markdown table rows into readable Discord bullets."""
    output = []
    for line in text.splitlines():
        if "|" not in line:
            if line.strip():
                output.append(line.strip())
            continue
        cells = [cell.strip().strip("*") for cell in line.strip().strip("|").split("|")]
        if not cells or all(not cell or re.fullmatch(r"[-: ]+", cell) for cell in cells):
            continue
        if any(word in " ".join(cells).casefold() for word in ("invited user", "account age", "profile picture")):
            continue
        if len(cells) >= 3:
            user = cells[0]
            facts = [cell for cell in cells[1:] if cell and cell.casefold() not in ("unknown", "n/a")]
            output.append(f"• **{user}** — " + " · ".join(facts))
        else:
            output.append("• " + " · ".join(cells))
    return "\n".join(output) or text


def _add_roster_fields(embed: discord.Embed, roster: str) -> None:
    """List accounts staff need to review, while keeping the embed compact."""
    lines = roster.splitlines()
    if not lines or not _MENTION_RE.search(roster):
        embed.add_field(name="👥 ROSTER CHECK", value="No invited accounts were verified.", inline=False)
        return
    categories = (
        ("⚠️ Underage", lambda row: "account under " in row.casefold()),
        ("🖼️ Missing PFP", lambda row: "no profile picture" in row.casefold()),
        ("📝 Bio check (manual)", lambda row: "bio: manual check required" in row.casefold()),
    )
    embed.add_field(name="👥 VERIFIED ROSTER", value=f"{len(lines)} invited account(s) checked.", inline=False)
    for label, predicate in categories:
        users = [_MENTION_RE.search(row).group(0) for row in lines if predicate(row) and _MENTION_RE.search(row)]
        if not users:
            continue
        # Keep mentions legible; split long lists across fields within Discord limits.
        chunks: list[str] = []
        current = ""
        for mention in users:
            addition = f"{', ' if current else ''}{mention}"
            if len(current) + len(addition) > 950:
                chunks.append(current)
                current = mention
            else:
                current += addition
        if current:
            chunks.append(current)
        for index, chunk in enumerate(chunks):
            suffix = f" · {index + 1}/{len(chunks)}" if len(chunks) > 1 else ""
            embed.add_field(name=f"{label} · {len(users)}{suffix}", value=chunk, inline=False)
    embed.add_field(
        name="Bio status",
        value="Discord does not expose other members’ bios to bots; listed bio checks require staff confirmation.",
        inline=False,
    )


def _compact_rule_checks(text: str) -> str:
    """Keep exceptions and unresolved checks; omit routine negative checks."""
    routine_prefixes = (
        "no j4j", "no j2j", "no alt", "no leave", "no fake", "no evidence",
        "no payout", "no server-promo", "no onboarding", "all invited accounts are",
    )
    exceptions = []
    for line in text.splitlines():
        clean = re.sub(r"^[•*\-\s]+", "", line).strip()
        if clean and not clean.casefold().startswith(routine_prefixes):
            exceptions.append(clean)
    return "\n".join(f"• {line}" for line in exceptions[:4]) or "No reset-rule violations identified in the ticket review."


def _progress_embed(title: str, step: int, total: int = 4) -> discord.Embed:
    frames = ("◐", "◓", "◑", "◒")
    filled = round(10 * step / total)
    bar = "▰" * filled + "▱" * (10 - filled)
    return discord.Embed(
        title=f"{frames[(step - 1) % len(frames)]} Invite Reward Audit",
        description=f"`{bar}` **{step}/{total}**\n\n{title}",
        color=discord.Color.gold(),
    )


async def _fetch_live_event_rules(bot: commands.Bot) -> str:
    channel = bot.get_channel(EVENT_RULES_CHANNEL_ID)
    if channel is None:
        try:
            channel = await bot.fetch_channel(EVENT_RULES_CHANNEL_ID)
        except (discord.HTTPException, discord.Forbidden):
            return EVENT_RULES_TEXT

    try:
        messages = [message async for message in channel.history(limit=30, oldest_first=True)]
    except (discord.HTTPException, discord.Forbidden, AttributeError):
        return EVENT_RULES_TEXT
    text = "\n".join(message.content for message in messages if message.content.strip())
    return text or EVENT_RULES_TEXT


async def _resolve_claimant(ctx: commands.Context, query: str) -> discord.Member | None:
    """Resolve a member from a mention, ID, username, nickname, or display name."""
    guild = ctx.guild
    if guild is None:
        return None
    query = query.strip().strip("<@!>")
    if query.isdigit():
        member = guild.get_member(int(query))
        if member is not None:
            return member
        try:
            return await guild.fetch_member(int(query))
        except (discord.NotFound, discord.HTTPException, discord.Forbidden):
            return None

    exact = [m for m in guild.members if query.casefold() in {
        m.name.casefold(), m.display_name.casefold(), str(m).casefold()
    }]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise ValueError("That name matches multiple server members. Use the member's ID or mention.")
    partial = [m for m in guild.members if query.casefold() in m.name.casefold() or query.casefold() in m.display_name.casefold()]
    if len(partial) == 1:
        return partial[0]
    if len(partial) > 1:
        raise ValueError("That name matches multiple server members. Use the member's ID or mention.")
    return None


def _target_matches(text: str, member: discord.Member) -> bool:
    folded = text.casefold()
    if str(member.id) in text or f"<@{member.id}>" in text or f"<@!{member.id}>" in text:
        return True
    return any(name and re.search(rf"(?<!\w){re.escape(name.casefold())}(?!\w)", folded)
               for name in (member.name, member.display_name))


def _extract_invited_roster(lines: list[str], member: discord.Member) -> tuple[list[int], int | None, set[int]]:
    """Collect every roster page present in the ticket and report page coverage."""
    ids: list[int] = []
    total_pages: int | None = None
    seen_pages: set[int] = set()
    for line in lines:
        header = _INVITED_HEADER_RE.search(line)
        if header:
            target_line = _target_matches(header.group(1), member)
        else:
            target_line = bool(re.search(r"\b-invited\b", line, re.IGNORECASE) and _target_matches(line, member))
        if not target_line:
            continue
        page_match = _PAGE_RE.search(line)
        if page_match:
            page_number, page_total = map(int, page_match.groups())
            total_pages = max(total_pages or 0, page_total)
            seen_pages.add(page_number)
        # Discord mentions are the reliable ID format in Falcon's roster embeds.
        matches = _MENTION_RE.findall(line)
        if not matches and ("invited list" in line.casefold() or "embed_field" in line.casefold()):
            matches = _USER_ID_RE.findall(line)
        for raw_id in matches:
            user_id = int(raw_id)
            if user_id != member.id and user_id not in ids:
                ids.append(user_id)
    return ids, total_pages, seen_pages


def _extract_invited_ids(lines: list[str], member: discord.Member) -> list[int]:
    """Compatibility wrapper for callers needing only the deduplicated roster."""
    return _extract_invited_roster(lines, member)[0]


def _extract_falcon_penalty_counts(lines: list[str], member: discord.Member) -> dict[str, int]:
    """Extract target-specific Falcon counters; absent values stay unverified."""
    patterns = {
        "Claimed": re.compile(
            r"\b(?:claimed\s+)?invites?\s*[:=：]\s*(\d+)\b|\bhas\s+(\d+)\s+invites?\b",
            re.IGNORECASE,
        ),
        "Joins": re.compile(r"\bjoins?\s*[:=：]\s*(\d+)\b", re.IGNORECASE),
        "Left": re.compile(r"\bleft\s*[:=：]\s*(\d+)\b", re.IGNORECASE),
        "Rejoins": re.compile(r"\brejoins?\s*[:=：]\s*(\d+)\b", re.IGNORECASE),
        "Fake": re.compile(r"\bfakes?\s*[:=：]\s*(\d+)\b", re.IGNORECASE),
        "Underage": re.compile(r"\bunderage\s*[:=：]\s*(\d+)\b", re.IGNORECASE),
    }
    counts: dict[str, int] = {}
    for line in lines:
        if "falcon" not in line.casefold() or not _target_matches(line, member):
            continue
        for label, pattern in patterns.items():
            match = pattern.search(line)
            if match:
                counts[label] = int(next(group for group in match.groups() if group is not None))
    return counts


def _build_rule_math(
    sections: dict[str, str], roster: str, counters: dict[str, int], *, roster_complete: bool = True
) -> tuple[str, str]:
    """Calculate confirmed deductions locally instead of trusting model arithmetic."""
    claimed_match = re.search(r"\b(-?\d+)\b", sections.get("Claimed Invites", ""))
    claimed = counters.get("Claimed")
    if claimed is None and claimed_match:
        claimed = int(claimed_match.group(1))
    missing_counters = [name for name in ("Joins", "Left", "Rejoins", "Fake") if name not in counters]
    if missing_counters:
        missing = ", ".join(missing_counters)
        return (
            f"⚠️ **Provisional:** missing Falcon counts for {missing}. Missing values are not treated as zero.",
            "Provisional — rerun Falcon `-i` and audit",
        )

    if any("age/avatar/bio need manual review" in row.casefold() for row in roster.splitlines()):
        return (
            "⚠️ **Provisional:** verify invited accounts' age and profile picture before finalizing.",
            "Provisional — account verification required",
        )

    if not roster_complete:
        return (
            "⚠️ **Provisional:** Falcon's invited roster is paginated and not every page was captured. "
            "No final reward count until the complete roster is available.",
            "Provisional — Falcon roster pages missing",
        )

    underage = counters.get(
        "Underage", sum("account under " in row.casefold() for row in roster.splitlines())
    )
    no_picture = sum("no profile picture (no count)" in row.casefold() for row in roster.splitlines())
    joins = counters["Joins"]
    claimed_text = str(claimed) if claimed is not None else "not reported"
    event_violations = sum(counters[label] for label in ("Left", "Rejoins", "Fake"))
    total_deduction = 2 * (event_violations + underage) + no_picture
    final_count = joins - total_deduction
    deductions = (
        f"Joins **{joins}** · claimed **{claimed_text}** (reference)\n"
        f"Leave {counters['Left']} · rejoin {counters['Rejoins']} · fake {counters['Fake']} "
        f"(−2 each) · underage {underage} (−2 each) · no PFP {no_picture} (−1)\n"
        f"**{joins} − {total_deduction} = {final_count}** · bio/onboarding review pending"
    )
    return deductions, f"{final_count} (pending bio/onboarding review)"


async def _describe_invited_account(bot: commands.Bot, guild: discord.Guild, user_id: int) -> tuple[str, bool]:
    member = guild.get_member(user_id)
    user = member
    flags: list[str] = []
    if user is None:
        try:
            user = await bot.fetch_user(user_id)
        except discord.NotFound:
            return f"<@{user_id}> — account unavailable; age/avatar/bio need manual review", False
        except discord.HTTPException:
            return f"<@{user_id}> — couldn't verify with Discord; age/avatar/bio need manual review", False
        flags.append("not currently in server")

    age_days = (datetime.datetime.now(datetime.timezone.utc) - user.created_at).days
    eligible = True
    if age_days < INVITE_UNDERAGE_ACCOUNT_DAYS:
        flags.append(f"account under {INVITE_UNDERAGE_ACCOUNT_DAYS} days (−2 penalty)")
        eligible = False
    if not user.avatar:
        flags.append("no profile picture (no count)")
        eligible = False
    status = "; ".join(flags) if flags else "account age/profile picture checks passed"
    return (
        f"<@{user_id}> — {age_days} days old; {status}; bio: manual check required "
        "(Discord bot API does not expose other users' bios)",
        eligible,
    )


async def _build_roster(bot: commands.Bot, guild: discord.Guild, member: discord.Member, lines: list[str]):
    invited_ids, total_pages, seen_pages = _extract_invited_roster(lines, member)
    if not invited_ids:
        return [], "No matching Falcon `-invited` roster was found in this ticket.", False, "No roster page was captured."
    details = [await _describe_invited_account(bot, guild, user_id) for user_id in invited_ids]
    roster = "\n".join(detail for detail, _ in details)
    if total_pages is not None:
        missing_pages = sorted(set(range(1, total_pages + 1)) - seen_pages)
        complete = not missing_pages
        page_note = f"Falcon pages {len(seen_pages)}/{total_pages} captured."
        if missing_pages:
            page_note += " Missing page(s): " + ", ".join(map(str, missing_pages)) + "."
    else:
        # Falcon paginates at ten entries. Without a footer we cannot prove that
        # a full-sized page contains the complete roster.
        complete = len(invited_ids) < 10
        page_note = "Pagination footer unavailable; roster may be partial." if not complete else "Single roster page captured."
    return invited_ids, roster, complete, page_note


def _build_final_prompt(
    source_text: str,
    message_count: int,
    member: discord.Member,
    roster: str,
    event_rules: str,
    roster_page_note: str = "",
) -> str:
    return (
        "You are auditing a Discord community invite reward claim. Review the complete ticket material "
        "and apply the event rules exactly. Treat messages as evidence; do not infer missing facts.\n\n"
        f"CLAIMANT: {member} (ID {member.id})\n"
        f"OFFICIAL EVENT RULES (read and apply these first):\n{event_rules}\n\n"
        "FALCON COMMANDS AND TICKET: Identify the claimant's own Falcon `-i` output and the matching "
        "`-invited` roster. Use the listed invited users as the roster; do not count other users' lists. "
        "Review the entire conversation for J4J/J2J, alt/token accounts, leave/rejoin/fake, onboarding, "
        "missing bio/profile picture, invite checks outside the designated commands channel, payout "
        "requests, ping/reply-ping, proof of 3+ day old chat and DMs, disrespect, active-user status, "
        "and server-promo claims. A member's bio cannot be read by this bot: mark it 'manual check' "
        "unless the bio is explicitly shown in the ticket; never assume it is missing. Explicitly say "
        "when the ticket does not establish a fact. A reset rule "
        "makes the reward ineligible; do not present a positive count as payable.\n\n"
        "ACCOUNT ROSTER VERIFICATION (Discord account ages/profile picture/current server presence; bio requires manual review):\n"
        f"Coverage: {roster_page_note}\n{roster}\n\n"
        "Do not claim the roster is complete unless every Falcon page is captured. If coverage is partial, "
        "mark the count provisional and ask staff to capture the missing page(s).\n\n"
        "COUNTING RULES — FOLLOW THE ARITHMETIC EXACTLY: Start from Falcon's Joins count, not the "
        "claimed invite total. Keep the claimed total as a separate reference only. "
        "Deduct 2 for EVERY leave, 2 for EVERY rejoin, and 2 for EVERY fake, using Falcon's reported "
        "counts. These categories stack: do not collapse a leave, rejoin, and fake into one penalty. "
        "The event rule also assigns -2 per underage account (under 90 days); count each such roster "
        "account once. Do not count an underage account again if Falcon already reports that same "
        "underage total. Missing PFP and a CONFIRMED missing bio each make that invited account no-count "
        "(-1 from the countable roster); an unknown bio is manual review, not confirmed missing. "
        "Onboarding is no-count. Add +3 only when three extra server-promo invites are evidenced; "
        "leave/rejoin/fake promo invites do not count. Show the arithmetic explicitly, for example: "
        "Left 2 × -2 = -4; Rejoins 1 × -2 = -2; Fake 3 × -2 = -6; total penalty = -12. "
        "If a Falcon count is absent, mark that component unverified and the final count provisional; "
        "never replace missing values with zero or claim there were no violations. Do not use Markdown "
        "tables. Keep each roster check to one concise bullet.\n\n"
        "Return concise professional Markdown with these exact section labels, one per line:\n"
        "Claimed Invites: ...\nVerified Invited Accounts: ...\nRule Checks: ...\nDeductions: ...\n"
        "Final Count: ...\nReward Decision: Eligible / Not eligible / Needs manual review — reason\n"
        "Staff Next Step: ...\n\n"
        f"TICKET TRANSCRIPT ({message_count} messages, chronological):\n{source_text}"
    )


class InvSummaryCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(
        name="inv",
        aliases=["invsummary"],
        help="Audit a member's invite reward claim against the ticket, Falcon roster, and event rules.",
    )
    @commands.cooldown(1, AI_COMMAND_COOLDOWN_SECONDS, commands.BucketType.channel)
    async def invsummary(self, ctx: commands.Context, *, claimant_query: str = ""):
        if not claimant_query:
            await ctx.send("Usage: `,inv <username, user ID, or @member>`")
            return
        if ctx.guild is None:
            await ctx.send("This audit can only run inside a server ticket.")
            return
        try:
            member = await _resolve_claimant(ctx, claimant_query)
        except ValueError as exc:
            await ctx.send(f"⚠️ {exc}")
            return
        if member is None:
            await ctx.send("❌ I couldn't find that member in this server. Try their user ID or mention.")
            return

        progress = await ctx.reply(embed=_progress_embed("Reading the event rules and full ticket history…", 1), mention_author=False)
        try:
            event_rules = await _fetch_live_event_rules(self.bot)
            lines = await fetch_transcript_lines(ctx.channel, limit=None)
            if not lines:
                await progress.edit(embed=discord.Embed(title="No Ticket History", description="There is no channel history to audit.", color=discord.Color.red()))
                return

            await progress.edit(embed=_progress_embed(f"Finding {member.display_name}'s Falcon `-i` and `-invited` results…", 2))
            invited_ids, roster, roster_complete, roster_page_note = await _build_roster(
                self.bot, ctx.guild, member, lines
            )

            await progress.edit(embed=_progress_embed(
                f"Checking {len(invited_ids)} captured invited account(s) · {roster_page_note}", 3
            ))
            falcon_counters = _extract_falcon_penalty_counts(lines, member)
            result = await analyze_transcript(
                lines,
                lambda source, count: _build_final_prompt(
                    source, count, member, roster, event_rules, roster_page_note
                ),
                final_max_tokens=4096,
            )

            await progress.edit(embed=_progress_embed("Preparing the audit summary…", 4))
            sections = _parse_report(result.text)
            rule_math, final_count = _build_rule_math(
                sections, roster, falcon_counters, roster_complete=roster_complete
            )
            sections["Deductions"] = rule_math
            if final_count.startswith("Provisional"):
                decision = "Needs manual review — Falcon counts or the complete invited roster are missing."
            elif "pending bio/onboarding" in final_count:
                decision = "Needs manual review — bio and onboarding status must be confirmed by staff."
            else:
                decision = sections.get("Reward Decision", "Needs manual review — confirm proof and event-rule checks.")
            if "not eligible" in decision.casefold() or "ineligible" in decision.casefold():
                report_color = discord.Color.red()
            elif "eligible" in decision.casefold() and "manual review" not in decision.casefold():
                report_color = discord.Color.green()
            else:
                report_color = discord.Color.orange()
            embed = discord.Embed(
                title=f"🎟️ Invite Audit · {member.display_name}",
                description=(
                    f"**Final count:** {final_count[:180]}\n"
                    f"**Decision:** {decision[:260]}"
                ),
                color=report_color,
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            embed.add_field(
                name="📊 Count basis",
                value=(
                    f"Joins **{falcon_counters.get('Joins', 'not found')}** · claimed **{falcon_counters.get('Claimed', 'not found')}** (reference) · "
                    f"roster **{len(invited_ids)}** · {roster_page_note}"
                ),
                inline=False,
            )
            if sections.get("Deductions"):
                embed.add_field(name="🔻 Deductions", value=sections["Deductions"][:700], inline=False)
            if sections.get("Rule Checks"):
                embed.add_field(name="🧾 Review flags", value=_compact_rule_checks(sections["Rule Checks"])[:700], inline=False)
            if sections.get("Staff Next Step"):
                next_step = re.sub(r"\s+", " ", sections["Staff Next Step"]).strip()
                if not roster_complete:
                    next_step = "Post the missing Falcon roster page(s) as ticket messages, then rerun `,inv`."
                embed.add_field(name="🧭 Staff next step", value=next_step[:300], inline=False)
            elif not roster_complete:
                embed.add_field(
                    name="🧭 Staff next step",
                    value="Post the missing Falcon roster page(s) as ticket messages, then rerun `,inv`.",
                    inline=False,
                )
            _add_roster_fields(embed, roster)
            embed.set_footer(text=f"Ticket messages reviewed: {result.message_count} • Sections: {result.chunks_analyzed} • Requested by {ctx.author}")
            embed.timestamp = datetime.datetime.now(datetime.timezone.utc)
            await progress.edit(embed=embed)
        except AIResponseError as exc:
            await progress.edit(embed=discord.Embed(title="AI Returned No Report", description=str(exc), color=discord.Color.red()))
        except AIConfigError as exc:
            await progress.edit(embed=discord.Embed(title="AI Unavailable", description=str(exc), color=discord.Color.red()))
        except Exception:
            log.exception("invite audit failed in channel %s for member %s", ctx.channel.id, member.id)
            await progress.edit(embed=discord.Embed(title="Audit Failed", description="Something went wrong. The issue has been logged.", color=discord.Color.red()))


async def setup(bot):
    await bot.add_cog(InvSummaryCog(bot))
