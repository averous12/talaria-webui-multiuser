import json

import pytest

from talaria.push import PushStore


def test_push_store_persists_subscriptions_and_public_key(tmp_path):
    store = PushStore(tmp_path / "config.json")
    subscription = {
        "endpoint": "https://push.example/send/1",
        "keys": {"p256dh": "public", "auth": "secret"},
    }
    store.subscribe("profile-a", subscription)
    reopened = PushStore(tmp_path / "config.json")
    assert reopened.public_key == store.public_key
    assert reopened.subscriptions("profile-a") == [subscription]
    assert reopened.subscriptions("profile-b") == []


@pytest.mark.asyncio
async def test_push_store_dispatches_only_completion_and_clarification(monkeypatch, tmp_path):
    store = PushStore(tmp_path / "config.json")
    sent = []

    def fake_webpush(subscription, data, **kwargs):
        sent.append((subscription, json.loads(data), kwargs))

    monkeypatch.setattr("talaria.push.webpush", fake_webpush)
    store.subscribe("profile-a", {
        "endpoint": "https://push.example/send/1",
        "keys": {"p256dh": "public", "auth": "secret"},
    })
    await store.notify("profile-a", "run-1", {"event": "message.delta", "delta": "x"})
    await store.notify("profile-a", "run-1", {"event": "run.completed"})
    await store.notify("profile-a", "run-1", {
        "event": "talaria.clarification.request",
        "request_id": "question-1",
        "question": "Which one?",
    })
    assert [payload for _, payload, _ in sent] == [
        {"kind": "completed", "run_id": "run-1", "url": "?session="},
        {"kind": "clarification", "run_id": "run-1", "question": "Which one?"},
    ]
