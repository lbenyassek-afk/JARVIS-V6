from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from .config import load_config
from .skills import Registry
from .plugins import enabled as plugin_enabled
from .audit import record
from .permissions import decide


@dataclass
class Step:
    action: str
    value: str


class TaskCancelled(RuntimeError):
    pass


class TaskExecutor:
    def __init__(self, registry: Registry):
        self.registry = registry
        self.cancel_event = threading.Event()

    def cancel(self) -> None:
        self.cancel_event.set()

    def execute(self, steps: list[Step], progress=None, approved_sensitive: bool = False) -> list[str]:
        cfg = load_config()
        if not cfg["desktop"].get("enabled") or not plugin_enabled("desktop"):
            raise PermissionError("Enable the Desktop Control plugin first.")
        maximum = max(1, min(int(cfg["desktop"].get("max_steps", 20)), 40))
        if not steps or len(steps) > maximum:
            raise ValueError(f"A task must contain 1–{maximum} steps.")
        self.cancel_event.clear()
        results = []
        for index, step in enumerate(steps, 1):
            if self.cancel_event.is_set():
                raise TaskCancelled("Desktop task cancelled.")
            action = self.registry.actions.get(step.action)
            if not action:
                raise ValueError(f"Unknown action: {step.action}")
            decision = decide(action, step.value)
            if decision.approval_required and not approved_sensitive:
                raise PermissionError(f"Approval required for {action.label}: {decision.reason}")
            if progress:
                progress(index, len(steps), action.label)
            if action.sensitive:
                record(step.action, step.value, "started")
            try:
                result = action.handler(step.value)
            except Exception as exc:
                if action.sensitive:
                    record(step.action, step.value, f"failed: {exc}")
                raise
            if action.sensitive:
                record(step.action, step.value, "completed")
            results.append(f"{index}. {result}")
            time.sleep(max(0, min(float(cfg["desktop"].get("step_delay", .35)), 3)))
        return results
