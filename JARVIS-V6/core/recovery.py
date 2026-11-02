from __future__ import annotations

import json
import threading

from . import config
from .crypto import open_text, seal

_LOCK = threading.Lock()


def _path():
    return config.APP_DIR / "recovery.state"


def load() -> dict:
    try:
        data = json.loads(open_text(_path().read_text(encoding="utf-8")))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save(state: dict, clean_exit: bool = False) -> None:
    with _LOCK:
        config.APP_DIR.mkdir(parents=True, exist_ok=True)
        payload = dict(state); payload["clean_exit"] = bool(clean_exit)
        temporary = _path().with_suffix(".tmp")
        temporary.write_text(seal(json.dumps(payload, separators=(",", ":"))), encoding="utf-8")
        temporary.replace(_path())


def begin() -> dict:
    previous = load()
    current = {key: value for key, value in previous.items() if key != "clean_exit"}
    save(current, False)
    return previous if previous and not previous.get("clean_exit", True) else {}
