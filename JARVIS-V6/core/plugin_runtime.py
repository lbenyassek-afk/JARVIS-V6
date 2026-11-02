from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{1,50}$")
VERSION = re.compile(r"^\d+\.\d+\.\d+$")
ALLOWED_PERMISSIONS = frozenset({
    "internet", "local_files_read", "local_files_write", "calendar_read",
    "calendar_write", "email_read", "email_draft", "email_send",
    "business_data", "notifications",
})


@dataclass(frozen=True)
class PluginManifest:
    plugin_id: str
    name: str
    version: str
    adapter: str
    permissions: tuple[str, ...]


def load_manifest(path: Path, installed_adapters: set[str]) -> PluginManifest:
    """Validate declarative metadata without importing or executing plugin code."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError("Plugin manifest is not valid JSON.") from exc
    plugin_id = str(data.get("id", "")); name = str(data.get("name", "")).strip()[:80]
    version = str(data.get("version", "")); adapter = str(data.get("adapter", ""))
    permissions = tuple(dict.fromkeys(str(item) for item in data.get("permissions", [])))
    if not IDENTIFIER.fullmatch(plugin_id) or not name or not VERSION.fullmatch(version):
        raise ValueError("Plugin identity, name or version is invalid.")
    if adapter not in installed_adapters:
        raise ValueError("The plugin requests an adapter that is not installed.")
    unknown = set(permissions) - ALLOWED_PERMISSIONS
    if unknown:
        raise ValueError("Unknown plugin permission: " + ", ".join(sorted(unknown)))
    return PluginManifest(plugin_id, name, version, adapter, permissions)
