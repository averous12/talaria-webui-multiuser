"""Authenticated artifact fetch and download routes."""

import base64
from pathlib import Path
from urllib.parse import quote

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .artifacts import MAX_ARTIFACT_BYTES
from .hermes import APIError, identifier, object_result
from .routes import body


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
    result = await request.app.state.hermes.request(
        "GET",
        f"/talaria/v1/sessions/{sid}/{message_id}/artifact",
        params={"path": path},
        timeout=20,
    )
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
