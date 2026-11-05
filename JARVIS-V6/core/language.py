from __future__ import annotations

import re
import unicodedata


LANGUAGES = {
    "auto": {"label": "Automatic — follow each message", "locale": "en-GB"},
    "en": {"label": "English", "locale": "en-GB"},
    "fr": {"label": "Français", "locale": "fr-FR"},
    "ar": {"label": "العربية", "locale": "ar-SA"},
    "es": {"label": "Español", "locale": "es-ES"},
    "de": {"label": "Deutsch", "locale": "de-DE"},
    "it": {"label": "Italiano", "locale": "it-IT"},
    "pt": {"label": "Português", "locale": "pt-PT"},
}

DEFAULT_NEURAL_VOICES = {
    "en": "en-GB-ThomasNeural",
    "fr": "fr-FR-HenriNeural",
    "ar": "ar-SA-HamedNeural",
    "es": "es-ES-AlvaroNeural",
    "de": "de-DE-ConradNeural",
    "it": "it-IT-DiegoNeural",
    "pt": "pt-PT-DuarteNeural",
}

_MARKERS = {
    "en": {"hello", "the", "and", "what", "how", "with", "please", "this", "that", "is", "are"},
    "fr": {"bonjour", "salut", "le", "la", "les", "et", "avec", "pour", "comment", "quoi", "est", "une", "des"},
    "es": {"hola", "el", "la", "los", "y", "con", "para", "como", "qué", "que", "una", "es"},
    "de": {"hallo", "der", "die", "das", "und", "mit", "für", "wie", "was", "ist", "eine"},
    "it": {"ciao", "il", "la", "gli", "e", "con", "per", "come", "cosa", "che", "una"},
    "pt": {"ola", "olá", "o", "a", "os", "e", "com", "para", "como", "que", "uma", "é"},
}


def normalize_language(value: str) -> str:
    value = str(value or "auto").strip().casefold().replace("_", "-")
    value = value.split("-", 1)[0]
    return value if value in LANGUAGES else "auto"


def normalized_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", str(value or "")).casefold()
    value = "".join(char for char in unicodedata.normalize("NFKD", value)
                    if not unicodedata.combining(char))
    return " ".join(re.findall(r"[^\W_]+", value, flags=re.UNICODE))


def detect_language(text: str, fallback: str = "en") -> str:
    raw = str(text or "")
    if re.search(r"[\u0600-\u06ff]", raw):
        return "ar"
    words = set(normalized_text(raw).split())
    if not words:
        return normalize_language(fallback) if normalize_language(fallback) != "auto" else "en"
    scores = {code: len(words & markers) for code, markers in _MARKERS.items()}
    # Diacritics resolve short sentences where stop words alone are ambiguous.
    lowered = raw.casefold()
    if re.search(r"[àâçéèêëîïôûùüÿœ]", lowered):
        scores["fr"] += 2
    if re.search(r"[ñ¿¡]", lowered):
        scores["es"] += 2
    if re.search(r"[äöüß]", lowered):
        scores["de"] += 2
    if re.search(r"[ãõ]", lowered):
        scores["pt"] += 2
    best = max(scores, key=scores.get)
    if scores[best] == 0:
        selected = normalize_language(fallback)
        return selected if selected != "auto" else "en"
    return best


def speech_locale(language: str) -> str:
    code = normalize_language(language)
    return LANGUAGES[code]["locale"]


def response_language(text: str, configured: str = "auto") -> str:
    selected = normalize_language(configured)
    return detect_language(text) if selected == "auto" else selected


def voice_for_text(text: str, preferred_voice: str, language: str = "auto") -> str:
    selected = normalize_language(language)
    code = detect_language(text) if selected == "auto" else selected
    if code == "en" and str(preferred_voice).startswith("en-"):
        return preferred_voice
    return DEFAULT_NEURAL_VOICES.get(code, DEFAULT_NEURAL_VOICES["en"])
