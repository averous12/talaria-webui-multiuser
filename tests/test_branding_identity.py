from talaria.metadata import agent_identity


def test_branding_agent_name_mode_overrides_live_identity():
    caps = {"agent": {"name": "Hermes Live"}}
    extended = {"agent": {"name": "Extension Agent"}}
    brand = {"agent_name": "Aurora", "agent_name_mode": "brand"}
    assert agent_identity(caps, extended, brand) == {
        "name": "Aurora", "name_source": "branding"
    }


def test_hermes_identity_remains_authoritative_by_default():
    assert agent_identity(
        {"agent": {"name": "Hermes Live"}},
        {},
        {"agent_name": "Aurora", "agent_name_mode": "hermes"},
    )["name"] == "Hermes Live"
