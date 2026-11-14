import httpx


def login(url, username, password):
    client = httpx.Client(base_url=url, headers={"X-Talaria-Request": "1"})
    response = client.post("/api/login", json={"username": username, "password": password})
    assert response.status_code == 200
    client.headers["X-CSRF-Token"] = client.get("/api/bootstrap").json()["csrf"]
    return client


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
