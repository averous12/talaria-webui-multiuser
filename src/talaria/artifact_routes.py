"""Authenticated artifact fetch and download routes."""

import base64
import mimetypes
import os
import stat
from pathlib import Path
from urllib.parse import quote

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .artifacts import MAX_ARTIFACT_BYTES
from .hermes import APIError, identifier, object_result
from .routes import body


def local_artifact(raw_path: str) -> tuple[Path, bytes]:
    """Read a regular file when Hermes refuses an external-delivery path.

    Talaria and Hermes are deliberately separate trust boundaries. This fallback is
    for the same host only: it accepts an absolute, existing regular file, rejects
    symlinks and special files, and applies Talaria's artifact size cap. It does not
    trust a path merely because the browser supplied it; the browser already sends
    only paths that occur in a Hermes assistant message.
    """
    if not isinstance(raw_path, str) or len(raw_path) > 4096:
        raise APIError("This file is no longer available.", 404)
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        raise APIError("This file is no longer available.", 404)
    try:
        if candidate.is_symlink():
            raise APIError("This file is no longer available.", 404)
        info = candidate.stat(follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode):
            raise APIError("This file is no longer available.", 404)
        if info.st_size <= 0 or info.st_size > MAX_ARTIFACT_BYTES:
            raise APIError("This file is too large to save in Talaria.", 413, "too_large")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(candidate, flags)
        with os.fdopen(descriptor, "rb") as file:
            if os.fstat(file.fileno()).st_size != info.st_size:
                raise APIError("This file is no longer available.", 404)
            raw = file.read(MAX_ARTIFACT_BYTES + 1)
    except APIError:
        raise
    except (OSError, ValueError) as exc:
        raise APIError("This file is no longer available.", 404) from exc
    if not raw or len(raw) > MAX_ARTIFACT_BYTES:
        raise APIError("This file is too large to save in Talaria.", 413, "too_large")
    return candidate, raw


def local_response(request: Request, sid: str, message_id: int, path: str) -> JSONResponse:
    local_path, raw = local_artifact(path)
    name = local_path.name[:180]
    if not name or name in {".", ".."}:
        raise APIError("This file is no longer available.", 404)
    mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
    artifact_id = request.app.state.artifacts.put(sid, message_id, path, name, mime[:128], raw)
    base = request.app.state.settings.base_path
    return JSONResponse(
        {
            "id": artifact_id,
            "name": name,
            "mime": mime,
            "url": f"{base}/api/artifacts/{artifact_id}",
        }
    )


async def fetch(request: Request):
    data = await body(request, 16 * 1024)
    sid = identifier(data.get("session_id", ""))
    message_id = data.get("message_id")
    path = data.get("path")
    if type(message_id) is not int or not 0 < message_id < 2**63:
        raise APIError("Choose a saved response.", 400)
    if not isinstance(path, str) or not path or len(path) > 4096:
        raise APIError("Choose a file from the response.", 400)
    cached = request.app.state.artifacts.get_by_source(sid, message_id, path)
    if cached:
        base = request.app.state.settings.base_path
        return JSONResponse({**cached, "url": f"{base}/api/artifacts/{cached['id']}"})
    try:
        result = await request.app.state.hermes.request(
            "GET",
            f"/talaria/v1/sessions/{sid}/{message_id}/artifact",
            params={"path": path},
            timeout=20,
        )
    except APIError as exc:
        if exc.status != 403:
            raise
        return local_response(request, sid, message_id, path)
    result = object_result(result)
    name, mime, encoded = result.get("name"), result.get("mime"), result.get("data")
    if not all(isinstance(value, str) for value in (name, mime, encoded)):
        raise APIError("Hermes returned an invalid file.", 502)
    name = Path(name.replace("\\", "/")).name[:180]
    if not name or name in {".", ".."}:
        raise APIError("Hermes returned an invalid file.", 502)
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise APIError("Hermes returned an unreadable file.", 502) from exc
    if not raw or len(raw) > MAX_ARTIFACT_BYTES:
        raise APIError("This file is too large to save in Talaria.", 413, "too_large")
    artifact_id = request.app.state.artifacts.put(sid, message_id, path, name, mime[:128], raw)
    base = request.app.state.settings.base_path
    return JSONResponse(
        {
            "id": artifact_id,
            "name": name,
            "mime": mime,
            "url": f"{base}/api/artifacts/{artifact_id}",
        }
    )


async def download(request: Request):
    artifact_id = request.path_params.get("artifact_id", "")
    if len(artifact_id) != 64 or any(c not in "0123456789abcdef" for c in artifact_id):
        raise APIError("This file is no longer available.", 404)
    artifact = request.app.state.artifacts.get(artifact_id)
    if artifact is None:
        raise APIError("This file is no longer available.", 404)
    name = artifact["name"].replace("\r", "_").replace("\n", "_").replace('"', "_")
    disposition = "inline" if artifact["mime"].startswith("image/") else "attachment"
    return Response(
        content=artifact["data"],
        media_type=artifact["mime"],
        headers={
            "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(name)}",
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
