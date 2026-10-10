# utils/storage.py
"""
Minimal persistence layer, backed by SQLite.

The original bot kept warnings in a plain in-memory dict, which means a
restart — including every single deploy on Railway — silently erased the
server's entire moderation history. For a community of a few dozen people
that's an annoyance; for one with 10,000 members it's a liability (an
appeal with "you have no warnings on file" because the file didn't survive
a redeploy).

This uses the stdlib's sqlite3, no extra service required. All calls are
synchronous under the hood but run via asyncio.to_thread so they never
block the event loop.

NOTE: on platforms with an ephemeral filesystem (Railway's default,
without an attached volume), this file is reset on every redeploy just
like the old in-memory dict was — but it now also survives simple crashes
and restarts *between* deploys, which the old code did not. For full
durability across deploys, attach a persistent volume and point
NEXTERMC_DB_PATH at a file inside it.
"""
from __future__ import annotations

import asyncio
import os
import sqlite3
from contextlib import contextmanager

DB_PATH = os.getenv("NEXTERMC_DB_PATH", "data/nextermc.db")


def _ensure_dir():
    directory = os.path.dirname(DB_PATH)
    if directory:
        os.makedirs(directory, exist_ok=True)


@contextmanager
def _connect():
    _ensure_dir()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _init_sync():
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS warnings (
                warn_id     INTEGER,
                guild_id    INTEGER NOT NULL,
                user_id     INTEGER NOT NULL,
                reason      TEXT NOT NULL,
                moderator   TEXT NOT NULL,
                created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (guild_id, warn_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS warning_counters (
                guild_id INTEGER PRIMARY KEY,
                next_id  INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS invites (
                guild_id    INTEGER NOT NULL,
                inviter_id  INTEGER NOT NULL,
                joined_id   INTEGER NOT NULL,
                joined_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (guild_id, joined_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS feature_flags (
                name TEXT PRIMARY KEY,
                enabled INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS disabled_commands (
                command_name TEXT PRIMARY KEY,
                disabled_by INTEGER NOT NULL,
                disabled_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS banned_words (
                guild_id INTEGER NOT NULL,
                term TEXT NOT NULL,
                added_by INTEGER NOT NULL,
                added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (guild_id, term)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS root_ping_strikes (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                strikes INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (guild_id, user_id)
            )
            """
        )
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS trainee_attempts (
                attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                trainee_id INTEGER NOT NULL,
                started_by INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                mode TEXT NOT NULL,
                topic TEXT,
                status TEXT NOT NULL,
                score REAL NOT NULL DEFAULT 0,
                max_score REAL NOT NULL DEFAULT 12,
                started_at TEXT NOT NULL,
                completed_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_trainee_attempts_owner
                ON trainee_attempts(guild_id, trainee_id, started_at DESC);
            CREATE TABLE IF NOT EXISTS trainee_answers (
                attempt_id INTEGER NOT NULL,
                position INTEGER NOT NULL,
                category TEXT NOT NULL,
                difficulty TEXT NOT NULL,
                question TEXT NOT NULL,
                response TEXT NOT NULL,
                answer_key TEXT NOT NULL,
                score REAL NOT NULL,
                feedback TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(attempt_id, position)
            );
            CREATE TABLE IF NOT EXISTS trainee_reviews (
                attempt_id INTEGER PRIMARY KEY,
                guild_id INTEGER NOT NULL,
                reviewer_id INTEGER NOT NULL,
                recommendation TEXT NOT NULL,
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS trainee_checklist (
                guild_id INTEGER NOT NULL,
                trainee_id INTEGER NOT NULL,
                item TEXT NOT NULL,
                completed_by INTEGER NOT NULL,
                completed_at TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                PRIMARY KEY(guild_id, trainee_id, item)
            );
            CREATE TABLE IF NOT EXISTS trainee_progress_resets (
                reset_id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                trainee_id INTEGER NOT NULL,
                actor_id INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )


async def init_db():
    await asyncio.to_thread(_init_sync)


def _get_feature_flag_sync(name: str, default: bool) -> bool:
    with _connect() as conn:
        row = conn.execute("SELECT enabled FROM feature_flags WHERE name = ?", (name,)).fetchone()
        return bool(row["enabled"]) if row else default


async def get_feature_flag(name: str, default: bool = False) -> bool:
    return await asyncio.to_thread(_get_feature_flag_sync, name, default)


def _set_feature_flag_sync(name: str, enabled: bool) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO feature_flags (name, enabled) VALUES (?, ?) "
            "ON CONFLICT(name) DO UPDATE SET enabled = excluded.enabled",
            (name, int(enabled)),
        )


async def set_feature_flag(name: str, enabled: bool) -> None:
    await asyncio.to_thread(_set_feature_flag_sync, name, enabled)


def _get_disabled_commands_sync():
    with _connect() as conn:
        rows = conn.execute("SELECT command_name FROM disabled_commands ORDER BY command_name").fetchall()
    return {str(row["command_name"]) for row in rows}


async def get_disabled_commands():
    return await asyncio.to_thread(_get_disabled_commands_sync)


def _set_disabled_command_sync(command_name, disabled_by, disabled):
    with _connect() as conn:
        if disabled:
            conn.execute(
                "INSERT INTO disabled_commands(command_name,disabled_by) VALUES(?,?) "
                "ON CONFLICT(command_name) DO UPDATE SET disabled_by=excluded.disabled_by, disabled_at=CURRENT_TIMESTAMP",
                (command_name, disabled_by),
            )
        else:
            conn.execute("DELETE FROM disabled_commands WHERE command_name=?", (command_name,))


async def set_disabled_command(command_name, disabled_by, disabled):
    await asyncio.to_thread(_set_disabled_command_sync, command_name, disabled_by, disabled)


def _add_banned_word_sync(guild_id: int, term: str, added_by: int) -> bool:
    with _connect() as conn:
        cursor = conn.execute(
            "INSERT OR IGNORE INTO banned_words(guild_id,term,added_by) VALUES(?,?,?)",
            (guild_id, term, added_by),
        )
        return cursor.rowcount > 0


async def add_banned_word(guild_id: int, term: str, added_by: int) -> bool:
    return await asyncio.to_thread(_add_banned_word_sync, guild_id, term, added_by)


def _remove_banned_word_sync(guild_id: int, term: str) -> bool:
    with _connect() as conn:
        cursor = conn.execute(
            "DELETE FROM banned_words WHERE guild_id=? AND term=?",
            (guild_id, term),
        )
        return cursor.rowcount > 0


async def remove_banned_word(guild_id: int, term: str) -> bool:
    return await asyncio.to_thread(_remove_banned_word_sync, guild_id, term)


def _list_banned_words_sync(guild_id: int) -> list[str]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT term FROM banned_words WHERE guild_id=? ORDER BY term COLLATE NOCASE",
            (guild_id,),
        ).fetchall()
    return [str(row["term"]) for row in rows]


async def list_banned_words(guild_id: int) -> list[str]:
    return await asyncio.to_thread(_list_banned_words_sync, guild_id)


def _record_restricted_mention_sync(guild_id: int, user_id: int) -> int:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO root_ping_strikes(guild_id,user_id,strikes) VALUES(?,?,1) "
            "ON CONFLICT(guild_id,user_id) DO UPDATE SET "
            "strikes=CASE WHEN updated_at <= datetime('now','-24 hours') THEN 1 ELSE strikes+1 END, "
            "updated_at=CURRENT_TIMESTAMP",
            (guild_id, user_id),
        )
        row = conn.execute(
            "SELECT strikes FROM root_ping_strikes WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        ).fetchone()
    return int(row["strikes"])


async def record_restricted_mention(guild_id: int, user_id: int) -> int:
    # Keep the existing table name so deployments retain their strike history.
    return await asyncio.to_thread(_record_restricted_mention_sync, guild_id, user_id)


# ---------------------------------------------------------------------------
# Trainee training records
# ---------------------------------------------------------------------------
def _create_trainee_attempt_sync(guild_id, trainee_id, started_by, channel_id, mode, topic, max_score, started_at):
    with _connect() as conn:
        cursor = conn.execute(
            "INSERT INTO trainee_attempts(guild_id,trainee_id,started_by,channel_id,mode,topic,status,max_score,started_at) "
            "VALUES(?,?,?,?,?,?,'in_progress',?,?)",
            (guild_id, trainee_id, started_by, channel_id, mode, topic, max_score, started_at),
        )
        return int(cursor.lastrowid)


async def create_trainee_attempt(guild_id, trainee_id, started_by, channel_id, mode, topic, max_score, started_at):
    return await asyncio.to_thread(
        _create_trainee_attempt_sync, guild_id, trainee_id, started_by, channel_id, mode, topic, max_score, started_at
    )


def _record_trainee_answer_sync(attempt_id, position, category, difficulty, question, response, answer_key, score, feedback, created_at):
    with _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO trainee_answers(attempt_id,position,category,difficulty,question,response,answer_key,score,feedback,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (attempt_id, position, category, difficulty, question, response, answer_key, score, feedback, created_at),
        )


async def record_trainee_answer(attempt_id, position, category, difficulty, question, response, answer_key, score, feedback, created_at):
    await asyncio.to_thread(
        _record_trainee_answer_sync, attempt_id, position, category, difficulty, question, response, answer_key, score, feedback, created_at
    )


def _finish_trainee_attempt_sync(attempt_id, status, score, completed_at):
    with _connect() as conn:
        conn.execute(
            "UPDATE trainee_attempts SET status=?, score=?, completed_at=? WHERE attempt_id=?",
            (status, score, completed_at, attempt_id),
        )


async def finish_trainee_attempt(attempt_id, status, score, completed_at):
    await asyncio.to_thread(_finish_trainee_attempt_sync, attempt_id, status, score, completed_at)


def _get_trainee_attempts_sync(guild_id, trainee_id, limit):
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM trainee_attempts WHERE guild_id=? AND trainee_id=? ORDER BY attempt_id DESC LIMIT ?",
            (guild_id, trainee_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]


async def get_trainee_attempts(guild_id, trainee_id, limit=20):
    return await asyncio.to_thread(_get_trainee_attempts_sync, guild_id, trainee_id, limit)


def _get_trainee_attempt_sync(guild_id, attempt_id):
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM trainee_attempts WHERE guild_id=? AND attempt_id=?", (guild_id, attempt_id)
        ).fetchone()
    return dict(row) if row else None


async def get_trainee_attempt(guild_id, attempt_id):
    return await asyncio.to_thread(_get_trainee_attempt_sync, guild_id, attempt_id)


def _get_trainee_answers_sync(attempt_id):
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM trainee_answers WHERE attempt_id=? ORDER BY position", (attempt_id,)
        ).fetchall()
    return [dict(row) for row in rows]


async def get_trainee_answers(attempt_id):
    return await asyncio.to_thread(_get_trainee_answers_sync, attempt_id)


def _get_trainee_checklist_sync(guild_id, trainee_id):
    with _connect() as conn:
        rows = conn.execute(
            "SELECT item,completed_by,completed_at,note FROM trainee_checklist WHERE guild_id=? AND trainee_id=?",
            (guild_id, trainee_id),
        ).fetchall()
    return {str(row["item"]): dict(row) for row in rows}


async def get_trainee_checklist(guild_id, trainee_id):
    return await asyncio.to_thread(_get_trainee_checklist_sync, guild_id, trainee_id)


def _set_trainee_checklist_sync(guild_id, trainee_id, item, completed_by, completed_at, note):
    with _connect() as conn:
        conn.execute(
            "INSERT INTO trainee_checklist(guild_id,trainee_id,item,completed_by,completed_at,note) VALUES(?,?,?,?,?,?) "
            "ON CONFLICT(guild_id,trainee_id,item) DO UPDATE SET completed_by=excluded.completed_by, "
            "completed_at=excluded.completed_at, note=excluded.note",
            (guild_id, trainee_id, item, completed_by, completed_at, note),
        )


async def set_trainee_checklist(guild_id, trainee_id, item, completed_by, completed_at, note=""):
    await asyncio.to_thread(_set_trainee_checklist_sync, guild_id, trainee_id, item, completed_by, completed_at, note)


def _save_trainee_review_sync(guild_id, attempt_id, reviewer_id, recommendation, notes, created_at):
    with _connect() as conn:
        row = conn.execute(
            "SELECT trainee_id,status,mode FROM trainee_attempts WHERE guild_id=? AND attempt_id=?",
            (guild_id, attempt_id),
        ).fetchone()
        if not row or row["status"] != "completed" or row["mode"] == "practice":
            return None
        conn.execute(
            "INSERT INTO trainee_reviews(attempt_id,guild_id,reviewer_id,recommendation,notes,created_at) VALUES(?,?,?,?,?,?) "
            "ON CONFLICT(attempt_id) DO UPDATE SET reviewer_id=excluded.reviewer_id,recommendation=excluded.recommendation,notes=excluded.notes,created_at=excluded.created_at",
            (attempt_id, guild_id, reviewer_id, recommendation, notes, created_at),
        )
        return int(row["trainee_id"])


async def save_trainee_review(guild_id, attempt_id, reviewer_id, recommendation, notes, created_at):
    return await asyncio.to_thread(
        _save_trainee_review_sync, guild_id, attempt_id, reviewer_id, recommendation, notes, created_at
    )


def _get_trainee_review_sync(attempt_id):
    with _connect() as conn:
        row = conn.execute("SELECT * FROM trainee_reviews WHERE attempt_id=?", (attempt_id,)).fetchone()
    return dict(row) if row else None


async def get_trainee_review(attempt_id):
    return await asyncio.to_thread(_get_trainee_review_sync, attempt_id)


def _reset_trainee_progress_sync(guild_id, trainee_id, actor_id, created_at):
    with _connect() as conn:
        conn.execute("DELETE FROM trainee_checklist WHERE guild_id=? AND trainee_id=?", (guild_id, trainee_id))
        conn.execute(
            "INSERT INTO trainee_progress_resets(guild_id,trainee_id,actor_id,created_at) VALUES(?,?,?,?)",
            (guild_id, trainee_id, actor_id, created_at),
        )


async def reset_trainee_progress(guild_id, trainee_id, actor_id, created_at):
    await asyncio.to_thread(_reset_trainee_progress_sync, guild_id, trainee_id, actor_id, created_at)


def _get_pending_trainee_reviews_sync(guild_id, limit):
    with _connect() as conn:
        rows = conn.execute(
            "SELECT a.attempt_id FROM trainee_attempts a LEFT JOIN trainee_reviews r ON r.attempt_id=a.attempt_id "
            "WHERE a.guild_id=? AND a.mode='scored' AND a.status='completed' AND r.attempt_id IS NULL "
            "ORDER BY a.attempt_id DESC LIMIT ?",
            (guild_id, limit),
        ).fetchall()
    return [int(row["attempt_id"]) for row in rows]


async def get_pending_trainee_reviews(guild_id, limit=100):
    return await asyncio.to_thread(_get_pending_trainee_reviews_sync, guild_id, limit)


# ---------------------------------------------------------------------------
# Warnings
# ---------------------------------------------------------------------------
def _add_warning_sync(guild_id: int, user_id: int, reason: str, moderator: str) -> int:
    with _connect() as conn:
        row = conn.execute(
            "SELECT next_id FROM warning_counters WHERE guild_id = ?", (guild_id,)
        ).fetchone()
        next_id = row["next_id"] if row else 1

        conn.execute(
            "INSERT INTO warnings (warn_id, guild_id, user_id, reason, moderator) VALUES (?, ?, ?, ?, ?)",
            (next_id, guild_id, user_id, reason, moderator),
        )
        conn.execute(
            "INSERT INTO warning_counters (guild_id, next_id) VALUES (?, ?) "
            "ON CONFLICT(guild_id) DO UPDATE SET next_id = excluded.next_id",
            (guild_id, next_id + 1),
        )
        return next_id


async def add_warning(guild_id: int, user_id: int, reason: str, moderator: str) -> int:
    return await asyncio.to_thread(_add_warning_sync, guild_id, user_id, reason, moderator)


def _remove_warning_sync(guild_id: int, warn_id: int) -> sqlite3.Row | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM warnings WHERE guild_id = ? AND warn_id = ?", (guild_id, warn_id)
        ).fetchone()
        if row is None:
            return None
        conn.execute("DELETE FROM warnings WHERE guild_id = ? AND warn_id = ?", (guild_id, warn_id))
        return row


async def remove_warning(guild_id: int, warn_id: int):
    return await asyncio.to_thread(_remove_warning_sync, guild_id, warn_id)


def _list_warnings_sync(guild_id: int, user_id: int) -> list[sqlite3.Row]:
    with _connect() as conn:
        return conn.execute(
            "SELECT * FROM warnings WHERE guild_id = ? AND user_id = ? ORDER BY warn_id",
            (guild_id, user_id),
        ).fetchall()


async def list_warnings(guild_id: int, user_id: int):
    return await asyncio.to_thread(_list_warnings_sync, guild_id, user_id)


# ---------------------------------------------------------------------------
# Invite tracking
# ---------------------------------------------------------------------------
def _record_invite_join_sync(guild_id: int, inviter_id: int, joined_id: int):
    with _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO invites (guild_id, inviter_id, joined_id) VALUES (?, ?, ?)",
            (guild_id, inviter_id, joined_id),
        )


async def record_invite_join(guild_id: int, inviter_id: int, joined_id: int):
    await asyncio.to_thread(_record_invite_join_sync, guild_id, inviter_id, joined_id)


def _count_invites_sync(guild_id: int, inviter_id: int) -> int:
    with _connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM invites WHERE guild_id = ? AND inviter_id = ?",
            (guild_id, inviter_id),
        ).fetchone()
        return row["c"] if row else 0


async def count_invites(guild_id: int, inviter_id: int) -> int:
    return await asyncio.to_thread(_count_invites_sync, guild_id, inviter_id)


def _get_inviter_sync(guild_id: int, joined_id: int):
    with _connect() as conn:
        row = conn.execute(
            "SELECT inviter_id FROM invites WHERE guild_id = ? AND joined_id = ?",
            (guild_id, joined_id),
        ).fetchone()
        return row["inviter_id"] if row else None


async def get_inviter(guild_id: int, joined_id: int):
    return await asyncio.to_thread(_get_inviter_sync, guild_id, joined_id)
