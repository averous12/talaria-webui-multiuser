"""Durable, profile-scoped assistant file artifacts."""

import contextlib
import hashlib
import os
import sqlite3
import time
from pathlib import Path

MAX_ARTIFACT_BYTES = 50 * 1024 * 1024


class ArtifactStore:
    def __init__(self, path: Path, *, profile_id="default", max_bytes=MAX_ARTIFACT_BYTES):
        self.path = Path(path)
        self.profile_id = profile_id
        self.max_bytes = max_bytes
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path.touch(mode=0o600, exist_ok=True)
        with contextlib.suppress(OSError):
            os.chmod(self.path, 0o600)
        with self.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS artifacts (
                id TEXT PRIMARY KEY, profile TEXT NOT NULL, session TEXT NOT NULL,
                message_id INTEGER NOT NULL, path TEXT NOT NULL, name TEXT NOT NULL,
                mime TEXT NOT NULL, data BLOB NOT NULL, size INTEGER NOT NULL,
                created REAL NOT NULL, accessed REAL NOT NULL,
                UNIQUE(profile, session, message_id, path))""")
            db.execute("CREATE INDEX IF NOT EXISTS artifacts_age ON artifacts(created)")

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        return db

    def put(self, session, message_id, path, name, mime, data):
        data = bytes(data)
        if not data or len(data) > self.max_bytes or type(message_id) is not int or message_id < 1:
            raise ValueError("Invalid or oversized artifact")
        digest = hashlib.sha256(
            f"{self.profile_id}\0{session}\0{message_id}\0{path}".encode()
        ).hexdigest()
        now = time.time()
        with self.connect() as db:
            db.execute(
                """INSERT INTO artifacts
                (id,profile,session,message_id,path,name,mime,data,size,created,accessed)
                VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(profile,session,message_id,path)
                DO UPDATE SET name=excluded.name,mime=excluded.mime,data=excluded.data,
                size=excluded.size,accessed=excluded.accessed""",
                (
                    digest,
                    self.profile_id,
                    session,
                    message_id,
                    path,
                    name,
                    mime,
                    data,
                    len(data),
                    now,
                    now,
                ),
            )
            total = db.execute("SELECT COALESCE(SUM(size),0) FROM artifacts").fetchone()[0]
            while total > 512 * 1024 * 1024:
                row = db.execute(
                    "SELECT id,size FROM artifacts ORDER BY accessed LIMIT 1"
                ).fetchone()
                if row is None:
                    break
                db.execute("DELETE FROM artifacts WHERE id=?", (row[0],))
                total -= row[1]
        return digest

    def get_by_source(self, session, message_id, path):
        with self.connect() as db:
            row = db.execute(
                "SELECT id,name,mime FROM artifacts "
                "WHERE profile=? AND session=? AND message_id=? AND path=?",
                (self.profile_id, session, message_id, path),
            ).fetchone()
            if row is None:
                return None
            db.execute("UPDATE artifacts SET accessed=? WHERE id=?", (time.time(), row[0]))
            return {"id": row[0], "name": row[1], "mime": row[2]}

    def delete_profile(self, profile_id=None):
        profile_id = profile_id or self.profile_id
        with self.connect() as db:
            db.execute("DELETE FROM artifacts WHERE profile=?", (profile_id,))

    def get(self, artifact_id):
        with self.connect() as db:
            row = db.execute(
                "SELECT session,message_id,path,name,mime,data FROM artifacts "
                "WHERE id=? AND profile=?",
                (artifact_id, self.profile_id),
            ).fetchone()
            if row is None:
                return None
            db.execute("UPDATE artifacts SET accessed=? WHERE id=?", (time.time(), artifact_id))
            return dict(
                zip(("session_id", "message_id", "path", "name", "mime", "data"), row, strict=True)
            )

    def delete_session(self, session):
        with self.connect() as db:
            db.execute(
                "DELETE FROM artifacts WHERE profile=? AND session=?", (self.profile_id, session)
            )

    def close(self):
        pass
