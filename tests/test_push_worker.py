from starlette.requests import Request

from talaria.push import PushStore, service_worker


def test_service_worker_contains_push_and_click_handlers(tmp_path):
    store = PushStore(tmp_path / "config.json")
    scope = {
        "type": "http", "path": "/push-sw.js", "headers": [], "query_string": b"",
        "app": type("App", (), {"state": type("State", (), {
            "settings": type("Settings", (), {"base_path": ""})(),
            "push": store,
        })()})(),
    }
    request = Request(scope)
    response = service_worker(request)
    body = response.body
    assert b"addEventListener('push'" in body
    assert b"notificationclick" in body
