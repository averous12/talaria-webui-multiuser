import json
from pathlib import Path

from talaria.branding import load_branding


def test_branding_routes_and_default_shell(live_app):
    address, _, _app = live_app
    import urllib.request

    page = urllib.request.urlopen(address).read().decode()
    assert '<title>Talaria</title>' in page
    assert '/branding/manifest' in page
    manifest = json.loads(urllib.request.urlopen(address + '/branding/manifest').read())
    assert manifest['name'] == 'Talaria'
    assert manifest['icons'][0]['src'].endswith('/branding/icons/icon-192.png')
    asset = urllib.request.urlopen(address + '/branding/mark.svg')
    assert asset.status == 200
    assert asset.headers["content-type"].startswith("image/svg")


def test_custom_branding_is_served_by_live_routes(live_app, tmp_path):
    pack = tmp_path / "aurora"
    pack.mkdir()
    for name in [
        "logo.svg", "favicon.svg", "apple.png", "icon-192.png", "icon-512.png", "mask.png"
    ]:
        (pack / name).write_bytes(b"custom-" + name.encode())
    (pack / "brand.json").write_text(json.dumps({
        "product_name": "Aurora Desk",
        "short_name": "Aurora",
        "description": "A custom workspace.",
        "theme_color": "#102030",
        "background_color": "#fefefe",
        "assets": {
            "logo": "logo.svg", "favicon": "favicon.svg", "apple_touch_icon": "apple.png",
            "icon_192": "icon-192.png", "icon_512": "icon-512.png", "maskable_icon": "mask.png",
        },
    }))
    live_app[2].state.branding = load_branding(
        str(pack), Path(live_app[2].state.settings.base_path or ".")
    )
    import urllib.request

    page = urllib.request.urlopen(live_app[0]).read().decode()
    assert "<title>Aurora Desk</title>" in page
    manifest = json.loads(urllib.request.urlopen(live_app[0] + "/branding/manifest").read())
    assert manifest["name"] == "Aurora Desk"
    assert manifest["theme_color"] == "#102030"
    asset = urllib.request.urlopen(live_app[0] + "/branding/logo.svg")
    assert asset.read() == b"custom-logo.svg"
