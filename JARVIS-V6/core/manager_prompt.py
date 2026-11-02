from __future__ import annotations

import re
from pathlib import Path

from .config import APP_DIR


DEFAULT_PATH = Path(__file__).with_name("manager_prompt.txt")
PATH = APP_DIR / "manager_prompt.txt"
MAX_CHARS = 8000
_SECRET = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bAIza[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"(?i)\b(?:password|api[_ -]?key|oauth|token|secret)\s*[:=]\s*\S+"),
)


def default() -> str:
    return DEFAULT_PATH.read_text(encoding="utf-8").strip()


def load() -> str:
    try:
        value = PATH.read_text(encoding="utf-8").strip()
        return value[:MAX_CHARS] if value else default()
    except OSError:
        return default()


def save(text: str) -> None:
    text = str(text or "").strip()
    if not text:
        raise ValueError("The Manager Prompt cannot be empty.")
    if len(text) > MAX_CHARS:
        raise ValueError(f"The Manager Prompt may not exceed {MAX_CHARS} characters.")
    if any(pattern.search(text) for pattern in _SECRET):
        raise ValueError("The Manager Prompt may not contain credentials or secrets.")
    PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = PATH.with_suffix(".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(PATH)


def restore_default() -> str:
    value = default()
    save(value)
    return value
