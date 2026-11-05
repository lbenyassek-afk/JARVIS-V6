from __future__ import annotations

import json
import re
import hashlib
from dataclasses import dataclass
from pathlib import Path


IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{1,50}$")
VERSION = re.compile(r"^\d+\.\d+\.\d+$")
ALLOWED_PERMISSIONS = frozenset({
    "internet", "local_files_read", "local_files_write", "calendar_read",
    "calendar_write", "email_read", "email_draft", "email_send",
    "business_data", "notifications",
})
ALLOWED_INPUT_TYPES = frozenset({"string", "number", "boolean", "object"})


@dataclass(frozen=True)
class PluginOperation:
    operation_id: str
    description: str
    input_type: str
    approval: str = "inherit"


@dataclass(frozen=True)
class PluginManifest:
    plugin_id: str
    name: str
    version: str
    adapter: str
    permissions: tuple[str, ...]
    operations: tuple[PluginOperation, ...] = ()
    domains: tuple[str, ...] = ()
    integrity: str = ""


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
    operations = []
    for item in data.get("operations", []):
        if not isinstance(item, dict):
            raise ValueError("Plugin operations must be objects.")
        operation_id = str(item.get("id", ""))
        input_type = str(item.get("input_type", "string"))
        approval = str(item.get("approval", "inherit"))
        if not IDENTIFIER.fullmatch(operation_id) or input_type not in ALLOWED_INPUT_TYPES:
            raise ValueError("Plugin operation ID or input type is invalid.")
        if approval not in {"inherit", "always", "never"}:
            raise ValueError("Plugin operation approval policy is invalid.")
        operations.append(PluginOperation(operation_id, str(item.get("description", ""))[:200],
                                          input_type, approval))
    if len({item.operation_id for item in operations}) != len(operations):
        raise ValueError("Plugin operation IDs must be unique.")
    domains = tuple(dict.fromkeys(str(item).casefold().strip() for item in data.get("domains", [])))
    domain_pattern = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
    if any(not domain_pattern.fullmatch(item) for item in domains):
        raise ValueError("Plugin domains must be exact hostnames without URLs or wildcards.")
    integrity = str(data.get("integrity", ""))
    if integrity and not re.fullmatch(r"sha256:[0-9a-f]{64}", integrity):
        raise ValueError("Plugin integrity must be a SHA-256 digest.")
    return PluginManifest(plugin_id, name, version, adapter, permissions,
                          tuple(operations), domains, integrity)


def verify_payload_integrity(path: Path, integrity: str) -> bool:
    """Check a declared plugin payload before an adapter is allowed to read it."""
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", str(integrity)):
        return False
    digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    return digest == str(integrity).removeprefix("sha256:")
