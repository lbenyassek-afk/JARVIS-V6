from __future__ import annotations

SERVICE = "JARVIS-V6"
ALLOWED = {"gemini_api_key", "memory_encryption_key", "companion_token"}


def _keyring():
    import keyring
    return keyring


def get_secret(name: str) -> str:
    if name not in ALLOWED:
        raise ValueError("Unknown secret name")
    try:
        return _keyring().get_password(SERVICE, name) or ""
    except Exception:
        return ""


def set_secret(name: str, value: str) -> None:
    if name not in ALLOWED:
        raise ValueError("Unknown secret name")
    value = str(value or "").strip()
    if value:
        try:
            _keyring().set_password(SERVICE, name, value)
        except Exception:
            return
    else:
        try:
            _keyring().delete_password(SERVICE, name)
        except Exception:
            pass


def secret_status() -> dict:
    return {name: bool(get_secret(name)) for name in sorted(ALLOWED)}
