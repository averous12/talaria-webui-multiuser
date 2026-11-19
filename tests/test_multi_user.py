import httpx


def login(url, username, password):
    client = httpx.Client(base_url=url, headers={"X-Talaria-Request": "1"})
    response = client.post("/api/login", json={"username": username, "password": password})
    assert response.status_code == 200
    client.headers["X-CSRF-Token"] = client.get("/api/bootstrap").json()["csrf"]
    return client


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
