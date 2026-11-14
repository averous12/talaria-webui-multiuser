from .test_app import signed_in


def test_agent_presentation_is_user_scoped_and_persistent(live_app):
    url, _, app = live_app
    with signed_in(url) as client:
        response = client.get("/api/bootstrap")
        assert response.status_code == 200
        assert response.json()["agent_presentation"] == {"name": "Hermes", "icon": "orb"}
        updated = client.patch(
            "/api/agent/presentation",
            json={"name": "Starlight", "icon": "spark"},
        )
        assert updated.status_code == 200
        assert updated.json() == {"name": "Starlight", "icon": "spark"}
        assert client.get("/api/bootstrap").json()["agent_presentation"] == {
            "name": "Starlight", "icon": "spark"
        }
    assert app.state.users.get(1)["presentation"] == {"name": "Starlight", "icon": "spark"}


def test_agent_presentation_rejects_unknown_icon_and_blank_name(live_app):
    with signed_in(live_app[0]) as client:
        assert client.patch(
            "/api/agent/presentation", json={"name": "", "icon": "spark"}
        ).status_code == 400
        assert client.patch(
            "/api/agent/presentation", json={"name": "Juniper", "icon": "unknown"}
        ).status_code == 400
