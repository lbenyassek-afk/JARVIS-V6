from __future__ import annotations

import os
import threading

from cryptography.fernet import Fernet, InvalidToken

from . import config
from .secrets import get_secret, set_secret


PREFIX = "J5E1:"
_KEY_LOCK = threading.Lock()
_KEY_CACHE: tuple[str, bytes] | None = None


def _fallback_path():
    return config.APP_DIR / ".memory.key"


def _key() -> bytes:
    global _KEY_CACHE
    path = _fallback_path(); cache_id = str(path.resolve())
    with _KEY_LOCK:
        if _KEY_CACHE and _KEY_CACHE[0] == cache_id:
            return _KEY_CACHE[1]
        value = get_secret("memory_encryption_key")
        if value:
            key = value.encode("ascii"); _KEY_CACHE = (cache_id, key); return key
        try:
            saved = path.read_text(encoding="ascii").strip()
            if saved:
                key = saved.encode("ascii"); _KEY_CACHE = (cache_id, key); return key
        except OSError:
            pass
        generated = Fernet.generate_key()
        set_secret("memory_encryption_key", generated.decode("ascii"))
        if not get_secret("memory_encryption_key"):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(generated)
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
        _KEY_CACHE = (cache_id, generated)
        return generated


def encrypted(value: str) -> bool:
    return str(value).startswith(PREFIX)


def seal(value: str) -> str:
    if encrypted(value):
        return str(value)
    token = Fernet(_key()).encrypt(str(value).encode("utf-8")).decode("ascii")
    return PREFIX + token


def open_text(value: str) -> str:
    text = str(value)
    if not encrypted(text):
        return text
    try:
        return Fernet(_key()).decrypt(text[len(PREFIX):].encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, UnicodeError) as exc:
        raise ValueError("Encrypted local data could not be unlocked.") from exc
