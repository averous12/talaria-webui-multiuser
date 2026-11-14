"""Durable Web Push subscriptions and VAPID delivery."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import sqlite3
import time
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid
from pywebpush import WebPushException, webpush
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse

from .hermes import APIError

log = logging.getLogger(__name__)
MAX_SUBSCRIPTIONS = 32


class PushStore:
    def __init__(self, config_path: Path):
        self.path = config_path.with_name(config_path.stem + ".push.db")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("""
                CREATE TABLE IF NOT EXISTS vapid (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    private_pem TEXT NOT NULL,
                    public_key TEXT NOT NULL
                )
            """)
            db.execute("""
                CREATE TABLE IF NOT EXISTS subscriptions (
                    profile TEXT NOT NULL,
                    endpoint TEXT NOT NULL,
                    p256dh TEXT NOT NULL,
                    auth TEXT NOT NULL,
                    updated REAL NOT NULL,
                    PRIMARY KEY (profile, endpoint)
                )
            """)
            db.execute("""
                CREATE TABLE IF NOT EXISTS runs (
                    profile TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    session TEXT NOT NULL,
                    PRIMARY KEY (profile, run_id)
                )
            """)
            if db.execute("SELECT 1 FROM vapid WHERE id = 1").fetchone() is None:
                vapid = Vapid()
                vapid.generate_keys()
                public = _public_key(vapid.public_key)
                db.execute(
                    "INSERT INTO vapid VALUES (1, ?, ?)",
                    (vapid.private_pem().decode(), public),
                )

    @property
    def public_key(self):
        with sqlite3.connect(self.path) as db:
            return db.execute("SELECT public_key FROM vapid WHERE id = 1").fetchone()[0]

    def subscribe(self, profile, subscription):
        endpoint, keys = _validate_subscription(subscription)
        now = time.time()
        with sqlite3.connect(self.path) as db:
            db.execute(
                """INSERT INTO subscriptions VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(profile, endpoint) DO UPDATE SET
                   p256dh=excluded.p256dh, auth=excluded.auth, updated=excluded.updated""",
                (profile, endpoint, keys["p256dh"], keys["auth"], now),
            )
            db.execute(
                """DELETE FROM subscriptions WHERE profile = ? AND endpoint IN
                   (SELECT endpoint FROM subscriptions WHERE profile = ?
                    ORDER BY updated DESC LIMIT -1 OFFSET ?)""",
                (profile, profile, MAX_SUBSCRIPTIONS),
            )

    def unsubscribe(self, profile, endpoint):
        with sqlite3.connect(self.path) as db:
            db.execute(
                "DELETE FROM subscriptions WHERE profile = ? AND endpoint = ?",
                (profile, endpoint),
            )

    def bind_run(self, profile, run_id, session_id):
        with sqlite3.connect(self.path) as db:
            db.execute(
                "INSERT OR REPLACE INTO runs VALUES (?, ?, ?)",
                (profile, run_id, session_id),
            )

    def session_for_run(self, profile, run_id):
        with sqlite3.connect(self.path) as db:
            row = db.execute(
                "SELECT session FROM runs WHERE profile = ? AND run_id = ?",
                (profile, run_id),
            ).fetchone()
        return row[0] if row else ""

    def subscriptions(self, profile):
        with sqlite3.connect(self.path) as db:
            rows = db.execute(
                "SELECT endpoint, p256dh, auth FROM subscriptions WHERE profile = ?",
                (profile,),
            ).fetchall()
        return [{"endpoint": e, "keys": {"p256dh": p, "auth": a}} for e, p, a in rows]

    async def notify(self, profile, run_id, event):
        session = self.session_for_run(profile, run_id)
        payload = _payload(run_id, event, session)
        if payload is None:
            return
        subscriptions = self.subscriptions(profile)
        if not subscriptions:
            return
        with sqlite3.connect(self.path) as db:
            private_pem = db.execute("SELECT private_pem FROM vapid WHERE id = 1").fetchone()[0]
        await asyncio.gather(*(
            self._send(profile, subscription, payload, private_pem)
            for subscription in subscriptions
        ))

    async def _send(self, profile, subscription, payload, private_pem):
        try:
            await asyncio.to_thread(
                webpush,
                subscription,
                data=json.dumps(payload, separators=(",", ":")),
                vapid_private_key=private_pem,
                vapid_claims={"sub": "mailto:averousraihan@gmail.com"},
                ttl=3600,
            )
        except WebPushException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in {404, 410}:
                self.unsubscribe(profile, subscription["endpoint"])
            else:
                log.warning("Web Push delivery failed: %s", exc)
        except Exception:
            log.exception("Web Push delivery failed")


def _public_key(key):
    raw = key.public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    )
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _validate_subscription(value):
    if not isinstance(value, dict):
        raise ValueError("Invalid push subscription.")
    endpoint = value.get("endpoint")
    keys = value.get("keys")
    if not isinstance(endpoint, str) or not endpoint.startswith("https://") or len(endpoint) > 2048:
        raise ValueError("Invalid push endpoint.")
    if not isinstance(keys, dict) or any(
        not isinstance(keys.get(key), str) or not keys[key] for key in ("p256dh", "auth")
    ):
        raise ValueError("Invalid push keys.")
    return endpoint, {key: keys[key][:512] for key in ("p256dh", "auth")}


async def push_config(request: Request):
    return JSONResponse({"public_key": request.app.state.push.public_key})


async def subscribe(request: Request):
    data = await request.json()
    try:
        request.app.state.push.subscribe(request.app.state.profile_id, data)
    except (TypeError, ValueError) as exc:
        raise APIError(str(exc), 400, "invalid_request") from exc
    return JSONResponse({"ok": True})


async def unsubscribe(request: Request):
    data = await request.json()
    endpoint = data.get("endpoint") if isinstance(data, dict) else None
    if not isinstance(endpoint, str):
        raise APIError("Invalid push endpoint.", 400, "invalid_request")
    request.app.state.push.unsubscribe(request.app.state.profile_id, endpoint)
    return JSONResponse({"ok": True})


def service_worker(request: Request):
    base = request.app.state.settings.base_path or ""
    script = (
        "self.addEventListener('push', event => {\n"
        "  let data = {};\n"
        "  try { data = event.data ? event.data.json() : {}; } catch (_) {}\n"
        "  const title = data.kind === 'clarification' ? 'Your agent needs input' : "
        "'Response complete';\n"
        "  const body = data.kind === 'clarification' ? (data.question || "
        "'Your agent is waiting for your answer.') : 'Your response is ready.';\n"
        "  event.waitUntil(self.registration.showNotification(title, { body, data: { url: '"
        + base
        + "/' + (data.url || '') } }));\n"
        "});\n"
        "self.addEventListener('notificationclick', event => {\n"
        "  event.notification.close();\n"
        "  const target = new URL(event.notification.data?.url || '"
        + base
        + "/', self.location.origin).href;\n"
        "  event.waitUntil(clients.matchAll({ type: 'window', "
        "includeUncontrolled: true }).then(list => {\n"
        "    for (const client of list) if ('focus' in client) { "
        "client.navigate(target); return client.focus(); }\n"
        "    return clients.openWindow(target);\n"
        "  }));\n"
        "});\n"
    )
    return PlainTextResponse(script, media_type="application/javascript")


def _payload(run_id, event, session=""):
    kind = event.get("event") if isinstance(event, dict) else None
    if kind == "run.completed":
        return {
            "kind": "completed",
            "run_id": run_id,
            "url": f"?session={session}" if session else "?session=",
        }
    if kind in {"talaria.clarification.request", "clarify.request"}:
        question = event.get("question") or event.get("prompt") or "Your agent needs input."
        return {"kind": "clarification", "run_id": run_id, "question": str(question)[:2000]}
    return None
