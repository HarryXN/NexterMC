"""Average recent public video views for YouTube channels and Instagram profiles."""
from __future__ import annotations

import asyncio
import datetime
import logging
import os
import re
import statistics
import time
from urllib.parse import urlparse

import aiohttp
import discord
from discord.ext import commands

from config import BRAND_NAME

log = logging.getLogger("nextermc.avgviews")
YOUTUBE_API = "https://www.googleapis.com/youtube/v3"
INSTAGRAM_API = "https://graph.facebook.com"
SAMPLE_SIZE = 10
INSTAGRAM_SAMPLE_SIZE = 12
RESERVED_IG_PATHS = {
    "about", "accounts", "api", "challenge", "developer", "direct", "explore",
    "legal", "p", "press", "reel", "reels", "stories", "web",
}


class LookupErrorForUser(Exception):
    """An expected lookup/configuration problem with a safe user-facing message."""


def _parse_profile_url(raw_url: str) -> tuple[str, str]:
    url = raw_url.strip().strip("<>")
    if not url:
        raise LookupErrorForUser("Paste a YouTube channel or Instagram profile URL.")
    if "://" not in url:
        url = "https://" + url

    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    path = parsed.path.strip("/")
    if host in {"youtube.com", "m.youtube.com", "music.youtube.com"}:
        parts = [part for part in path.split("/") if part]
        if not parts:
            raise LookupErrorForUser("That YouTube URL does not identify a channel.")
        if parts[0].startswith("@"):
            return "youtube", parts[0][1:]
        if parts[0] == "channel" and len(parts) > 1:
            return "youtube", parts[1]
        if parts[0] == "user" and len(parts) > 1:
            return "youtube_user", parts[1]
        if parts[0] == "c" and len(parts) > 1:
            return "youtube_search", parts[1]
        raise LookupErrorForUser(
            "Use a channel URL such as `youtube.com/@name` or `youtube.com/channel/UC…`."
        )

    if host in {"instagram.com", "instagr.am"}:
        parts = [part for part in path.split("/") if part]
        if len(parts) != 1 or parts[0].lower() in RESERVED_IG_PATHS:
            raise LookupErrorForUser("Use an Instagram profile URL, not a post, Reel, or story URL.")
        username = parts[0].lstrip("@")
        if not re.fullmatch(r"[A-Za-z0-9._]{1,30}", username):
            raise LookupErrorForUser("That Instagram profile URL does not contain a valid username.")
        return "instagram", username

    raise LookupErrorForUser(
        "I couldn't identify that platform. Paste a `youtube.com` or `instagram.com` profile URL."
    )


async def _get_json(
    session: aiohttp.ClientSession,
    url: str,
    *,
    params: dict[str, str | int],
    headers: dict[str, str] | None = None,
) -> dict:
    try:
        async with session.get(url, params=params, headers=headers) as response:
            payload = await response.json(content_type=None)
            if response.status >= 400:
                detail = payload.get("error", {}) if isinstance(payload, dict) else {}
                api_message = str(detail.get("message", "")) if isinstance(detail, dict) else ""
                log.warning("Social analytics API returned HTTP %s: %s", response.status, api_message[:250])
                if "quota" in api_message.lower():
                    raise LookupErrorForUser("The YouTube API quota is exhausted. Try again after its quota resets.")
                if response.status in (401, 403):
                    raise LookupErrorForUser(
                        "The platform rejected the bot's API credentials or permissions. Check the API setup in `.env`."
                    )
                if response.status == 404:
                    raise LookupErrorForUser("That profile/channel was not found or is not available through the platform API.")
                if response.status == 429:
                    raise LookupErrorForUser("The platform rate-limited this lookup. Please try again later.")
                raise LookupErrorForUser("The platform could not provide data for that profile right now.")
            if not isinstance(payload, dict):
                raise LookupErrorForUser("The platform returned an unreadable response.")
            if payload.get("error"):
                detail = payload["error"]
                api_message = str(detail.get("message", "")) if isinstance(detail, dict) else ""
                log.warning("Social analytics API error: %s", api_message[:250])
                if "quota" in api_message.lower():
                    raise LookupErrorForUser("The YouTube API quota is exhausted. Try again after its quota resets.")
                raise LookupErrorForUser("The platform rejected this lookup. Check the profile URL and API permissions.")
            return payload
    except LookupErrorForUser:
        raise
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
        log.warning("Social analytics request failed (%s)", type(exc).__name__)
        raise LookupErrorForUser("The platform could not be reached. Please try again in a moment.") from exc


async def _youtube_average(
    session: aiohttp.ClientSession,
    channel_ref: str,
    ref_type: str,
    api_key: str,
    progress_callback=None,
) -> dict:
    if not api_key:
        raise LookupErrorForUser(
            "YouTube lookup is not configured yet. Add `YOUTUBE_API_KEY` to the bot's `.env` and restart it."
        )

    channel_params: dict[str, str | int] = {"part": "snippet,statistics,contentDetails", "key": api_key}
    if ref_type == "youtube":
        channel_params["forHandle"] = channel_ref
    elif ref_type == "youtube_user":
        channel_params["forUsername"] = channel_ref
    elif ref_type == "youtube_search":
        search = await _get_json(
            session,
            f"{YOUTUBE_API}/search",
            params={"part": "snippet", "type": "channel", "q": channel_ref, "maxResults": 1, "key": api_key},
        )
        items = search.get("items", [])
        if not items:
            raise LookupErrorForUser("I couldn't find a YouTube channel matching that URL.")
        channel_params["id"] = items[0].get("id", {}).get("channelId", "")
    else:
        channel_params["id"] = channel_ref

    response = await _get_json(session, f"{YOUTUBE_API}/channels", params=channel_params)
    channels = response.get("items", [])
    if not channels:
        raise LookupErrorForUser("I couldn't find that YouTube channel. Check the URL and try again.")
    channel = channels[0]
    snippet = channel.get("snippet", {})
    stats = channel.get("statistics", {})
    uploads_id = channel.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
    if not uploads_id:
        raise LookupErrorForUser("YouTube did not provide a public uploads list for that channel.")

    # Walk the uploads playlist to its end. YouTube's channel totalViewCount is
    # returned separately; reading each upload is necessary for a true average
    # across all public videos instead of treating the latest ten as the whole channel.
    all_views: list[int] = []
    latest_views: list[int] = []
    latest_video_ids: set[str] = set()
    top_video: tuple[int, str] | None = None
    total_upload_ids = 0
    processed_upload_ids = 0
    page_token = None
    page_number = 0
    while True:
        page_params: dict[str, str | int] = {
            "part": "contentDetails",
            "playlistId": uploads_id,
            "maxResults": 50,
            "key": api_key,
        }
        if page_token:
            page_params["pageToken"] = page_token
        playlist = await _get_json(session, f"{YOUTUBE_API}/playlistItems", params=page_params)
        video_ids = [
            str(item.get("contentDetails", {}).get("videoId", ""))
            for item in playlist.get("items", [])
            if item.get("contentDetails", {}).get("videoId")
        ]
        if video_ids:
            if len(latest_video_ids) < SAMPLE_SIZE:
                latest_video_ids.update(video_ids[: SAMPLE_SIZE - len(latest_video_ids)])
            videos = await _get_json(
                session,
                f"{YOUTUBE_API}/videos",
                params={
                    "part": "statistics,snippet",
                    "id": ",".join(video_ids),
                    "maxResults": 50,
                    "key": api_key,
                },
            )
            for video in videos.get("items", []):
                raw_views = video.get("statistics", {}).get("viewCount")
                if raw_views is None:
                    continue
                try:
                    view_count = int(raw_views)
                except (TypeError, ValueError):
                    continue
                all_views.append(view_count)
                if video.get("id") in latest_video_ids:
                    latest_views.append(view_count)
                if top_video is None or view_count > top_video[0]:
                    top_video = (view_count, video.get("snippet", {}).get("title", "Untitled video"))

            total_upload_ids += len(video_ids)
            processed_upload_ids += len(video_ids)
            page_number += 1
            if progress_callback and page_number % 10 == 0:
                await progress_callback(processed_upload_ids, stats.get("videoCount"))

        page_token = playlist.get("nextPageToken")
        if not page_token:
            break

    if not all_views:
        raise LookupErrorForUser("YouTube did not return public view counts for this channel's uploads.")

    handle = snippet.get("customUrl", "")
    channel_url = f"https://www.youtube.com/channel/{channel['id']}"
    if handle.startswith("@"):
        channel_url = f"https://www.youtube.com/{handle}"
    return {
        "platform": "YouTube",
        "name": snippet.get("title", channel_ref),
        "url": channel_url,
        "average": statistics.mean(all_views),
        "median": statistics.median(all_views),
        "sample_count": len(all_views),
        "sample_window": (
            f"All {len(all_views):,} uploads with view data"
            + (f" of {int(stats['videoCount']):,} public videos reported by YouTube" if stats.get("videoCount") is not None else "")
        ),
        "recent_average": statistics.mean(latest_views) if latest_views else None,
        "recent_count": len(latest_views),
        "all_time_views": stats.get("viewCount"),
        "reported_video_count": stats.get("videoCount"),
        "uploads_scanned": total_upload_ids,
        "followers": stats.get("subscriberCount"),
        "top_title": top_video[1] if top_video else "Unavailable",
        "top_views": top_video[0] if top_video else 0,
        "note": (
            "Lifetime views are the channel total reported by YouTube. The average includes every public upload "
            "whose view count is available; private, deleted, or unavailable uploads cannot be checked."
        ),
    }


async def _instagram_average(
    session: aiohttp.ClientSession, username: str, token: str, business_account_id: str, api_version: str
) -> dict:
    if not token or not business_account_id:
        raise LookupErrorForUser(
            "Instagram lookup is not configured yet. Add `INSTAGRAM_ACCESS_TOKEN` and "
            "`INSTAGRAM_BUSINESS_ACCOUNT_ID` to `.env` and restart the bot."
        )
    api_version = api_version.strip().strip("/") or "v25.0"
    if not re.fullmatch(r"v\d+\.\d+", api_version):
        raise LookupErrorForUser("`INSTAGRAM_GRAPH_API_VERSION` must look like `v25.0`.")

    fields = (
        f"business_discovery.username({username}){{username,name,followers_count,"
        f"media_count,media.limit({INSTAGRAM_SAMPLE_SIZE}){{media_type,media_product_type,"
        "timestamp,permalink,view_count}}}"
    )
    payload = await _get_json(
        session,
        f"{INSTAGRAM_API}/{api_version}/{business_account_id}",
        params={"fields": fields},
        headers={"Authorization": f"Bearer {token}"},
    )
    profile = payload.get("business_discovery")
    if not isinstance(profile, dict):
        raise LookupErrorForUser(
            "Instagram did not return that profile. The target may be private/personal, or unavailable to Business Discovery."
        )
    reels = []
    for post in profile.get("media", {}).get("data", []):
        kind = str(post.get("media_product_type", "")).upper()
        media_type = str(post.get("media_type", "")).upper()
        raw_views = post.get("view_count")
        if kind == "REELS" or media_type == "VIDEO":
            if raw_views is not None:
                try:
                    reels.append((int(raw_views), post.get("permalink", "")))
                except (TypeError, ValueError):
                    continue
    if not reels:
        raise LookupErrorForUser(
            "Instagram returned no recent Reel/video view counts for this profile. "
            "It may have no public Reels, or the account/API access may not support Business Discovery."
        )

    return {
        "platform": "Instagram",
        "name": profile.get("name") or profile.get("username") or username,
        "url": f"https://www.instagram.com/{profile.get('username', username)}/",
        "average": statistics.mean(value for value, _ in reels),
        "median": statistics.median(value for value, _ in reels),
        "sample_count": len(reels),
        "sample_window": f"Latest {INSTAGRAM_SAMPLE_SIZE} public posts checked; {len(reels)} Reels/videos counted",
        "followers": profile.get("followers_count"),
        "top_title": "Recent Reel/video",
        "top_views": max(value for value, _ in reels),
        "note": "Photos/carousels without a video are excluded; only posts with a public view count are averaged.",
    }


def _format_count(value) -> str:
    if value is None:
        return "Not public"
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "Not public"


def _result_embed(result: dict, elapsed: float) -> discord.Embed:
    if result["platform"] == "YouTube":
        headline = (
            f"Average across **all {result['sample_count']:,} public uploads with view data:** "
            f"**{_format_count(round(result['average']))} views per video**"
        )
    else:
        headline = (
            f"Average across **{result['sample_count']:,}** recent videos: "
            f"**{_format_count(round(result['average']))} views**"
        )
    embed = discord.Embed(
        title=f"📊 {result['platform']} Average Views",
        description=f"**[{discord.utils.escape_markdown(result['name'])}]({result['url']})**\n{headline}",
        color=discord.Color.from_rgb(88, 101, 242) if result["platform"] == "YouTube" else discord.Color.from_rgb(225, 48, 108),
        timestamp=datetime.datetime.now(datetime.timezone.utc),
    )
    embed.add_field(name="📈 Average views", value=f"`{_format_count(round(result['average']))}`", inline=True)
    embed.add_field(name="〰️ Median views", value=f"`{_format_count(round(result['median']))}`", inline=True)
    embed.add_field(name="👥 Followers / subscribers", value=f"`{_format_count(result['followers'])}`", inline=True)
    if result["platform"] == "YouTube":
        embed.add_field(name="🌐 Channel lifetime views", value=f"`{_format_count(result['all_time_views'])}`", inline=True)
        embed.add_field(
            name="🆕 Latest 10 average",
            value=f"`{_format_count(round(result['recent_average']))}` across {result['recent_count']} uploads"
            if result["recent_average"] is not None else "No recent view counts available",
            inline=True,
        )
    embed.add_field(name="🔎 Sample", value=result["sample_window"], inline=False)
    embed.add_field(name="🏆 Highest in sample", value=f"`{_format_count(result['top_views'])}` — {discord.utils.escape_markdown(result['top_title'])[:180]}", inline=False)
    embed.add_field(name="ℹ️ Notes", value=result["note"], inline=False)
    embed.set_footer(text=f"{BRAND_NAME} Creator Analytics • public data • completed in {elapsed:.1f}s")
    return embed


class AverageViews(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(name="avgviews", aliases=["averageviews", "viewsavg"])
    @commands.cooldown(1, 15, commands.BucketType.user)
    async def avgviews(self, ctx: commands.Context, *, profile_url: str):
        """Estimate average views from a channel/profile's recent public videos."""
        try:
            platform, profile_ref = _parse_profile_url(profile_url)
        except LookupErrorForUser as exc:
            await ctx.send(f"⚠️ {exc}", delete_after=12)
            return

        status = discord.Embed(
            title="🔎 Creator Analytics",
            description=(
                "Reading the complete public upload history and collecting view counts…"
                if platform.startswith("youtube")
                else f"Reviewing recent public uploads for {platform.title()}…"
            ),
            color=discord.Color.blurple(),
        )
        status.set_footer(text="Fetching public video statistics; large channels may take longer")
        message = await ctx.send(embed=status)
        started = time.monotonic()
        timeout = aiohttp.ClientTimeout(total=20, connect=8)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                if platform.startswith("youtube"):
                    async def show_progress(processed: int, expected):
                        progress = discord.Embed(
                            title="🔎 Creator Analytics",
                            description=f"Checked **{processed:,}** public uploads so far"
                            + (f" of **{int(expected):,}** reported videos…" if expected is not None else "…"),
                            color=discord.Color.blurple(),
                        )
                        progress.set_footer(text="Still paging through the channel's upload history")
                        await message.edit(embed=progress)

                    result = await _youtube_average(
                        session, profile_ref, platform,
                        os.getenv("YOUTUBE_API_KEY", "").strip(),
                        progress_callback=show_progress,
                    )
                else:
                    result = await _instagram_average(
                        session,
                        profile_ref,
                        os.getenv("INSTAGRAM_ACCESS_TOKEN", "").strip(),
                        os.getenv("INSTAGRAM_BUSINESS_ACCOUNT_ID", "").strip(),
                        os.getenv("INSTAGRAM_GRAPH_API_VERSION", "v25.0"),
                    )
            await message.edit(embed=_result_embed(result, time.monotonic() - started))
        except LookupErrorForUser as exc:
            failure = discord.Embed(
                title="⚠️ Could not calculate average views",
                description=str(exc),
                color=discord.Color.orange(),
            )
            failure.set_footer(text="No view count was guessed or estimated")
            await message.edit(embed=failure)
        except Exception:
            log.exception("Unexpected average-views failure (platform=%s)", platform)
            failure = discord.Embed(
                title="❌ Analytics lookup failed",
                description="An unexpected error occurred. It has been recorded in the bot logs.",
                color=discord.Color.red(),
            )
            await message.edit(embed=failure)


async def setup(bot: commands.Bot):
    await bot.add_cog(AverageViews(bot))
