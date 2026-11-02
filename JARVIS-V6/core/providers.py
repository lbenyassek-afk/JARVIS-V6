from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Provider:
    provider_id: str
    name: str
    installed: bool
    local: bool = False


CATALOG = (
    Provider("gemini", "Google Gemini", True),
    Provider("local", "Local model", False, True),
    Provider("openai", "OpenAI", False),
    Provider("anthropic", "Anthropic", False),
)


def select(config: dict, mode: str = "chat") -> Provider:
    providers = config.get("providers", {})
    enabled = providers.get("enabled", {})
    preferred = str(providers.get("primary", "gemini"))
    installed = {item.provider_id: item for item in CATALOG if item.installed}
    if preferred in installed and enabled.get(preferred, preferred == "gemini"):
        return installed[preferred]
    for provider_id in providers.get("fallback_order", ["gemini"]):
        if provider_id in installed and enabled.get(provider_id, provider_id == "gemini"):
            return installed[provider_id]
    return installed["gemini"]
