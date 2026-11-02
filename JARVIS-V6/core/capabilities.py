from __future__ import annotations

import importlib.util

from .config import load_config
from .secrets import get_secret


def snapshot(registry=None) -> list[dict]:
    cfg = load_config()
    voice_ready = (importlib.util.find_spec("sounddevice") is not None and
                   importlib.util.find_spec("speech_recognition") is not None)
    neural_voice = importlib.util.find_spec("edge_tts") is not None
    desktop_errors = list(getattr(registry, "errors", [])) if registry is not None else []
    desktop_actions = len(getattr(registry, "actions", {})) if registry is not None else 0
    companion_enabled = bool(cfg.get("companion", {}).get("enabled", False))
    return [
        {"id": "local_core", "state": "ready", "detail": "Bounded offline commands and local memory search"},
        {"id": "gemini", "state": "configured" if get_secret("gemini_api_key") else "setup_required",
         "detail": "Key stored; live test is available in Settings" if get_secret("gemini_api_key") else "No Gemini key stored"},
        {"id": "voice_input", "state": "ready" if voice_ready else "unavailable",
         "detail": "Speech packages installed" if voice_ready else "Speech packages are missing"},
        {"id": "cinematic_voice", "state": "ready" if neural_voice else "fallback",
         "detail": "Edge neural voice installed" if neural_voice else "Windows voice fallback only"},
        {"id": "desktop_control", "state": "ready" if desktop_actions and not desktop_errors else "unavailable",
         "detail": f"{desktop_actions} allowlisted action(s)" if not desktop_errors else "; ".join(desktop_errors)},
        {"id": "companion_transport", "state": "enabled" if companion_enabled else "disabled",
         "detail": "Authenticated local inbox"},
        {"id": "iphone_interface", "state": "future", "detail": "Not implemented in Alpha 1"},
        {"id": "remote_relay", "state": "future", "detail": "No remote relay adapter installed"},
        {"id": "provider_plugins", "state": "foundation", "detail": "Manifest validation only; no external provider adapter installed"},
    ]
