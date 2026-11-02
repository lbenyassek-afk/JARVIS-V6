from __future__ import annotations

from dataclasses import dataclass

from .config import load_config, save_config


@dataclass(frozen=True)
class Plugin:
    plugin_id: str
    name: str
    description: str
    permissions: str
    installed: bool = True


CATALOG = (
    Plugin("desktop", "Desktop Control", "Approved applications, typing, clipboard, keys and reviewed task plans.",
           "Keyboard, mouse, clipboard and approved applications"),
    Plugin("weather", "Live Weather", "Current conditions and daily forecast for the selected location.",
           "Internet and optional IP-based location"),
    Plugin("project_manager", "Project & Life Manager", "Planning templates, priorities, focus sessions and reviews.",
           "Local workspace records"),
    Plugin("email_calendar", "Email & Calendar", "Future approved mail, calendar and scheduling adapter.",
           "Not installed — will require account authorization and action approval", False),
    Plugin("notion", "Notion", "Future project and knowledge workspace connector.",
           "Not installed — will require a scoped Notion integration", False),
    Plugin("etsy_business", "Etsy & Business Research", "Future Etsy research and business workflow adapter.",
           "Not installed — publishing and account actions will require approval", False),
    Plugin("chatgpt", "ChatGPT Connector", "Reserved connector for a future optional OpenAI provider adapter.",
           "Not installed — would require a separate API key", False),
    Plugin("anthropic", "Anthropic Provider", "Reserved provider slot for a future optional Claude adapter.",
           "Not installed — would require a separate API key and explicit activation", False),
    Plugin("local_ai", "Local AI Provider", "Reserved provider slot for an offline local model runtime.",
           "Not installed — model download and hardware check required", False),
    Plugin("n8n", "n8n / NHM Connector", "Reserved connector for approved workflow automation.",
           "Not installed — would require a secured adapter", False),
)


def enabled(plugin_id: str) -> bool:
    return bool(load_config().get("plugins", {}).get("enabled", {}).get(plugin_id, False))


def set_enabled(states: dict[str, bool]) -> None:
    installed = {plugin.plugin_id for plugin in CATALOG if plugin.installed}
    cfg = load_config()
    for plugin_id, state in states.items():
        if plugin_id in installed:
            cfg["plugins"]["enabled"][plugin_id] = bool(state)
    cfg["desktop"]["enabled"] = bool(cfg["plugins"]["enabled"].get("desktop", False))
    save_config(cfg)
