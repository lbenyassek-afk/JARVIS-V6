from __future__ import annotations

import importlib.util

from .crypto import open_text, seal
from .secrets import get_secret
from .capabilities import snapshot as capability_snapshot


def run(registry=None) -> list[dict]:
    rows = []
    def add(name, ok, detail): rows.append({"name": name, "ok": bool(ok), "detail": str(detail)})
    try:
        add("Encrypted storage", open_text(seal("health-check")) == "health-check", "Encryption round-trip passed")
    except Exception as exc:
        add("Encrypted storage", False, exc)
    add("Gemini connection", bool(get_secret("gemini_api_key")),
        "API key stored; run the live test in Settings" if get_secret("gemini_api_key") else "API key setup required")
    offline = importlib.util.find_spec("speech_recognition") is not None and importlib.util.find_spec("pocketsphinx") is not None
    add("Offline voice", offline, "Local English recognizer installed" if offline else "Offline voice package missing")
    try:
        import sounddevice as sd
        inputs = [item for item in sd.query_devices() if item.get("max_input_channels", 0) > 0]
        add("Microphone", bool(inputs), f"{len(inputs)} input device(s) detected")
    except Exception as exc:
        add("Microphone", False, exc)
    errors = list(getattr(registry, "errors", [])) if registry is not None else []
    add("Desktop skills", not errors, "Allowlisted skills loaded" if not errors else "; ".join(errors))
    for capability in capability_snapshot(registry):
        state = capability["state"]
        add("Capability: " + capability["id"].replace("_", " ").title(),
            state in ("ready", "configured", "enabled", "foundation"),
            f"{state}: {capability['detail']}")
    return rows
