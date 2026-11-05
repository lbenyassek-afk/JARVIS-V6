from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone

from . import config
from .crypto import open_text, seal
from .memory import sensitive
from .tasks import Step


def _path():
    return config.APP_DIR / "desktop_routines.json"


def load() -> list[dict]:
    try:
        data = json.loads(open_text(_path().read_text(encoding="utf-8")))
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data[:30]
            if isinstance(item, dict) and isinstance(item.get("steps"), list)]


def _write(routines: list[dict]) -> None:
    path = _path(); path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    payload = json.dumps(routines, ensure_ascii=False, separators=(",", ":"))
    temporary.write_text(seal(payload), encoding="utf-8")
    temporary.replace(path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def save(name: str, goal: str, steps: list[Step]) -> None:
    name = " ".join(str(name).split())[:80]
    goal = " ".join(str(goal).split())[:300]
    if not name or not re.fullmatch(r"[\w .&()'\-]{1,80}", name, re.UNICODE):
        raise ValueError("Use a short routine name with letters, numbers, spaces or dashes.")
    steps = list(steps)
    if not steps or len(steps) > 20:
        raise ValueError("A routine must contain 1–20 steps.")
    serialized = [{"action": str(step.action)[:60], "value": str(step.value)[:4000]} for step in steps]
    private_text = json.dumps(serialized, ensure_ascii=False)
    if sensitive(name, goal + " " + private_text):
        raise ValueError("Credentials and secrets cannot be saved inside routines.")
    routines = [item for item in load() if str(item.get("name", "")).casefold() != name.casefold()]
    routines.insert(0, {
        "name": name, "goal": goal or name, "steps": serialized,
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    _write(routines[:30])


def delete(name: str) -> bool:
    routines = load()
    kept = [item for item in routines if str(item.get("name", "")).casefold() != str(name).casefold()]
    if len(kept) == len(routines):
        return False
    _write(kept)
    return True


def steps(item: dict) -> list[Step]:
    return [Step(str(row.get("action", "")), str(row.get("value", "")))
            for row in item.get("steps", []) if isinstance(row, dict)]
