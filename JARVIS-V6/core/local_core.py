from __future__ import annotations

import re
from datetime import datetime

from .config import load_config
from .memory import search


def respond(text: str, now: datetime | None = None) -> str | None:
    """Answer bounded, useful requests without a network or language model."""
    if not load_config().get("local_core", {}).get("enabled", True):
        return None
    raw = " ".join(str(text).strip().split())
    lowered = raw.casefold()
    now = now or datetime.now()
    if re.search(r"\b(what time is it|current time|tell me the time)\b", lowered):
        return f"It is {now:%H:%M}."
    if re.search(r"\b(what(?:'s| is) (?:the )?date|today'?s date|what day is it)\b", lowered):
        return f"Today is {now:%A, %d %B %Y}."
    if lowered in ("are you online", "system status", "status report", "offline status"):
        return "The local core is online. Memory, local commands, plans and approved desktop tools remain available without Gemini."
    match = re.search(r"(?:search|find|look in) (?:my )?memor(?:y|ies)(?: for)?\s+(.+)", raw, re.I)
    if match:
        rows = search(match.group(1), 6)
        if not rows:
            return "I found no matching long-term memory."
        return "Matching memory:\n" + "\n".join(
            f"- {row['category']}/{row['key']}: {row['value']}" for row in rows)
    if lowered in ("what can you do offline", "offline capabilities"):
        return ("Offline I can manage memory, search local records, track plans and tasks, "
                "answer basic system questions, and run approved desktop commands. Advanced "
                "conversation and current web research use Gemini.")
    return None
