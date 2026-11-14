"""Read one artifact from a specific assistant message under Hermes delivery policy."""

import asyncio
import base64
import mimetypes
import os
import stat
from pathlib import Path

MAX_ARTIFACT_BYTES = 8 * 1024 * 1024


def _safe_path(path):
    from gateway.platforms.base import validate_media_delivery_path

    return validate_media_delivery_path(path)


def _media_paths(text):
    from gateway.platforms.base import MEDIA_TAG_CLEANUP_RE, _normalize_media_tag_path

    return [
        _normalize_media_tag_path(match.group("path"))
        for match in MEDIA_TAG_CLEANUP_RE.finditer(text)
    ]


def _assistant_message(db, session_id, message_id):
    rows = db.get_messages(session_id, after_id=message_id - 1, limit=1)
    if not rows or rows[0].get("id") != message_id or rows[0].get("role") != "assistant":
        return None
    return rows[0]


def _resolve(requested, text):
    if not isinstance(requested, str) or len(requested) > 4096:
        return None
    for candidate in _media_paths(text):
        if candidate == requested:
            return _safe_path(candidate)
    return None


def _read(path):
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    fd = os.open(path, flags)
    with os.fdopen(fd, "rb") as file:
        info = os.fstat(file.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_ARTIFACT_BYTES:
            raise ValueError("Unsupported or oversized artifact")
        data = file.read(MAX_ARTIFACT_BYTES + 1)
    if not data or len(data) > MAX_ARTIFACT_BYTES:
        raise ValueError("Unsupported or oversized artifact")
    return data


async def dispatch(request, adapter, db):
    from aiohttp import web

    sid = request.match_info.get("session_id", "")
    try:
        message_id = int(request.match_info.get("message_id", ""))
    except (TypeError, ValueError):
        return web.json_response({"error": "Choose a saved response."}, status=400)
    if not 0 < message_id < 2**63:
        return web.json_response({"error": "Choose a saved response."}, status=400)
    message = await asyncio.to_thread(_assistant_message, db, sid, message_id)
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str):
        return web.json_response({"error": "This file is no longer available."}, status=404)
    path = await asyncio.to_thread(_resolve, request.query.get("path", ""), content)
    if not path:
        return web.json_response({"error": "This file is not approved for delivery."}, status=403)
    try:
        data = await asyncio.to_thread(_read, path)
    except (OSError, ValueError):
        return web.json_response({"error": "This file is no longer available."}, status=404)
    name = Path(path).name[:180] or "download"
    mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
    return web.json_response(
        {"name": name, "mime": mime, "data": base64.b64encode(data).decode("ascii")}
    )
