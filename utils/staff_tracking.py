"""Minimal staff role and ticket activity history (message text is never stored)."""
from __future__ import annotations

import asyncio
import datetime
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "staff_tracking.db"


@contextmanager
def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def _init_sync() -> None:
    with _connect() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS staff_role_assignments (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                role_id INTEGER NOT NULL,
                assigned_at TEXT NOT NULL,
                removed_at TEXT,
                PRIMARY KEY (guild_id, user_id, role_id)
            );
            CREATE TABLE IF NOT EXISTS staff_activity_daily (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                day_utc TEXT NOT NULL,
                channel_id INTEGER NOT NULL,
                is_ticket INTEGER NOT NULL,
                message_count INTEGER NOT NULL DEFAULT 0,
                last_message_at TEXT NOT NULL,
                PRIMARY KEY (guild_id, user_id, day_utc, channel_id, is_ticket)
            );
            CREATE TABLE IF NOT EXISTS staff_tracking_meta (
                name TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        """)
        db.execute(
            "INSERT OR IGNORE INTO staff_tracking_meta(name, value) VALUES('started_at', ?)",
            (datetime.datetime.now(datetime.timezone.utc).isoformat(),),
        )
        db.execute("DELETE FROM staff_activity_daily WHERE day_utc < date('now','-90 day')")


async def init_staff_tracking() -> None:
    await asyncio.to_thread(_init_sync)


def _record_role_sync(guild_id: int, user_id: int, role_id: int, added: bool, when: str) -> None:
    with _connect() as db:
        if added:
            db.execute(
                "INSERT INTO staff_role_assignments(guild_id,user_id,role_id,assigned_at,removed_at) "
                "VALUES(?,?,?,?,NULL) ON CONFLICT(guild_id,user_id,role_id) DO UPDATE SET "
                "assigned_at=excluded.assigned_at, removed_at=NULL",
                (guild_id, user_id, role_id, when),
            )
        else:
            db.execute(
                "UPDATE staff_role_assignments SET removed_at=? "
                "WHERE guild_id=? AND user_id=? AND role_id=? AND removed_at IS NULL",
                (when, guild_id, user_id, role_id),
            )


async def record_role_change(guild_id: int, user_id: int, role_id: int, added: bool, when: str) -> None:
    await asyncio.to_thread(_record_role_sync, guild_id, user_id, role_id, added, when)


def _record_message_sync(guild_id: int, user_id: int, day: str, channel_id: int, is_ticket: bool, when: str) -> None:
    with _connect() as db:
        db.execute(
            "INSERT INTO staff_activity_daily(guild_id,user_id,day_utc,channel_id,is_ticket,message_count,last_message_at) "
            "VALUES(?,?,?,?,?,1,?) ON CONFLICT(guild_id,user_id,day_utc,channel_id,is_ticket) "
            "DO UPDATE SET message_count=message_count+1, last_message_at=excluded.last_message_at",
            (guild_id, user_id, day, channel_id, int(is_ticket), when),
        )


async def record_staff_message(guild_id: int, user_id: int, day: str, channel_id: int, is_ticket: bool, when: str) -> None:
    await asyncio.to_thread(_record_message_sync, guild_id, user_id, day, channel_id, is_ticket, when)


def _assignments_sync(guild_id: int) -> dict[tuple[int, int], str]:
    with _connect() as db:
        rows = db.execute(
            "SELECT user_id,role_id,assigned_at FROM staff_role_assignments "
            "WHERE guild_id=? AND removed_at IS NULL", (guild_id,),
        ).fetchall()
    return {(int(row["user_id"]), int(row["role_id"])): str(row["assigned_at"]) for row in rows}


async def get_role_assignments(guild_id: int) -> dict[tuple[int, int], str]:
    return await asyncio.to_thread(_assignments_sync, guild_id)


def _profile_activity_sync(guild_id: int, user_id: int, day: str) -> dict:
    with _connect() as db:
        today = db.execute(
            "SELECT COALESCE(SUM(message_count),0) AS total, "
            "COALESCE(SUM(CASE WHEN is_ticket=1 THEN message_count ELSE 0 END),0) AS tickets "
            "FROM staff_activity_daily WHERE guild_id=? AND user_id=? AND day_utc=?",
            (guild_id, user_id, day),
        ).fetchone()
        last = db.execute(
            "SELECT channel_id,last_message_at FROM staff_activity_daily "
            "WHERE guild_id=? AND user_id=? ORDER BY last_message_at DESC LIMIT 1",
            (guild_id, user_id),
        ).fetchone()
    return {
        "today_total": int(today["total"]), "today_tickets": int(today["tickets"]),
        "last_channel": int(last["channel_id"]) if last else None,
        "last_at": str(last["last_message_at"]) if last else None,
    }


async def get_profile_activity(guild_id: int, user_id: int, day: str) -> dict:
    return await asyncio.to_thread(_profile_activity_sync, guild_id, user_id, day)


def _today_ranking_sync(guild_id: int, day: str) -> list[tuple[int, int]]:
    with _connect() as db:
        rows = db.execute(
            "SELECT user_id,SUM(message_count) AS total FROM staff_activity_daily "
            "WHERE guild_id=? AND day_utc=? AND is_ticket=1 GROUP BY user_id "
            "ORDER BY total DESC,user_id LIMIT 25", (guild_id, day),
        ).fetchall()
    return [(int(row["user_id"]), int(row["total"])) for row in rows]


async def get_today_ticket_ranking(guild_id: int, day: str) -> list[tuple[int, int]]:
    return await asyncio.to_thread(_today_ranking_sync, guild_id, day)


def _tracking_start_sync() -> str:
    with _connect() as db:
        row = db.execute("SELECT value FROM staff_tracking_meta WHERE name='started_at'").fetchone()
    return str(row["value"]) if row else "unknown"


async def get_tracking_start() -> str:
    return await asyncio.to_thread(_tracking_start_sync)
