from __future__ import annotations

import re

from .config import APP_DIR


PATH = APP_DIR / "custom_instructions.txt"
MAX_CHARS = 6000
_SECRET = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bAIza[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"(?i)\b(?:password|api[_ -]?key|oauth|token|secret)\s*[:=]\s*\S+"),
)


def load() -> str:
    try:
        return PATH.read_text(encoding="utf-8")[:MAX_CHARS].strip()
    except Exception:
        return ""


def save(text: str) -> None:
    text = str(text or "").strip()
    if len(text) > MAX_CHARS:
        raise ValueError(f"Custom instructions may not exceed {MAX_CHARS} characters.")
    if any(pattern.search(text) for pattern in _SECRET):
        raise ValueError("Custom instructions may not contain credentials or secrets.")
    PATH.parent.mkdir(parents=True, exist_ok=True)
    temp = PATH.with_suffix(".tmp")
    temp.write_text(text, encoding="utf-8")
    temp.replace(PATH)


def clear() -> None:
    try:
        PATH.unlink()
    except FileNotFoundError:
        pass
