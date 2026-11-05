from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from .permissions import decide


@dataclass(frozen=True)
class PlannedStep:
    action: str
    value: str
    label: str
    approval_required: bool
    reason: str


@dataclass(frozen=True)
class ExecutionPlan:
    plan_id: str
    goal: str
    created: str
    steps: tuple[PlannedStep, ...]

    @property
    def requires_approval(self) -> bool:
        return any(step.approval_required for step in self.steps)

    def to_dict(self) -> dict:
        return {**asdict(self), "requires_approval": self.requires_approval}


def build(goal: str, steps, registry, maximum: int = 20) -> ExecutionPlan:
    """Validate a proposed plan against the allowlisted action registry."""
    goal = " ".join(str(goal).strip().split())[:300]
    if not goal:
        raise ValueError("A plan needs a goal.")
    steps = list(steps)
    if not steps or len(steps) > max(1, min(int(maximum), 40)):
        raise ValueError("A plan must contain between 1 and the configured maximum steps.")
    planned = []
    for step in steps:
        action = registry.actions.get(str(step.action))
        if not action:
            raise ValueError(f"Unknown or unavailable action: {step.action}")
        value = str(step.value)[:2_000]
        if action.values and value not in action.values:
            raise ValueError(f"Value is not allowlisted for {action.label}: {value}")
        if action.validator:
            try:
                value = action.validator(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Invalid value for {action.label}: {exc}") from exc
        decision = decide(action, value)
        planned.append(PlannedStep(action.name, value, action.label,
                                   decision.approval_required, decision.reason))
    return ExecutionPlan(uuid.uuid4().hex, goal,
                         datetime.now(timezone.utc).isoformat(timespec="seconds"), tuple(planned))
