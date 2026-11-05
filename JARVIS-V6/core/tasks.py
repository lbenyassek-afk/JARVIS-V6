from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from .config import load_config
from .skills import Registry
from .plugins import enabled as plugin_enabled
from .audit import record
from .permissions import decide
from .mission_graph import MissionGraph, MissionStore
from .verification import verify
from .isolation import selected as selected_isolation


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

    def interrupted_mission(self) -> MissionGraph | None:
        """Return an interrupted checkpoint for review; never auto-repeat it."""
        graph = MissionStore().load()
        if graph and any(node.state != "completed" for node in graph.nodes):
            return graph
        return None

    def discard_checkpoint(self) -> None:
        MissionStore().clear()

    def execute(self, steps: list[Step], progress=None, approved_sensitive: bool = False,
                goal: str = "Desktop mission") -> list[str]:
        cfg = load_config()
        if not cfg["desktop"].get("enabled") or not plugin_enabled("desktop"):
            raise PermissionError("Enable the Desktop Control plugin first.")
        maximum = max(1, min(int(cfg["desktop"].get("max_steps", 20)), 40))
        if not steps or len(steps) > maximum:
            raise ValueError(f"A task must contain 1–{maximum} steps.")
        self.cancel_event.clear()
        graph = MissionGraph.sequential(steps, goal)
        return self.execute_graph(graph, progress, approved_sensitive, cfg)

    def execute_graph(self, graph: MissionGraph, progress=None, approved_sensitive: bool = False,
                      cfg: dict | None = None) -> list[str]:
        """Execute a validated dependency graph with encrypted checkpoints.

        Desktop actions remain sequential because concurrent mouse/keyboard
        control is nondeterministic. The graph still supports independent
        branches for future read-only adapters and blocks dependants on failure.
        """
        cfg = cfg or load_config()
        graph.validate(max(1, min(int(cfg["desktop"].get("max_steps", 20)), 40)))
        if not cfg["desktop"].get("enabled") or not plugin_enabled("desktop"):
            raise PermissionError("Enable the Desktop Control plugin first.")
        # Validate the complete graph before the first side effect. This avoids
        # a mission partially executing before a bad value or later approval
        # requirement is discovered.
        for node in graph.nodes:
            action = self.registry.actions.get(node.action)
            if not action:
                raise ValueError(f"Unknown action: {node.action}")
            if action.values and node.value not in action.values:
                raise ValueError(f"Value is not allowlisted for {action.label}: {node.value}")
            if action.validator:
                try:
                    node.value = action.validator(node.value)
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"Invalid value for {action.label}: {exc}") from exc
            decision = decide(action, node.value)
            if decision.approval_required and not approved_sensitive:
                raise PermissionError(f"Approval required for {action.label}: {decision.reason}")
        isolation = selected_isolation(cfg)
        if not isolation.available:
            raise RuntimeError(isolation.detail)
        if not isolation.executes:
            return [f"{index}. SIMULATED — {self.registry.actions[node.action].label}: {node.value}"
                    for index, node in enumerate(graph.nodes, 1)]
        store = MissionStore(); store.save(graph)
        results = []
        total = len(graph.nodes)
        completed = 0
        while completed < total:
            if self.cancel_event.is_set():
                for pending in graph.nodes:
                    if pending.state == "pending":
                        pending.state = "cancelled"
                store.save(graph)
                raise TaskCancelled("Desktop task cancelled.")
            ready = graph.ready()
            if not ready:
                graph.block_dependants(); store.save(graph)
                if all(node.state in {"completed", "blocked"} for node in graph.nodes):
                    break
                raise RuntimeError("Mission cannot continue because its dependencies are unresolved.")
            node = ready[0]
            index = graph.nodes.index(node) + 1
            step = Step(node.action, node.value)
            action = self.registry.actions.get(step.action)
            if not action:  # guarded by preflight; retained for type safety
                raise ValueError(f"Unknown action: {step.action}")
            if progress:
                progress(index, total, action.label)
            record(step.action, step.value, "started")
            node.state = "running"; store.save(graph)
            maximum_attempts = 1 + (max(0, min(int(cfg["desktop"].get("verification_retries", 1)), 2))
                                    if action.verifier and action.retry_safe else 0)
            last_error: Exception | None = None
            result = ""
            for attempt in range(1, maximum_attempts + 1):
                node.attempts = attempt
                try:
                    result = action.handler(step.value)
                    verifier = action.verifier if cfg["desktop"].get("verify_results", True) else None
                    outcome = verify(verifier, step.value, result,
                                     cfg["desktop"].get("verification_settle_seconds", .12))
                    node.verification = outcome.detail
                    if outcome.verified:
                        last_error = None
                        break
                    last_error = RuntimeError(outcome.detail)
                except Exception as exc:
                    last_error = exc
                if attempt < maximum_attempts:
                    time.sleep(.15 * attempt)
            if last_error is not None:
                node.state = "failed"; node.result = str(last_error); graph.block_dependants(); store.save(graph)
                record(step.action, step.value, f"failed: {last_error}")
                raise RuntimeError(f"Step {index} ({action.label}) failed: {last_error}") from last_error
            node.state = "completed"; node.result = str(result); store.save(graph)
            record(step.action, step.value,
                   "verified" if action.verifier and cfg["desktop"].get("verify_results", True) else "reported")
            results.append(f"{index}. {result}")
            completed += 1
            time.sleep(max(0, min(float(cfg["desktop"].get("step_delay", .35)), 3)))
        if any(node.state != "completed" for node in graph.nodes):
            raise RuntimeError("Mission stopped because one or more dependent steps were blocked.")
        store.clear()
        return results
