# config.py
"""
Central configuration for the NexterMC bot.
"""
from __future__ import annotations

import os


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _int_list_env(name: str) -> list[int]:
    raw = os.getenv(name)
    if not raw:
        return []
    out = []
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            out.append(int(part))
    return out


OWNER_ID = _int_env("OWNER_ID", 1006250810142883851)
STAFF_ROLE_IDS = _int_list_env("STAFF_ROLE_IDS")
# This role is intentionally limited to ticket summaries only.
SUMMARY_ONLY_ROLE_ID = _int_env("SUMMARY_ONLY_ROLE_ID", 1525300305246425240)

CATEGORY_FREE_ID = _int_env("CATEGORY_FREE_ID", 1505564682482618368)
CATEGORY_PAID_ID = _int_env("CATEGORY_PAID_ID", 1456919500602474651)

PLAN_CONTEXT_MAP = {
    CATEGORY_FREE_ID: "Free Cloud Hosting (Invite-based)",
    CATEGORY_PAID_ID: "Paid Cloud Hosting Plan",
}
DEFAULT_PLAN_CONTEXT = "General Support"


def plan_context_for_category(category_id) -> str:
    try:
        category_id = int(category_id) if category_id is not None else None
    except (TypeError, ValueError):
        category_id = None
    return PLAN_CONTEXT_MAP.get(category_id, DEFAULT_PLAN_CONTEXT)


EVENT_RULES_CHANNEL_ID = _int_env("EVENT_RULES_CHANNEL_ID", 1419933431399452753)
CRASH_LOG_CHANNEL_ID = _int_env("CRASH_LOG_CHANNEL_ID", 1551741192830718044)

# Pterodactyl client API. Keep the API key in the VPS .env file only.
PANEL_URL = os.getenv("PANEL_URL", "https://panel.nextercloud.com").rstrip("/")
PANEL_API_KEY = os.getenv("PANEL_API_KEY", "").strip()
# Restrict this Application API key to read-only Nodes, Locations, and Allocations permissions.
PANEL_APP_API_KEY = os.getenv("PANEL_APP_API_KEY", "").strip()
PANEL_SERVERS = {
    "main": {"name": "Main Server", "identifier": os.getenv("PANEL_SERVER_MAIN", "f072de70").strip()},
    "velocity": {"name": "Velocity Proxy", "identifier": os.getenv("PANEL_SERVER_VELOCITY", "30436258").strip()},
    "pvp": {"name": "PvP Server", "identifier": os.getenv("PANEL_SERVER_PVP", "8e2a480f").strip()},
}

MAIN_SERVER_CONSOLE_ID = _int_env("MAIN_SERVER_CONSOLE_ID", 1539875653036281937)
VELOCITY_CONSOLE_ID = _int_env("VELOCITY_CONSOLE_ID", 1542774698163703888)
PVP_SERVER_CONSOLE_ID = _int_env("PVP_SERVER_CONSOLE_ID", 1553443227653251184)

MINECRAFT_SERVERS = {
    "Velocity Proxy": "ultimate-1.nextercloud.com:25565",
    "Main Server": "ultimate-1.nextercloud.com:19163",
    "PvP Server": "ultimate-1.nextercloud.com:19165",
}

# Minecraft Query gives the complete current online roster, unlike the optional
# partial player sample in the Java status response. Set these to each server's
# externally reachable UDP query host:port (often its allocated server port).
MINECRAFT_QUERY_SERVERS = {
    "main": os.getenv("QUERY_SERVER_MAIN", MINECRAFT_SERVERS["Main Server"]).strip(),
    "velocity": os.getenv("QUERY_SERVER_VELOCITY", MINECRAFT_SERVERS["Velocity Proxy"]).strip(),
    "pvp": os.getenv("QUERY_SERVER_PVP", MINECRAFT_SERVERS["PvP Server"]).strip(),
}

NODE_CONSOLE_CHANNELS = {
    "Velocity Proxy": VELOCITY_CONSOLE_ID,
    "Main Server": MAIN_SERVER_CONSOLE_ID,
    "PvP Server": PVP_SERVER_CONSOLE_ID,
}

CONSOLE_CHANNELS = {
    "main": MAIN_SERVER_CONSOLE_ID,
    "velocity": VELOCITY_CONSOLE_ID,
    "pvp": PVP_SERVER_CONSOLE_ID,
}

EVENT_RULES_TEXT = """
NO J4J/J2J ALLOWED
NO ALT/TOKEN ALLOWED
LEAVE/REJOIN/FAKE/UNDERAGE (3M) = -2
ONBOARDING = NO COUNT
NO BIO/PFP = NO COUNT
CHECKING INVITES IN OTHER CHANNELS EXCEPT #🤖〢commands = RESET
ASKING FOR PAYOUT = RESET
PING/REPLY PING = RESET
WE NEED 3D+ OLD CHAT & DM PROOFS
NO PROOFS = NO REWARD
DISRESPECTING ANYONE = RESET
YOUR INVITES MUST BE ACTIVE USERS
SERVER PROMO ALLOWED = +3 (DO 3 EXTRA INVITES)
REJOIN/LEAVE/FAKE NO COUNT IN SERVER PROMO
WE HOLD THE RIGHT TO CHANGE ANY RULE ANYTIME
""".strip()

INVITE_UNDERAGE_ACCOUNT_DAYS = _int_env("INVITE_UNDERAGE_ACCOUNT_DAYS", 90)

GROQ_MODEL_ID = os.getenv("GROQ_MODEL_ID", "openai/gpt-oss-120b")
TRANSCRIPT_CHUNK_CHAR_LIMIT = _int_env("TRANSCRIPT_CHUNK_CHAR_LIMIT", 9000)
AI_COMMAND_COOLDOWN_SECONDS = _int_env("AI_COMMAND_COOLDOWN_SECONDS", 20)

BRAND_NAME = os.getenv("BRAND_NAME", "NexterMC")
HOST_NAME = os.getenv("HOST_NAME", "NexterCloud")
