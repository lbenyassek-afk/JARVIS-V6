from __future__ import annotations

import importlib.util
import sys

from .config import load_config
from .secrets import get_secret
from .adapters import platform_registry
from .isolation import selected as selected_isolation


def snapshot(registry=None) -> list[dict]:
    cfg = load_config()
    voice_ready = (importlib.util.find_spec("sounddevice") is not None and
                   importlib.util.find_spec("speech_recognition") is not None)
    neural_voice = importlib.util.find_spec("edge_tts") is not None
    desktop_errors = list(getattr(registry, "errors", [])) if registry is not None else []
    desktop_actions = len(getattr(registry, "actions", {})) if registry is not None else 0
    companion_enabled = bool(cfg.get("companion", {}).get("enabled", False))
    gemini_ready = bool(get_secret("gemini_api_key"))
    desktop_ready = bool(desktop_actions and not desktop_errors)
    app_aware_ready = desktop_ready and sys.platform == "win32" and importlib.util.find_spec("pywinauto") is not None
    isolation = selected_isolation(cfg)
    adapters = platform_registry().status()
    return [
        {"id": "local_core", "state": "ready", "detail": "Bounded offline commands and local memory search"},
        {"id": "gemini", "state": "configured" if gemini_ready else "setup_required",
         "detail": "Key stored; five-stage live diagnostics available" if gemini_ready else "No Gemini key stored"},
        {"id": "fast_chat", "state": "ready" if gemini_ready else "setup_required",
         "detail": "Gemini fast model" if gemini_ready else "Connect Gemini"},
        {"id": "deep_research", "state": "ready" if gemini_ready else "setup_required",
         "detail": "Google Search grounding with cited sources" if gemini_ready else "Connect Gemini"},
        {"id": "multilingual", "state": "ready",
         "detail": "Automatic or selected language across chat, memory, speech and neural voice"},
        {"id": "memory", "state": "ready" if cfg["memory"].get("enabled", True) else "disabled",
         "detail": "Encrypted organized memory and relevant retrieval"},
        {"id": "voice_input", "state": "ready" if voice_ready else "unavailable",
         "detail": "Adaptive capture and confidence-aware transcription" if voice_ready else "Speech packages are missing"},
        {"id": "cinematic_voice", "state": "ready" if neural_voice else "fallback",
         "detail": "Edge neural voice installed" if neural_voice else "Windows voice fallback only"},
        {"id": "desktop_control", "state": "ready" if desktop_ready else "unavailable",
         "detail": f"{desktop_actions} allowlisted action(s)" if not desktop_errors else "; ".join(desktop_errors)},
        {"id": "natural_desktop", "state": "ready" if desktop_ready and gemini_ready else "setup_required",
         "detail": "/desktop control with structured planning" if gemini_ready else "Connect Gemini for multi-step planning"},
        {"id": "app_aware_desktop", "state": "ready" if app_aware_ready else "unavailable",
         "detail": "Named Windows controls and fields" if app_aware_ready else "Requires the Windows application build"},
        {"id": "desktop_routines", "state": "ready", "detail": "Encrypted reusable reviewed missions"},
        {"id": "verified_execution", "state": "ready",
         "detail": "Postcondition contracts, bounded retries and encrypted mission checkpoints"},
        {"id": "mission_graph", "state": "ready",
         "detail": "Validated dependency graph with cycle detection and blocked-step propagation"},
        {"id": "isolation", "state": "ready" if isolation.available else "unavailable",
         "detail": f"{isolation.name}: {isolation.detail}"},
        {"id": "typed_adapters", "state": "foundation",
         "detail": f"{sum(1 for item in adapters if item.available)} available typed adapter(s); arbitrary calls are blocked"},
        {"id": "reliability_benchmarks", "state": "ready",
         "detail": "Offline repeatable reliability, recovery, memory and security benchmark runner"},
        {"id": "appearance", "state": "ready", "detail": "Six themes, custom accent and five presence designs"},
        {"id": "workspaces", "state": "ready", "detail": "Personal, School and Business contexts"},
        {"id": "weather", "state": "ready" if cfg.get("plugins", {}).get("enabled", {}).get("weather", True) else "disabled",
         "detail": "Live location-aware weather"},
        {"id": "recovery_backup", "state": "ready", "detail": "Encrypted recovery state and password backups"},
        {"id": "companion_transport", "state": "enabled" if companion_enabled else "disabled",
         "detail": "Authenticated local inbox"},
        {"id": "iphone_interface", "state": "future", "detail": "Not implemented in Alpha 1"},
        {"id": "remote_relay", "state": "future", "detail": "No remote relay adapter installed"},
        {"id": "provider_plugins", "state": "foundation", "detail": "Manifest validation only; no external provider adapter installed"},
    ]
