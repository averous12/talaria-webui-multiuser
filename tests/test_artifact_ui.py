"""Assistant MEDIA artifacts appear as a skeleton, then a durable link."""

import base64
from urllib.parse import urljoin

import pytest
from playwright.sync_api import expect

from .conftest import wait_for_store
from .test_app import signed_in

pytestmark = pytest.mark.browser


def test_media_artifact_skeleton_becomes_download_link(page, live_app):
    url, peer, _ = live_app
    sid = "artifact-session"
    peer.sessions[sid] = {"id": sid, "title": "Artifact", "source": "api_server", "pinned": False}
    peer.messages[sid] = [
        {"id": 11, "role": "user", "content": "Make a report"},
        {"id": 12, "role": "assistant", "content": "Here is the report:\nMEDIA:/safe/report.pdf"},
    ]
    content = b"%PDF-1.4 persisted test artifact"
    peer.discovery_overrides[f"/talaria/v1/sessions/{sid}/12/artifact"] = (
        {
            "name": "report.pdf",
            "mime": "application/pdf",
            "data": base64.b64encode(content).decode("ascii"),
        },
        200,
    )
    with signed_in(url) as client:
        assert client.get(f"/api/sessions/{sid}").status_code == 200

    page.goto(url)
    wait_for_store(page, "s => !!s.connected")
    page.get_by_text("Artifact", exact=True).click()

    peer.artifact_delay = 0.35
    skeleton = page.locator(".artifact-skeleton")
    expect(skeleton).to_be_visible(timeout=5000)
    assert skeleton.locator(".artifact-skeleton-lines i").count() == 2
    assert skeleton.locator(".artifact-skeleton-button").count() == 1

    link = page.get_by_role("link", name="report.pdf", exact=False)
    expect(link).to_be_visible(timeout=10000)
    assert link.get_attribute("href", timeout=5000).startswith("/api/artifacts/")


def test_media_image_renders_through_existing_image_viewer(page, live_app):
    url, peer, _ = live_app
    sid = "image-artifact-session"
    path = "C:/Users/avero/Pictures/citrus_stickers/yuzu_smile.png"
    peer.sessions[sid] = {
        "id": sid,
        "title": "Image artifact",
        "source": "api_server",
        "pinned": False,
    }
    peer.messages[sid] = [
        {"id": 21, "role": "assistant", "content": f"Here it is.\nMEDIA:{path}"},
    ]
    image = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )
    peer.discovery_overrides[f"/talaria/v1/sessions/{sid}/21/artifact"] = (
        {
            "name": "yuzu_smile.png",
            "mime": "image/png",
            "data": base64.b64encode(image).decode("ascii"),
        },
        200,
    )
    with signed_in(url) as client:
        assert client.get(f"/api/sessions/{sid}").status_code == 200

    page.goto(url)
    wait_for_store(page, "s => !!s.connected")
    page.get_by_text("Image artifact", exact=True).click()
    image_node = page.locator(".message-image img[alt='yuzu_smile.png']")
    expect(image_node).to_be_visible(timeout=10000)
    assert image_node.get_attribute("src", timeout=5000).startswith("/api/artifacts/")
    assert page.locator(".artifact-error").count() == 0
    response = page.request.get(urljoin(url, image_node.get_attribute("src")))
    assert response.status == 200
    assert response.headers["content-type"].startswith("image/png")
    assert response.headers["content-disposition"].startswith("inline")
