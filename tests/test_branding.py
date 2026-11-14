import json

import pytest

from talaria.branding import load_branding


def test_default_branding_exposes_builtin_identity_and_assets(tmp_path):
    brand = load_branding("", tmp_path / "static")
    assert brand.public["product_name"] == "Talaria"
    assert brand.public["short_name"] == "Talaria"
    assert brand.public["agent_name_mode"] == "hermes"
    assert brand.public["assets"] == {
        "logo": "mark.svg",
        "favicon": "mark.svg",
        "apple_touch_icon": "icons/apple-touch-icon.png",
        "icon_192": "icons/icon-192.png",
        "icon_512": "icons/icon-512.png",
        "maskable_icon": "icons/maskable-512.png",
    }


def test_custom_branding_validates_and_reads_pack(tmp_path):
    pack = tmp_path / "aurora"
    pack.mkdir()
    for name in [
        "logo.svg", "favicon.svg", "apple.png", "icon-192.png", "icon-512.png", "mask.png"
    ]:
        (pack / name).write_bytes(b"asset")
    (pack / "brand.json").write_text(json.dumps({
        "product_name": "Aurora Desk",
        "short_name": "Aurora",
        "description": "A calm agent workspace.",
        "agent_name": "Aurora",
        "agent_name_mode": "brand",
        "theme_color": "#102030",
        "background_color": "#fefefe",
        "assets": {
            "logo": "logo.svg", "favicon": "favicon.svg", "apple_touch_icon": "apple.png",
            "icon_192": "icon-192.png", "icon_512": "icon-512.png", "maskable_icon": "mask.png",
        },
    }))
    brand = load_branding(str(pack), tmp_path / "static")
    assert brand.public["product_name"] == "Aurora Desk"
    assert brand.public["agent_name"] == "Aurora"
    assert brand.asset_path("logo.svg") == pack / "logo.svg"


@pytest.mark.parametrize("field,value", [
    ("product_name", ""),
    ("theme_color", "red"),
    ("agent_name_mode", "override"),
])
def test_custom_branding_rejects_invalid_values(tmp_path, field, value):
    pack = tmp_path / "bad"
    pack.mkdir()
    data = {field: value}
    (pack / "brand.json").write_text(json.dumps(data))
    with pytest.raises(ValueError):
        load_branding(str(pack), tmp_path / "static")


def test_custom_branding_rejects_asset_traversal(tmp_path):
    pack = tmp_path / "bad"
    pack.mkdir()
    (pack / "brand.json").write_text(json.dumps({"assets": {"logo": "../secret.svg"}}))
    with pytest.raises(ValueError):
        load_branding(str(pack), tmp_path / "static")
