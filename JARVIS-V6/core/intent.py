from __future__ import annotations

import re
from datetime import datetime

from .language import normalized_text, response_language


def _normalise(text: str) -> str:
    return normalized_text(text)


def quick_reply(text: str, assistant_name: str = "JARVIS", user_name: str = "",
                language: str = "auto") -> str | None:
    """Return deterministic zero-network answers for common small requests."""
    normal = _normalise(text)
    assistant = _normalise(assistant_name) or "jarvis"
    salutation = r"hey|hi|hello|bonjour|salut|hola|hallo|ciao|ola|مرحبا"
    normal = re.sub(rf"^(?:{salutation})\s+{re.escape(assistant)}\s*", "", normal).strip()
    greeting = str(user_name).strip()
    greeting = f", {greeting}" if greeting else ""
    greetings = {
        "en": ("Hello", "How can I help?"), "fr": ("Bonjour", "Comment puis-je vous aider ?"),
        "ar": ("مرحباً", "كيف يمكنني مساعدتك؟"), "es": ("Hola", "¿Cómo puedo ayudarte?"),
        "de": ("Hallo", "Wie kann ich helfen?"), "it": ("Ciao", "Come posso aiutarti?"),
        "pt": ("Olá", "Como posso ajudar?"),
    }
    greeting_words = {
        "", "hi", "hello", "hey", "good morning", "good afternoon", "good evening",
        "bonjour", "salut", "hola", "hallo", "ciao", "ola", "مرحبا", "السلام عليكم",
    }
    if normal in greeting_words:
        answer_language = response_language(text, language)
        hello, offer = greetings.get(answer_language, greetings["en"])
        return f"{hello}{greeting}. {offer}"
    if re.fullmatch(r"(?:what(?: is| s)? )?(?:the )?time(?: is it)?", normal):
        return f"It is {datetime.now().strftime('%H:%M')}."
    if re.fullmatch(r"(?:what(?: is| s)? )?(?:today(?: s)? )?date|what day is it", normal):
        return datetime.now().strftime("Today is %A, %d %B %Y.")
    return None


def is_weather_query(text: str) -> bool:
    normal = _normalise(text)
    return any(word in normal.split() for word in (
        "weather", "forecast", "temperature", "rain", "snow", "wind", "outside",
        "meteo", "pluie", "neige", "vent", "temps", "clima", "lluvia", "nieve", "viento",
        "wetter", "regen", "schnee", "temperatur", "tempo", "pioggia", "neve", "vento",
        "chuva", "جَو", "طقس", "مطر", "ثلج", "حرارة",
    ))


def requested_location(text: str) -> str:
    match = re.search(
        r"(?:weather|forecast|temperature|m[ée]t[ée]o|clima|tiempo|wetter|tempo|طقس)"
        r"\s+(?:(?:report|rapport|informe|bericht)\s+)?(?:for|in|at|pour|[àa]|en|f[üu]r|في)\s+(.+)$",
        str(text), re.I)
    return match.group(1).strip(" ?.!")[:100] if match else ""
