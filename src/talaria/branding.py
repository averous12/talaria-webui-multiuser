"""Validated, installation-wide branding packs."""

from __future__ import annotations

import json
import mimetypes
import re
from dataclasses import dataclass
from pathlib import Path

from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse

DEFAULT_ASSETS = {
    "logo": "mark.svg",
    "favicon": "mark.svg",
    "apple_touch_icon": "icons/apple-touch-icon.png",
    "icon_192": "icons/icon-192.png",
    "icon_512": "icons/icon-512.png",
    "maskable_icon": "icons/maskable-512.png",
}
DEFAULT_PUBLIC = {
    "product_name": "Talaria",
    "short_name": "Talaria",
    "description": "A web interface for Hermes Agent",
    "agent_name": "",
    "agent_name_mode": "hermes",
    "theme_color": "#fbfbf9",
    "background_color": "#fbfbf9",
    "assets": DEFAULT_ASSETS,
}
HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
ASSET_KEY = re.compile(r"^[a-z][a-z0-9_]{0,31}$")


@dataclass(frozen=True)
class Branding:
    root: Path
    public: dict

    def asset_path(self, relative):
        path = _asset_name(relative)
        candidate = (self.root / path).resolve()
        if self.root.resolve() not in candidate.parents:
            raise ValueError("Brand asset escapes the branding folder.")
        if not candidate.is_file():
            raise ValueError(f"Brand asset is missing: {path}")
        return candidate


def load_branding(folder, static_root: Path):  # noqa: C901, PLR0912
    if not folder:
        return Branding(static_root.resolve(), dict(DEFAULT_PUBLIC))
    root = Path(folder).expanduser().resolve()
    if not root.is_dir():
        raise ValueError("Branding folder does not exist.")
    manifest = root / "brand.json"
    if not manifest.is_file():
        raise ValueError("Branding folder must contain brand.json.")
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Branding manifest is unreadable JSON.") from exc
    if not isinstance(data, dict):
        raise ValueError("Branding manifest must be an object.")
    public = dict(DEFAULT_PUBLIC)
    for key in ("product_name", "short_name", "description", "agent_name"):
        if key in data:
            value = data[key]
            if not isinstance(value, str) or not value.strip() or len(value) > 160:
                raise ValueError(f"Invalid branding field: {key}")
            public[key] = value.strip()
    mode = data.get("agent_name_mode", public["agent_name_mode"])
    if mode not in {"hermes", "brand"}:
        raise ValueError("agent_name_mode must be hermes or brand.")
    public["agent_name_mode"] = mode
    for key in ("theme_color", "background_color"):
        value = data.get(key, public[key])
        if not isinstance(value, str) or not HEX_COLOR.fullmatch(value):
            raise ValueError(f"Invalid branding color: {key}")
        public[key] = value
    assets = data.get("assets", {})
    if not isinstance(assets, dict):
        raise ValueError("Branding assets must be an object.")
    merged = dict(DEFAULT_ASSETS)
    for key, value in assets.items():
        if not isinstance(key, str) or not ASSET_KEY.fullmatch(key) or not isinstance(value, str):
            raise ValueError("Invalid branding asset entry.")
        merged[key] = _asset_name(value)
    public["assets"] = merged
    branding = Branding(root, public)
    for value in merged.values():
        branding.asset_path(value)
    return branding


def _asset_name(value):
    path = Path(value.replace("\\", "/"))
    if not value or path.is_absolute() or ".." in path.parts:
        raise ValueError("Brand assets must be relative paths.")

    return path.as_posix()


def public_details(branding, base):
    public = dict(branding.public)
    assets = public["assets"]
    public["logo_url"] = f"{base}/branding/{assets['logo']}"
    public["favicon_url"] = f"{base}/branding/{assets['favicon']}"
    public["apple_touch_icon_url"] = f"{base}/branding/{assets['apple_touch_icon']}"
    public["asset_base"] = f"{base}/branding/"
    public["manifest_url"] = f"{base}/branding/manifest"
    return public


def manifest(branding, base):
    assets = branding.public["assets"]
    return {
        "id": base + "/",
        "name": branding.public["product_name"],
        "short_name": branding.public["short_name"],
        "description": branding.public["description"],
        "start_url": base + "/",
        "scope": base + "/",
        "display": "standalone",
        "background_color": branding.public["background_color"],
        "theme_color": branding.public["theme_color"],
        "icons": [
            {
                "src": f"{base}/branding/{assets['icon_192']}",
                "sizes": "192x192",
                "type": "image/png",
            },
            {
                "src": f"{base}/branding/{assets['icon_512']}",
                "sizes": "512x512",
                "type": "image/png",
            },
            {
                "src": f"{base}/branding/{assets['maskable_icon']}",
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "maskable",
            },
        ],
    }


async def details(request: Request):
    state = request.app.state
    public = public_details(state.branding, state.settings.base_path)
    return JSONResponse(public)


async def manifest_route(request: Request):
    state = request.app.state
    return JSONResponse(manifest(state.branding, state.settings.base_path))


async def asset(request: Request):
    relative = request.path_params["path"]
    try:
        path = request.app.state.branding.asset_path(relative)
    except ValueError:
        return JSONResponse({"error": "Brand asset not found."}, status_code=404)
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(path, media_type=media_type, headers={"Cache-Control": "no-cache"})
