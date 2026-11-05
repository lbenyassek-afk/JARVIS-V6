from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class AdapterCapability:
    operation: str
    description: str
    read_only: bool
    approval_required: bool


@dataclass(frozen=True)
class AdapterStatus:
    adapter_id: str
    available: bool
    detail: str
    capabilities: tuple[AdapterCapability, ...] = ()


class AdapterRegistry:
    """Typed boundary for integrations; adapters never expose arbitrary calls."""
    def __init__(self):
        self._statuses: dict[str, AdapterStatus] = {}
        self._handlers: dict[tuple[str, str], Callable[[dict], object]] = {}

    def register(self, status: AdapterStatus,
                 handlers: dict[str, Callable[[dict], object]] | None = None) -> None:
        if status.adapter_id in self._statuses:
            raise ValueError(f"Duplicate adapter: {status.adapter_id}")
        declared = {item.operation for item in status.capabilities}
        handlers = handlers or {}
        if set(handlers) - declared:
            raise ValueError("Adapter handler is not declared in its capability contract.")
        self._statuses[status.adapter_id] = status
        for operation, handler in handlers.items():
            self._handlers[(status.adapter_id, operation)] = handler

    def status(self) -> tuple[AdapterStatus, ...]:
        return tuple(self._statuses.values())

    def invoke(self, adapter_id: str, operation: str, payload: dict,
               approved: bool = False) -> object:
        status = self._statuses.get(adapter_id)
        if not status or not status.available:
            raise RuntimeError("Adapter is unavailable.")
        capability = next((item for item in status.capabilities if item.operation == operation), None)
        if capability is None or (adapter_id, operation) not in self._handlers:
            raise ValueError("Operation is not allowlisted for this adapter.")
        if capability.approval_required and not approved:
            raise PermissionError("This adapter operation requires approval.")
        if not isinstance(payload, dict):
            raise TypeError("Adapter input must be a structured object.")
        return self._handlers[(adapter_id, operation)](payload)


def platform_registry() -> AdapterRegistry:
    registry = AdapterRegistry()
    windows_uia = importlib.util.find_spec("pywinauto") is not None
    registry.register(AdapterStatus(
        "windows_uia", windows_uia,
        "Windows accessibility adapter available" if windows_uia else "Install the Windows build for UI Automation",
        (AdapterCapability("inspect_active_app", "Read named controls from the active app", True, False),),
    ))
    registry.register(AdapterStatus(
        "browser", False, "No browser automation runtime is installed; web research uses Gemini grounding",
        (),
    ))
    registry.register(AdapterStatus(
        "mcp", False, "MCP transport contract reserved; no external server is trusted or connected",
        (),
    ))
    return registry
