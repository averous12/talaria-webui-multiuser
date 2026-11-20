"""Lightweight per-session file uploads owned by Talaria."""

from __future__ import annotations

import mimetypes
import re
import secrets
from urllib.parse import unquote

from starlette.requests import Request
from starlette.responses import JSONResponse

from .hermes import APIError, identifier

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_FILENAME = 180
INVALID_FILENAME = re.compile(r"[\x00-\x1f\x7f<>:\"/\\|?*]")


def _safe_name(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise APIError("Choose a file.", 400, "invalid_file")
    name = value.strip()
    if len(name) > MAX_FILENAME:
        raise APIError("The filename is too long.", 400, "invalid_file")
    if name in {".", ".."} or INVALID_FILENAME.search(name):
        raise APIError("That filename is not supported.", 400, "invalid_file")
    return name


async def upload(request: Request):
    sid = identifier(request.path_params["session_id"])
    filename = _safe_name(unquote(request.headers.get("x-talaria-filename", "")))
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_UPLOAD_BYTES:
                raise APIError("Files must be 25 MB or smaller.", 413, "too_large")
        except ValueError as exc:
            raise APIError("Invalid file size.", 400, "invalid_file") from exc

    root = request.app.state.config_path.parent / "uploads" / sid
    root.mkdir(parents=True, exist_ok=True)
    target = root / filename
    if target.exists():
        target = root / f"{target.stem}-{secrets.token_hex(4)}{target.suffix}"

    size = 0
    try:
        with target.open("xb") as output:
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise APIError("Files must be 25 MB or smaller.", 413, "too_large")
                output.write(chunk)
    except APIError:
        target.unlink(missing_ok=True)
        raise
    except OSError as exc:
        target.unlink(missing_ok=True)
        raise APIError("Talaria could not save this file.", 507, "storage_unavailable") from exc

    relative = "/".join(("uploads", sid, target.name))
    mime = request.headers.get("content-type") or mimetypes.guess_type(target.name)[0]
    return JSONResponse(
        {
            "id": secrets.token_hex(12),
            "name": target.name,
            "path": target.resolve().as_posix(),
            "relative_path": relative,
            "mime": mime or "application/octet-stream",
            "size": size,
            "session_id": sid,
        },
        status_code=201,
    )
