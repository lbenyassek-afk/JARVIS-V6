from __future__ import annotations

from .config import load_config
from .secrets import get_secret


def snapshot(registry=None) -> tuple[dict, ...]:
    """The five product promises shown in priority order throughout the UI."""
    cfg = load_config()
    actions = len(getattr(registry, "actions", {})) if registry is not None else 0
    desktop_ready = bool(cfg.get("desktop", {}).get("enabled", True) and actions)
    connected = bool(get_secret("gemini_api_key"))
    voice = cfg.get("voice", {})
    return (
        {"id": "foundation", "label": "Extensible foundation", "ready": True,
         "detail": "Typed adapters, encrypted memory, mission graphs and benchmarks"},
        {"id": "registration", "label": "Gemini registration", "ready": connected,
         "detail": "Connected securely" if connected else "Setup required before Gemini intelligence"},
        {"id": "desktop", "label": "Desktop control", "ready": desktop_ready,
         "detail": f"{actions} bounded actions with approval and verification" if desktop_ready
                   else "Enable Desktop Control"},
        {"id": "speed", "label": "Fast intelligence", "ready": True,
         "detail": f"{cfg.get('assistant', {}).get('intelligence_profile', 'adaptive').title()} routing and local instant replies"},
        {"id": "voice", "label": "Responsive custom voice", "ready": True,
         "detail": f"{voice.get('voice_style', 'cinematic').title()} style · {voice.get('end_silence_ms', 500)} ms silence target"},
    )
