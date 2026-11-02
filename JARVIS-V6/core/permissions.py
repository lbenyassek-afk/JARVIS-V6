from __future__ import annotations

from dataclasses import dataclass

from .config import load_config


@dataclass(frozen=True)
class Decision:
    approval_required: bool
    reason: str


def decide(action, value: str = "") -> Decision:
    cfg = load_config().get("permissions", {})
    overrides = cfg.get("actions", {})
    rule = str(overrides.get(action.name, ""))
    if action.name == "open_app":
        rule = str(cfg.get("applications", {}).get(str(value), rule))
    if action.sensitive:
        return Decision(True, "Sensitive mouse, keyboard, file or private-data action")
    if rule == "ask":
        return Decision(True, "This action is configured to ask every time")
    if rule == "allow":
        return Decision(False, "This action is explicitly allowed")
    automatic = str(cfg.get("low_risk", "automatic")) == "automatic"
    return Decision(not automatic, "Low-risk action policy")


def plan_requires_approval(steps, registry) -> bool:
    return any(decide(registry.actions[step.action], step.value).approval_required for step in steps)
