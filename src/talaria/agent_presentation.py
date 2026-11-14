"""User-scoped visual presentation preferences for the connected agent."""

AGENT_ICONS = {
    "spark",
    "orb",
    "bot",
    "comet",
    "neural",
    "beacon",
    "constellation",
    "wave",
    "prism",
}
DEFAULT_PRESENTATION = {"name": "Hermes", "icon": "orb"}


def validate_presentation(value):
    if not isinstance(value, dict):
        raise ValueError("presentation")
    name = value.get("name")
    icon = value.get("icon")
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
        raise ValueError("name")
    if not isinstance(icon, str) or icon not in AGENT_ICONS:
        raise ValueError("icon")
    return {"name": name.strip(), "icon": icon}
