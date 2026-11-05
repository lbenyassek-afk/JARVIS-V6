from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from .config import APP_DIR, load_config
from .crypto import open_text, seal, encrypted
from .retrieval import relevance


MEMORY_PATH = APP_DIR / "memory.json"
CATEGORIES = ("identity", "preferences", "relationships", "projects",
              "businesses", "goals", "decisions", "routines", "notes")
_SECRET = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bAIza[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"(?i)\b(?:password|api[_ -]?key|oauth|token|secret)\s*[:=]\s*\S+"),
)


def empty_memory() -> dict:
    return {category: {} for category in CATEGORIES}


def sensitive(key: str, value: str) -> bool:
    name = re.sub(r"\W+", "_", str(key).lower())
    if any(word in name for word in ("password", "api_key", "apikey", "token", "secret", "credential")):
        return True
    return any(pattern.search(str(value)) for pattern in _SECRET)


def load_memory() -> dict:
    stored = ""
    try:
        stored = MEMORY_PATH.read_text(encoding="utf-8")
        raw = json.loads(open_text(stored))
    except Exception:
        raw = {}
    result = empty_memory()
    if isinstance(raw, dict):
        for category in CATEGORIES:
            if isinstance(raw.get(category), dict):
                result[category].update(raw[category])
        for key, value in raw.items():
            if key not in result:
                result[key] = value
    if raw and not encrypted(stored):
        save_memory(result)
    return result


def save_memory(memory: dict) -> None:
    MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp = MEMORY_PATH.with_suffix(".tmp")
    payload = json.dumps(memory, separators=(",", ":"), ensure_ascii=False)
    temp.write_text(seal(payload), encoding="utf-8")
    temp.replace(MEMORY_PATH)
    try:
        os.chmod(MEMORY_PATH, 0o600)
    except OSError:
        pass


def remember(category: str, key: str, value: str, *, importance: int = 3,
             pinned: bool = False, source: str = "user") -> str:
    category = category if category in CATEGORIES else "notes"
    key, value = str(key).strip(), str(value).strip()
    if not key or not value:
        return "Nothing stored: a name and value are required."
    if sensitive(key, value):
        return "Refused: credentials and private secrets are never stored."
    memory = load_memory()
    previous = memory[category].get(key, {})
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    memory[category][key] = {
        "value": value[:600],
        "scope": str(load_config().get("assistant", {}).get("active_mode", "personal")),
        "importance": max(1, min(int(importance), 5)),
        "pinned": bool(pinned),
        "source": str(source)[:40],
        "created": previous.get("created", now) if isinstance(previous, dict) else now,
        "updated": now,
    }
    save_memory(memory)
    return f"Remembered {category}/{key}."


def forget(query: str) -> str:
    query = str(query).strip().lower()
    if not query:
        return "Nothing forgotten: provide a memory name or phrase."
    memory = load_memory()
    matches = []
    for category in CATEGORIES:
        for key, entry in memory[category].items():
            value = entry.get("value", "") if isinstance(entry, dict) else str(entry)
            if query in key.lower() or query in value.lower():
                matches.append((category, key))
    if len(matches) != 1:
        return "No unique memory matched." if not matches else "Several memories matched; be more specific."
    category, key = matches[0]
    del memory[category][key]
    save_memory(memory)
    return f"Forgotten {category}/{key}."


def delete_all() -> None:
    save_memory(empty_memory())


def delete_one(category: str, key: str) -> bool:
    memory = load_memory()
    if category not in CATEGORIES or key not in memory.get(category, {}):
        return False
    del memory[category][key]
    save_memory(memory)
    return True


def update(category: str, key: str, *, value: str | None = None,
           importance: int | None = None, pinned: bool | None = None) -> bool:
    memory = load_memory()
    entry = memory.get(category, {}).get(key)
    if category not in CATEGORIES or not isinstance(entry, dict):
        return False
    if value is not None:
        if sensitive(key, value):
            raise ValueError("Credentials and private secrets are never stored.")
        entry["value"] = str(value).strip()[:600]
    if importance is not None:
        entry["importance"] = max(1, min(int(importance), 5))
    if pinned is not None:
        entry["pinned"] = bool(pinned)
    entry["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    save_memory(memory)
    return True


def search(query: str = "", limit: int = 12, scope: str | None = None) -> list[dict]:
    query = str(query).strip()
    scope = scope or str(load_config().get("assistant", {}).get("active_mode", "personal"))
    rows = []
    for category, items in load_memory().items():
        if not isinstance(items, dict):
            continue
        for key, entry in items.items():
            value = entry.get("value", "") if isinstance(entry, dict) else str(entry)
            item_scope = entry.get("scope", "global") if isinstance(entry, dict) else "global"
            if item_scope not in (scope, "global"):
                continue
            if sensitive(key, value):
                continue
            haystack = f"{category} {key} {value}"
            matches = 1 if not query else relevance(query, haystack)
            importance = int(entry.get("importance", 3)) if isinstance(entry, dict) else 3
            pinned = bool(entry.get("pinned", False)) if isinstance(entry, dict) else False
            score = matches * 10 + importance + (8 if pinned else 0)
            if matches:
                rows.append({"category": category, "key": key, "value": value,
                             "scope": item_scope, "importance": importance,
                             "pinned": pinned, "source": entry.get("source", "legacy") if isinstance(entry, dict) else "legacy",
                             "updated": entry.get("updated", "") if isinstance(entry, dict) else "", "score": score})
    rows.sort(key=lambda row: (-row["score"], row["category"], row["key"]))
    return rows[:limit]


def prompt_block(query: str, budget: int = 1800) -> str:
    lines = ["[RELEVANT LONG-TERM MEMORY]"]
    used = len(lines[0])
    for row in search(query, 30):
        line = f"- {row['category']}/{row['key']}: {row['value']}"
        if used + len(line) > budget:
            break
        lines.append(line)
        used += len(line)
    return "\n".join(lines) if len(lines) > 1 else ""
