from __future__ import annotations

import asyncio
import hashlib
import re
import tempfile
import uuid
from pathlib import Path

from .config import APP_DIR
from .metrics import measure


BRITISH_VOICES = {
    "Ryan — British male": "en-GB-RyanNeural",
    "Sonia — British female": "en-GB-SoniaNeural",
    "Thomas — Cinematic British male": "en-GB-ThomasNeural",
    "Libby — British female": "en-GB-LibbyNeural",
    "Maisie — British female": "en-GB-MaisieNeural",
}


def _spoken_text(text: str) -> str:
    clean = re.sub(r"```.*?```", "Code example omitted from speech.", str(text), flags=re.S)
    clean = re.sub(r"https?://\S+", "source link", clean)
    clean = re.sub(r"[*_#`>|]", "", clean)
    # Remove formatting and repeated punctuation while keeping sentence stops;
    # sentence punctuation gives the neural voice natural prosody.
    clean = re.sub(r"\.{2,}|…+", " ", clean)
    clean = re.sub(r"[,;:]+", " ", clean)
    clean = re.sub(r"([.!?])\1+", r"\1", clean)
    clean = re.sub(r"([.!?])(?=\S)", r"\1 ", clean)
    clean = re.sub(r"\s*[-–—]\s*", " ", clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean[:4_500]


def synthesize(text: str, voice: str = "en-GB-ThomasNeural",
               rate: int = 0, pitch: int = 0) -> str:
    """Create one temporary British neural-voice response for Qt playback."""
    import edge_tts
    if voice not in BRITISH_VOICES.values():
        voice = "en-GB-ThomasNeural"
    rate = max(-20, min(20, int(rate)))
    pitch = max(-10, min(10, int(pitch)))
    spoken = _spoken_text(text)
    cacheable = len(spoken) <= 220
    if cacheable:
        digest = hashlib.sha256(f"{voice}|{rate}|{pitch}|{spoken}".encode("utf-8")).hexdigest()
        directory = APP_DIR / "voice-cache"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{digest}.mp3"
        if path.exists() and path.stat().st_size >= 256:
            return str(path)
    else:
        path = Path(tempfile.gettempdir()) / f"jarvis_voice_{uuid.uuid4().hex}.mp3"
    temporary = path.with_suffix(".tmp")

    async def create():
        communicate = edge_tts.Communicate(
            spoken, voice=voice,
            rate=f"{rate:+d}%", pitch=f"{pitch:+d}Hz", volume="+3%",
        )
        await communicate.save(str(temporary))

    with measure("voice.neural_synthesis"):
        asyncio.run(create())
    if not temporary.exists() or temporary.stat().st_size < 256:
        raise RuntimeError("British neural voice returned no audio")
    temporary.replace(path)
    if cacheable:
        cached = sorted(path.parent.glob("*.mp3"), key=lambda item: item.stat().st_mtime, reverse=True)
        for old in cached[80:]:
            old.unlink(missing_ok=True)
    return str(path)


def is_cached_audio(path: str) -> bool:
    try:
        return Path(path).resolve().parent == (APP_DIR / "voice-cache").resolve()
    except OSError:
        return False
