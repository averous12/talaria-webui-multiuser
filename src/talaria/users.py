"""Durable local accounts and roles."""

from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path

from .agent_presentation import DEFAULT_PRESENTATION, validate_presentation
from .auth import hash_password, verify_password

USERNAME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{2,63}$")
ROLES = {"admin", "user"}


def _presentation(value):
    if not value:
        return dict(DEFAULT_PRESENTATION)
    try:
        return validate_presentation(json.loads(value))
    except (ValueError, TypeError, json.JSONDecodeError):
        return dict(DEFAULT_PRESENTATION)


class UserStore:
    def __init__(self, path: Path, legacy_password_hash=""):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with sqlite3.connect(self.path) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=FULL")
            db.execute(
                """CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('admin', 'user')),
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created REAL NOT NULL,
                    updated REAL NOT NULL,
                    profile_id TEXT,
                    presentation TEXT,
                    monthly_budget_micro_idr INTEGER
                )"""
            )
            db.execute(
                """CREATE TABLE IF NOT EXISTS session_owners (
                    user_id INTEGER NOT NULL, profile TEXT NOT NULL, session TEXT NOT NULL,
                    PRIMARY KEY (user_id, profile, session)
                )"""
            )
            db.execute(
                """CREATE TABLE IF NOT EXISTS run_owners (
                    user_id INTEGER NOT NULL, profile TEXT NOT NULL, run TEXT NOT NULL,
                    PRIMARY KEY (user_id, profile, run)
                )"""
            )
            db.execute("PRAGMA table_info(users)")
            columns = {row[1] for row in db.execute("PRAGMA table_info(users)")}
            if "profile_id" not in columns:
                db.execute("ALTER TABLE users ADD COLUMN profile_id TEXT")
            if "presentation" not in columns:
                db.execute("ALTER TABLE users ADD COLUMN presentation TEXT")
            if "monthly_budget_micro_idr" not in columns:
                db.execute("ALTER TABLE users ADD COLUMN monthly_budget_micro_idr INTEGER")
            if db.execute("SELECT 1 FROM users LIMIT 1").fetchone() is None:
                if not legacy_password_hash:
                    raise ValueError("At least one administrator account is required.")
                now = time.time()
                db.execute(
                    "INSERT INTO users "
                    "(username,password_hash,role,created,updated) VALUES (?,?,?,?,?)",
                    ("admin", legacy_password_hash, "admin", now, now),
                )
        self.path.chmod(0o600)

    def _public(self, row):
        return {
            "id": row[0],
            "username": row[1],
            "role": row[2],
            "enabled": bool(row[3]),
            "created": row[4],
            "profile_id": row[5],
            "presentation": _presentation(row[6]),
            "monthly_budget_micro_idr": row[7],
        }

    def authenticate(self, username, password):
        if not isinstance(username, str) or not USERNAME.fullmatch(username):
            return None
        if not isinstance(password, str):
            return None
        with sqlite3.connect(self.path) as db:
            row = db.execute(
                "SELECT id,username,password_hash,role,enabled,created,profile_id,"
                "presentation,monthly_budget_micro_idr "
                "FROM users "
                "WHERE username = ? COLLATE NOCASE",
                (username,),
            ).fetchone()
        if not row or not row[4] or not verify_password(password, row[2]):
            return None
        return self._public((row[0], row[1], row[3], row[4], row[5], row[6], row[7], row[8]))

    def list_public(self):
        with sqlite3.connect(self.path) as db:
            rows = db.execute(
                "SELECT id,username,role,enabled,created,profile_id,"
                "presentation,monthly_budget_micro_idr "
                "FROM users ORDER BY id"
            ).fetchall()
        return [self._public(row) for row in rows]

    def create(self, username, password, role="user", profile_id=None):
        if not isinstance(username, str) or not USERNAME.fullmatch(username):
            raise ValueError("username")
        if not isinstance(password, str) or not 4 <= len(password) <= 1024:
            raise ValueError("password")
        if role not in ROLES:
            raise ValueError("role")
        now = time.time()
        try:
            with sqlite3.connect(self.path) as db:
                cursor = db.execute(
                    "INSERT INTO users "
                    "(username,password_hash,role,created,updated,profile_id,"
                    "presentation,monthly_budget_micro_idr) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                                        (
                                            username,
                                            hash_password(password),
                                            role,
                                            now,
                                            now,
                                            profile_id,
                                            json.dumps(DEFAULT_PRESENTATION),
                                            None,
                                        ),
                )
                user_id = cursor.lastrowid
                row = db.execute(
                    "SELECT id,username,role,enabled,created,profile_id,"
                    "presentation,monthly_budget_micro_idr "
                    "FROM users WHERE id=?",
                    (user_id,),
                ).fetchone()
        except sqlite3.IntegrityError as exc:
            raise ValueError("username_exists") from exc
        return self._public(row)

    def get(self, user_id):
        with sqlite3.connect(self.path) as db:
            row = db.execute(
                "SELECT id,username,role,enabled,created,profile_id,"
                "presentation,monthly_budget_micro_idr "
                "FROM users WHERE id=?",
                (user_id,),
            ).fetchone()
        return self._public(row) if row else None

    def is_admin(self, user_id):
        user = self.get(user_id)
        return bool(user and user["role"] == "admin")

    def owns(self, user_id, profile, session):
        with sqlite3.connect(self.path) as db:
            return db.execute(
                "SELECT 1 FROM session_owners WHERE user_id=? AND profile=? AND session=?",
                (user_id, profile, session),
            ).fetchone() is not None

    def claim(self, user_id, profile, session):
        with sqlite3.connect(self.path) as db:
            db.execute(
                "INSERT OR IGNORE INTO session_owners (user_id,profile,session) VALUES (?,?,?)",
                (user_id, profile, session),
            )

    def owned_sessions(self, user_id, profile):
        with sqlite3.connect(self.path) as db:
            return {
                row[0]
                for row in db.execute(
                    "SELECT session FROM session_owners WHERE user_id=? AND profile=?",
                    (user_id, profile),
                )
            }

    def assign(self, user_id, profile, session):
        self.claim(user_id, profile, session)


    def set_presentation(self, user_id, value):
        value = validate_presentation(value)
        with sqlite3.connect(self.path) as db:
            db.execute(
                "UPDATE users SET presentation=?, updated=? WHERE id=?",
                (json.dumps(value, sort_keys=True), time.time(), user_id),
            )
        return value

    def set_monthly_budget(self, user_id, monthly_budget_micro_idr):
        if type(monthly_budget_micro_idr) is not int or monthly_budget_micro_idr < 0:
            raise ValueError("monthly_budget_micro_idr")
        with sqlite3.connect(self.path) as db:
            db.execute(
                "UPDATE users SET monthly_budget_micro_idr=?, updated=? WHERE id=?",
                (monthly_budget_micro_idr or None, time.time(), user_id),
            )

    def assign_profile(self, user_id, profile_id):
        with sqlite3.connect(self.path) as db:
            db.execute(
                "UPDATE users SET profile_id=?, updated=? WHERE id=?",
                (profile_id, time.time(), user_id),
            )

    def set_password(self, user_id, password):
        if not isinstance(password, str) or not 4 <= len(password) <= 1024:
            raise ValueError("password")
        with sqlite3.connect(self.path) as db:
            db.execute(
                "UPDATE users SET password_hash=?, updated=? WHERE id=?",
                (hash_password(password), time.time(), user_id),
            )

    def set_enabled(self, user_id, enabled):
        with sqlite3.connect(self.path) as db:
            row = db.execute("SELECT role,enabled FROM users WHERE id=?", (user_id,)).fetchone()
            if row is None:
                raise ValueError("user")
            if row[0] == "admin" and not enabled:
                admins = db.execute(
                    "SELECT COUNT(*) FROM users WHERE role='admin' AND enabled=1"
                ).fetchone()[0]
                if admins <= 1:
                    raise ValueError("last_admin")
            db.execute(
                "UPDATE users SET enabled=?, updated=? WHERE id=?",
                (int(bool(enabled)), time.time(), user_id),
            )
