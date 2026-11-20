from pathlib import Path

import httpx

from .test_app import signed_in


def login(url, username, password):
    client = httpx.Client(base_url=url, headers={"X-Talaria-Request": "1"})
    response = client.post("/api/login", json={"username": username, "password": password})
    assert response.status_code == 200
    client.headers["X-CSRF-Token"] = client.get("/api/bootstrap").json()["csrf"]
    return client


def test_session_upload_stores_binary_file_and_metadata(live_app):
    url, _, _ = live_app
    sid = "d" * 32
    raw = b"\\x00\\x01binary\\xff"
    with signed_in(url) as client:
        response = client.post(
            f"/api/sessions/{sid}/upload",
            content=raw,
            headers={
                "X-Talaria-Filename": "report.bin",
                "Content-Type": "application/octet-stream",
            },
        )
    assert response.status_code == 201
    metadata = response.json()
    assert metadata["path"].endswith(f"uploads/{sid}/report.bin")
    assert metadata["path"].startswith("/") or ":/" in metadata["path"]
    stored = Path(metadata["path"])
    assert stored.read_bytes() == raw
    assert metadata["size"] == len(raw)


def test_session_upload_delete_removes_only_the_named_file(live_app):
    url, _, _ = live_app
    sid = "f" * 32
    headers = {"X-Talaria-Filename": "cancel-me.bin", "Content-Type": "application/octet-stream"}
    with signed_in(url) as client:
        uploaded = client.post(f"/api/sessions/{sid}/upload", content=b"bytes", headers=headers)
        assert uploaded.status_code == 201
        path = Path(uploaded.json()["path"])
        assert path.exists()
        deleted = client.delete(
            f"/api/sessions/{sid}/upload",
            headers={"X-Talaria-Filename": "cancel-me.bin"},
        )
        assert deleted.status_code == 200
        assert not path.exists()
        assert path.parent.exists()


def test_session_upload_rejects_unsafe_filename(live_app):
    url, _, _ = live_app
    with signed_in(url) as client:
        response = client.post(
            f"/api/sessions/{'e' * 32}/upload",
            content=b"data",
            headers={"X-Talaria-Filename": "../secret.txt", "Content-Type": "text/plain"},
        )
    assert response.status_code == 400


def test_regular_users_do_not_receive_hermes_readiness_alerts(live_app):
    url, peer, _ = live_app
    peer.discovery_overrides["/health/detailed"] = (
        {
            "status": "degraded",
            "readiness": {
                "status": "degraded",
                "checks": {
                    "disk": {"status": "degraded", "used_percent": 94.5},
                    "model": {"status": "degraded", "detail": "Model unavailable"},
                },
            },
        },
        200,
    )
    admin = login(url, "admin", "test-password")
    admin_response = admin.get("/api/readiness")
    assert admin_response.json()["status"] == "degraded"
    assert {issue["name"] for issue in admin_response.json()["issues"]} == {"disk", "model"}
    created = admin.post(
        "/api/users",
        json={
            "username": "quiet-user",
            "password": "quiet-password",
            "role": "user",
            "profile_id": "default",
        },
    )
    assert created.status_code == 201
    user = login(url, "quiet-user", "quiet-password")
    response = user.get("/api/readiness")
    assert response.json() == {"status": "ok", "issues": []}
    agent_response = user.get("/api/agent")
    assert agent_response.json()["readiness"] == {"status": "ok", "issues": []}
    assert "94.5" not in response.text and "Model unavailable" not in response.text
    assert "94.5" not in agent_response.text and "Model unavailable" not in agent_response.text
    admin.close()
    user.close()


def test_cron_reply_promotes_and_deletes_source(live_app):
    url, peer, _ = live_app
    peer.extension = {"session_fork": True}
    source = "a" * 32
    peer.sessions[source] = {"id": source, "title": "Nightly report", "source": "cron"}
    peer.messages[source] = [
        {"id": 1, "role": "user", "content": "Run the nightly report"},
        {"id": 2, "role": "assistant", "content": "Report complete."},
    ]
    with signed_in(url) as client:
        response = client.post(f"/api/sessions/{source}/reply", json={})
    assert response.status_code == 201
    branch = response.json()
    assert branch["id"] in peer.sessions
    assert branch["parent_session_id"] == source
    assert branch["source"] == "api_server"
    assert source not in peer.sessions
    assert ("DELETE", f"/api/sessions/{source}", {}) in peer.calls


def test_cron_reply_rejects_regular_sessions(live_app):
    url, peer, _ = live_app
    sid = "b" * 32
    peer.sessions[sid] = {"id": sid, "title": "Normal", "source": "api_server"}
    peer.messages[sid] = [{"id": 1, "role": "assistant", "content": "Ready."}]
    with signed_in(url) as client:
        response = client.post(f"/api/sessions/{sid}/reply", json={})
    assert response.status_code == 409
    assert sid in peer.sessions


def test_admin_and_user_have_separate_roles_and_sessions(live_app):
    url, _, _ = live_app
    admin = login(url, "admin", "test-password")
    created = admin.post(
        "/api/users",
        json={
            "username": "alice",
            "password": "alice-password",
            "role": "user",
            "profile_id": "default",
        },
    )
    assert created.status_code == 201
    admin_session = admin.post("/api/sessions", json={"title": "Admin private"}).json()["id"]
    user = login(url, "alice", "alice-password")
    assert user.get("/api/users").status_code == 403
    user_session = user.post("/api/sessions", json={"title": "Alice private"})
    assert user_session.status_code == 201
    assert user_session.json()["id"] != admin_session
    listed = user.get("/api/sessions").json()["data"]
    assert {row["id"] for row in listed} == {admin_session, user_session.json()["id"]}
    assert user.get("/api/sessions?talaria_profile=" + "a" * 32).status_code == 403
    assert admin.get("/api/users").json()["users"][1]["username"] == "alice"
    admin.close()
    user.close()
