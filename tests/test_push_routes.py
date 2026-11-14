def test_push_routes_and_worker(page, live_app):
    address, _, app = live_app
    config = page.request.get(f"{address}/api/push/config")
    assert config.status == 200
    assert len(config.json()["public_key"]) >= 80
    worker = page.request.get(f"{address}/push-sw.js")
    assert worker.status == 200
    assert "addEventListener('push'" in worker.text()
    assert "notificationclick" in worker.text()
    subscription = {
        "endpoint": "https://push.example/send/live",
        "keys": {"p256dh": "public", "auth": "secret"},
    }
    csrf = page.request.get(f"{address}/api/bootstrap").json()["csrf"]
    response = page.request.post(
        f"{address}/api/push/subscribe",
        data=subscription,
        headers={"X-Talaria-Request": "1", "X-CSRF-Token": csrf},
    )
    assert response.status == 200
    assert app.state.push.subscriptions("default") == [subscription]
