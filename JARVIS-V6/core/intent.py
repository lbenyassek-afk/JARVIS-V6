from __future__ import annotations

import re
from datetime import datetime


def _normalise(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", str(text).casefold()).strip()


def quick_reply(text: str, assistant_name: str = "JARVIS", user_name: str = "") -> str | None:
    """Return deterministic zero-network answers for common small requests."""
    normal = _normalise(text)
    assistant = _normalise(assistant_name) or "jarvis"
    normal = re.sub(rf"^(?:hey|hi|hello)\s+{re.escape(assistant)}\s*", "", normal).strip()
    greeting = str(user_name).strip()
    greeting = f", {greeting}" if greeting else ""
    if normal in ("", "hi", "hello", "hey", "good morning", "good afternoon", "good evening"):
        return f"Hello{greeting}. How can I help?"
    if re.fullmatch(r"(?:what(?: is| s)? )?(?:the )?time(?: is it)?", normal):
        return f"It is {datetime.now().strftime('%H:%M')}."
    if re.fullmatch(r"(?:what(?: is| s)? )?(?:today(?: s)? )?date|what day is it", normal):
        return datetime.now().strftime("Today is %A, %d %B %Y.")
    return None


def is_weather_query(text: str) -> bool:
    normal = _normalise(text)
    return bool(re.search(r"\b(weather|forecast|temperature|rain|snow|wind|outside)\b", normal))


def requested_location(text: str) -> str:
    match = re.search(r"\b(?:weather|forecast|temperature)\s+(?:report\s+)?(?:for|in|at)\s+(.+)$",
                      str(text), re.I)
    return match.group(1).strip(" ?.!")[:100] if match else ""
