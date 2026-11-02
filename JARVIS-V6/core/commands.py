from __future__ import annotations

import re

from . import memory


def handle_memory_command(text: str) -> tuple[bool, str]:
    raw = str(text or "").strip()
    lower = raw.lower()
    if "do not save this" in lower or "ne sauvegarde pas" in lower:
        return True, "Understood. Nothing from this turn will be saved."
    match = re.match(r"(?is)^remember this\s*:\s*(.+)$", raw)
    if match:
        fact = match.group(1).strip()
        key = re.sub(r"\W+", "_", fact.lower()).strip("_")[:48] or "memory"
        return True, memory.remember("notes", key, fact)
    match = re.match(r"(?is)^forget this\s*:\s*(.+)$", raw)
    if match:
        return True, memory.forget(match.group(1))
    if lower in ("what do you remember about me?", "what do you remember about me"):
        rows = memory.search("", 30)
        if not rows:
            return True, "I have no long-term memories about you yet."
        return True, "\n".join(f"• {r['category']}/{r['key']}: {r['value']}" for r in rows)
    if lower.rstrip(".!?") == "delete all memories":
        return True, "__CONFIRM_DELETE_ALL_MEMORY__"
    return False, ""
