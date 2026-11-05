from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path


APP_DIR = Path(os.getenv("APPDATA", Path.home())) / "JARVIS-V6"
CONFIG_PATH = APP_DIR / "config.json"

DEFAULTS = {
    "assistant": {
        "name": "JARVIS",
        "user_name": "Sir",
        "language": "auto",
        "tone": "warm_calm",
        "response_length": "balanced",
        "intelligence_profile": "adaptive",
        "serious_mode": False,
        "quick_local_replies": True,
        "daily_focus": "",
        "manager_enabled": True,
        "active_mode": "personal",
    },
    "memory": {
        "enabled": True,
        "prompt_budget": 1800,
        "chat_history_enabled": True,
        "chat_context_messages": 24,
        "organized_schema": 2,
        "automatic_capture": "important_only",
        "retention": "user_controlled",
    },
    "llm": {
        "provider": "gemini",
        "fast_model": "gemini-3.5-flash-lite",
        "smart_model": "gemini-3.5-flash-lite",
    },
    "providers": {
        "primary": "gemini",
        "fallback_order": ["gemini"],
        "enabled": {"gemini": True, "local": False, "openai": False, "anthropic": False},
    },
    "voice": {
        "speak_replies": True,
        "always_listening": True,
        "english_only": False,
        "input_engine": "fast_free",
        "activation_mode": "natural",
        "output_engine": "edge_free",
        "input_device": "",
        "session_timeout": 180,
        "wake_phrase": "hey jarvis",
        "wake_phrases": ["hey jarvis", "jarvis"],
        "end_silence_ms": 500,
        "adaptive_silence": True,
        "minimum_speech_ms": 150,
        "max_utterance_seconds": 20,
        "speech_rate": -1,
        "speech_pitch": -4,
        "speech_volume": 90,
        "voice_style": "cinematic",
        "british_voice": "en-GB-ThomasNeural",
        "profile_version": 3,
        "recognition_profile_version": 4,
        "output_profile_version": 5,
        "multilingual_profile_version": 1,
        "capture_profile_version": 4,
    },
    "desktop": {
        "enabled": True,
        "persistent_access": True,
        "access_profile_version": 2,
        "automatic_approved_actions": True,
        "screen_observation": True,
        "screen_interval_seconds": 2,
        "emergency_hotkey": "<ctrl>+<shift>+q",
        "step_delay": 0.35,
        "max_steps": 20,
        "execution_mode": "plan_then_execute",
        "verify_results": True,
        "verification_retries": 1,
        "verification_settle_seconds": 0.12,
        "checkpoint_missions": True,
        "isolation_profile": "host_reviewed",
    },
    "permissions": {
        "low_risk": "automatic",
        "sensitive": "always_ask",
        "actions": {},
        "applications": {},
    },
    "interface": {
        "visual_mode": "orb",
        "presence_profile_version": 1,
        "window_mode": "restore",
        "last_window_mode": "normal",
        "appearance_profile": "obsidian",
        "accent_color": "",
        "appearance_profile_version": 1,
        "adaptive_layout": True,
        "motion_profile": "adaptive",
        "reduced_motion": False,
    },
    "weather": {
        "location": "",
        "automatic_location": True,
        "units": "metric",
    },
    "planning": {
        "focus_session_minutes": 50,
        "max_daily_priorities": 3,
        "daily_review": True,
    },
    "plugins": {
        "enabled": {
            "desktop": True,
            "weather": True,
            "project_manager": True,
            "chatgpt": False,
            "n8n": False,
        },
    },
    "local_core": {
        "enabled": True,
        "offline_commands": True,
        "local_search": True,
        "model_runtime": "rules",
    },
    "companion": {
        "enabled": False,
        "connection_mode": "local",
        "bind": "127.0.0.1",
        "port": 8765,
        "remote_relay": False,
    },
    "updates": {
        "automatic_check": True,
        "channel": "stable",
        "repository": "lbenyassek-afk/JARVIS-V6",
    },
    "privacy": {
        "store_audio": False,
        "store_transcripts": True,
        "store_screen_captures": False,
    },
    "onboarding": {
        "diagnostics_run": False,
    },
}


def _merge(base: dict, saved: dict) -> dict:
    out = deepcopy(base)
    for key, value in (saved or {}).items():
        if key not in out:
            continue
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        elif key in out:
            out[key] = value
    return out


def load_config() -> dict:
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    merged = _merge(DEFAULTS, data if isinstance(data, dict) else {})
    # Model routing is owned by the application so old settings cannot keep a
    # slower or retired model after an upgrade.
    merged["llm"] = deepcopy(DEFAULTS["llm"])
    # Migrate the original voice profile to the cleaner premium voice once.
    # Users can still select any available neural voice in Settings.
    saved_voice = data.get("voice", {}) if isinstance(data, dict) else {}
    if (int(saved_voice.get("profile_version", 1)) < 2 and
            merged["voice"].get("british_voice") == "en-GB-RyanNeural"):
        merged["voice"]["british_voice"] = "en-GB-ThomasNeural"
    if (int(saved_voice.get("capture_profile_version", 1)) < 2 and
            int(merged["voice"].get("end_silence_ms", 700)) == 700):
        merged["voice"]["end_silence_ms"] = 550
    if int(saved_voice.get("capture_profile_version", 1)) < 4:
        merged["voice"]["adaptive_silence"] = True
        merged["voice"]["minimum_speech_ms"] = 150
        merged["voice"]["max_utterance_seconds"] = 20
        merged["voice"]["capture_profile_version"] = 4
    # V5.0/V5.1 defaulted to PocketSphinx, which is fully offline but often
    # misses natural conversational speech. Move that old default to the
    # faster free recognizer while preserving an explicit Gemini selection.
    if int(saved_voice.get("recognition_profile_version", 1)) < 4:
        if saved_voice.get("input_engine", "offline") == "offline":
            merged["voice"]["input_engine"] = "fast_free"
        merged["voice"]["activation_mode"] = "natural"
        merged["voice"]["recognition_profile_version"] = 4
    if int(saved_voice.get("output_profile_version", 1)) < 5:
        if saved_voice.get("british_voice", "en-GB-ThomasNeural") in (
                "en-GB-ThomasNeural", "en-GB-RyanNeural"):
            merged["voice"]["british_voice"] = "en-GB-ThomasNeural"
        merged["voice"]["speech_rate"] = -1
        merged["voice"]["speech_pitch"] = -4
        merged["voice"]["output_profile_version"] = 5
    if int(saved_voice.get("multilingual_profile_version", 0)) < 1:
        # Previous versions silently rejected non-English Gemini speech. V6 now
        # follows the configured language, or the speaker when set to Automatic.
        merged["voice"]["english_only"] = False
        merged["voice"]["multilingual_profile_version"] = 1
    saved_desktop = data.get("desktop", {}) if isinstance(data, dict) else {}
    if int(saved_desktop.get("access_profile_version", 1)) < 2:
        merged["desktop"]["enabled"] = True
        merged["desktop"]["persistent_access"] = True
        merged["plugins"]["enabled"]["desktop"] = True
    # V6 introduces a lighter presence panel with five selectable identities.
    # Apply the new Orb default once while preserving choices made afterwards.
    saved_interface = data.get("interface", {}) if isinstance(data, dict) else {}
    if int(saved_interface.get("presence_profile_version", 0)) < 1:
        merged["interface"]["visual_mode"] = "orb"
        merged["interface"]["presence_profile_version"] = 1
    return merged


def save_config(config: dict) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    temp = CONFIG_PATH.with_suffix(".tmp")
    temp.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
    temp.replace(CONFIG_PATH)
    try:
        os.chmod(CONFIG_PATH, 0o600)
    except OSError:
        pass
