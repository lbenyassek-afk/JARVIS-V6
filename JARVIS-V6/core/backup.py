from __future__ import annotations

import io
import json
import os
import zipfile
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from . import config
from .secrets import get_secret


MAGIC = b"JARVIS6-BACKUP\x00"


def _derive(password: str, salt: bytes) -> bytes:
    if len(str(password)) < 8:
        raise ValueError("Backup password must contain at least 8 characters.")
    return PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=480_000).derive(
        str(password).encode("utf-8"))


def create(destination: Path, password: str) -> Path:
    destination = Path(destination)
    files = ("config.json", "memory.json", "conversation.sqlite3", "workspace.sqlite3",
             "desktop_audit.sqlite3", "desktop_routines.json",
             "custom_instructions.txt", "manager_prompt.txt")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps({"format": 1, "application": "JARVIS V6"}))
        for name in files:
            path = config.APP_DIR / name
            if path.is_file():
                archive.writestr("data/" + name, path.read_bytes())
        key = get_secret("memory_encryption_key")
        fallback = config.APP_DIR / ".memory.key"
        if not key and fallback.is_file():
            key = fallback.read_text(encoding="ascii").strip()
        if key:
            archive.writestr("private/memory.key", key)
    salt, nonce = os.urandom(16), os.urandom(12)
    encrypted = AESGCM(_derive(password, salt)).encrypt(nonce, buffer.getvalue(), MAGIC)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(MAGIC + salt + nonce + encrypted)
    return destination


def inspect(path: Path, password: str) -> list[str]:
    raw = Path(path).read_bytes()
    if not raw.startswith(MAGIC):
        raise ValueError("This is not a JARVIS V6 encrypted backup.")
    offset = len(MAGIC); salt = raw[offset:offset + 16]; nonce = raw[offset + 16:offset + 28]
    try:
        clear = AESGCM(_derive(password, salt)).decrypt(nonce, raw[offset + 28:], MAGIC)
    except Exception as exc:
        raise ValueError("The backup password is incorrect or the file is damaged.") from exc
    with zipfile.ZipFile(io.BytesIO(clear), "r") as archive:
        return sorted(archive.namelist())
