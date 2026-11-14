from contextlib import contextmanager

import httpx

from talaria.push import _payload


@contextmanager
def signed_in(url):
    client = httpx.Client(base_url=url, headers={"X-Talaria-Request": "1"})
    assert client.post("/api/login", json={"password": "test-password"}).status_code == 200
    client.headers["X-CSRF-Token"] = client.get("/api/bootstrap").json()["csrf"]
    try:
        yield client
    finally:
        client.close()




def test_kenari_budget_routes_proxy_authenticated_payload(live_app):
    url, peer, _ = live_app
    peer.discovery_overrides["/kenari/v1/budget"] = (
        {"schema": 1, "status": "complete", "currency": "IDR"}, 200
    )
    peer.discovery_overrides["/kenari/v1/pricing"] = (
        {"schema": 1, "models": [{"id": "kenari-test"}]}, 200
    )
    peer.discovery_overrides["/kenari/v1/estimate"] = ({"schema": 1, "estimated_idr": 42}, 200)
    with signed_in(url) as client:
        assert client.get("/api/kenari/budget").json()["status"] == "complete"
        assert client.get("/api/kenari/pricing").json()["models"][0]["id"] == "kenari-test"
        estimate = client.post(
            "/api/kenari/estimate",
            json={"model": "kenari-test", "input_tokens": 10},
        )
        assert estimate.status_code == 200
        assert estimate.json()["estimated_idr"] == 42
    assert ("GET", "/kenari/v1/budget", {}) in peer.calls
    assert ("GET", "/kenari/v1/pricing", {}) in peer.calls
    assert ("POST", "/kenari/v1/estimate", {}) in peer.calls


def test_kenari_estimate_rejects_invalid_token_counts(live_app):
    url, peer, _ = live_app
    with signed_in(url) as client:
        response = client.post(
            "/api/kenari/estimate",
            json={"model": "kenari-test", "input_tokens": -1},
        )
    assert response.status_code == 400
    assert not any(path == "/kenari/v1/estimate" for _, path, _ in peer.calls)


def test_kenari_routes_require_talaria_login(live_app):
    url, _, _ = live_app
    for path in ("/api/kenari/budget", "/api/kenari/pricing"):
        assert httpx.get(url + path).status_code == 401




def test_admin_budget_percentages_and_new_run_block(live_app):
    url, peer, _ = live_app
    with signed_in(url) as admin:
        created = admin.post(
            "/api/users",
            json={
                "username": "budget-user",
                "password": "budget-password",
                "role": "user",
                "profile_id": "default",
            },
        )
        assert created.status_code == 201
        user_id = created.json()["id"]
        assert admin.patch(
            f"/api/users/{user_id}", json={"monthly_budget_idr": 4}
        ).status_code == 200
        sid = admin.post("/api/sessions", json={"title": "Budget session"}).json()["id"]
        peer.sessions[sid]["actual_cost_micro_idr"] = 5_000_000
    user = httpx.Client(base_url=url, headers={"X-Talaria-Request": "1"})
    try:
        assert user.post(
            "/api/login",
            json={"username": "budget-user", "password": "budget-password"},
        ).status_code == 200
        user.headers["X-CSRF-Token"] = user.get("/api/bootstrap").json()["csrf"]
        budget = user.get("/api/budget").json()
        assert budget["blocked"] is True
        assert budget["weekly_percent"] == 100
        assert budget["monthly_percent"] == 100
        assert "monthly_budget_micro_idr" not in user.get("/api/bootstrap").json()["user"]
        blocked = user.post("/api/runs", json={"session_id": sid, "input": "new message"})
        assert blocked.status_code == 429
        assert blocked.json()["code"] == "budget_exceeded"
    finally:
        user.close()

    url, _, _ = live_app
    assert httpx.get(url + "/api/sessions").status_code == 401
    with signed_in(url) as client:
        assert client.get("/api/sessions").status_code == 200
        assert (
            client.post(
                "/api/sessions",
                json={"title": "Unsafe"},
                headers={"Origin": "https://untrusted.example"},
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/sessions", json={"title": "Unsafe"}, headers={"X-CSRF-Token": "wrong"}
            ).status_code
            == 403
        )
        assert "test-hermes-key" not in client.get("/api/connection").text
        assert "frame-ancestors 'none'" in client.get("/").headers["Content-Security-Policy"]


def test_push_service_worker_is_valid_javascript(live_app):
    url, _, _ = live_app
    response = httpx.get(url + "/push-sw.js")
    assert response.status_code == 200
    script = response.text
    assert response.headers["service-worker-allowed"] == "/"
    assert "\\\\n" not in script
    assert "self.registration.showNotification" in script


def test_push_completion_payload_contains_response_snippet():
    output = "**Final answer**\n\n" + ("x" * 300)
    payload = _payload("run-1", {"event": "run.completed", "output": output}, "session-1")
    assert payload["kind"] == "completed"
    assert payload["snippet"].startswith("Final answer x")
    assert len(payload["snippet"]) == 241
    assert payload["snippet"].endswith("…")
    assert "\\n" not in payload["snippet"]


def test_push_completion_payload_falls_back_without_output():
    assert "snippet" not in _payload("run-1", {"event": "run.completed"})


def test_session_lifecycle(live_app):
    with signed_in(live_app[0]) as client:
        created = client.post("/api/sessions", json={"title": "A thought"})
        sid = created.json()["id"]
        assert created.status_code == 201
        assert (
            client.patch(f"/api/sessions/{sid}", json={"title": "A better thought"}).status_code
            == 200
        )
        live_app[1].messages[sid] = [{"id": 1, "role": "user", "content": "A thought"}]
        fork = client.post(f"/api/sessions/{sid}/fork", json={"title": "A branch"}).json()
        assert fork["id"] != sid
        assert len(client.get("/api/sessions").json()["data"]) == 2
        assert client.delete(f"/api/sessions/{sid}").status_code == 200
        assert client.get(f"/api/sessions/{sid}").status_code == 404


def test_idempotent_run_and_replay(live_app):
    url, peer, _ = live_app
    with signed_in(url) as client:
        sid = client.post("/api/sessions", json={"title": "Run"}).json()["id"]
        payload = {"session_id": sid, "input": "Hello", "request_id": "test-request"}
        rid = client.post("/api/runs", json=payload).json()["run_id"]
        assert client.post("/api/runs", json=payload).json()["run_id"] == rid
        first = client.get(f"/api/runs/{rid}/events").text
        assert '"event":"message.delta"' in first and '"event":"run.completed"' in first
        replay = client.get(f"/api/runs/{rid}/events", headers={"Last-Event-ID": "1"}).text
        assert "id: 1\n" not in replay
        assert '"event":"run.completed"' in replay
        # A page resumes a parked run where it stopped; a reconnect's own cursor wins.
        resumed = client.get(f"/api/runs/{rid}/events?after=2").text
        assert "id: 2\n" not in resumed and "id: 3\n" in resumed
        cursor = {"Last-Event-ID": "3"}
        assert "id: 3\n" not in client.get(f"/api/runs/{rid}/events?after=1", headers=cursor).text
        assert client.get(f"/api/runs/{rid}/events?after=soon").status_code == 400
        assert len(peer.runs) == 1
