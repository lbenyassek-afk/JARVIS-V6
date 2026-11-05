from __future__ import annotations

import json
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from . import config
from .crypto import open_text, seal


TERMINAL = frozenset({"completed", "failed", "cancelled", "blocked"})


@dataclass
class MissionNode:
    node_id: str
    action: str
    value: str
    depends_on: tuple[str, ...] = ()
    state: str = "pending"
    result: str = ""
    verification: str = ""
    attempts: int = 0


@dataclass
class MissionGraph:
    goal: str
    nodes: list[MissionNode]
    mission_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))

    @classmethod
    def sequential(cls, steps, goal: str = "Desktop mission") -> "MissionGraph":
        nodes = []
        previous = ()
        for index, step in enumerate(steps, 1):
            node_id = f"step_{index}"
            nodes.append(MissionNode(node_id, str(step.action), str(step.value), previous))
            previous = (node_id,)
        graph = cls(str(goal).strip()[:300] or "Desktop mission", nodes)
        graph.validate()
        return graph

    def validate(self, maximum: int = 40) -> None:
        if not self.nodes or len(self.nodes) > maximum:
            raise ValueError(f"A mission graph must contain 1–{maximum} nodes.")
        ids = [node.node_id for node in self.nodes]
        if len(ids) != len(set(ids)) or any(not item for item in ids):
            raise ValueError("Mission node IDs must be non-empty and unique.")
        known = set(ids)
        if any(set(node.depends_on) - known for node in self.nodes):
            raise ValueError("Mission dependencies must refer to nodes in the same graph.")
        visiting: set[str] = set(); visited: set[str] = set()
        by_id = {node.node_id: node for node in self.nodes}

        def visit(node_id: str) -> None:
            if node_id in visiting:
                raise ValueError("Mission dependencies contain a cycle.")
            if node_id in visited:
                return
            visiting.add(node_id)
            for dependency in by_id[node_id].depends_on:
                visit(dependency)
            visiting.remove(node_id); visited.add(node_id)

        for node_id in ids:
            visit(node_id)

    def ready(self) -> list[MissionNode]:
        states = {node.node_id: node.state for node in self.nodes}
        return [node for node in self.nodes if node.state == "pending" and
                all(states.get(dependency) == "completed" for dependency in node.depends_on)]

    def block_dependants(self) -> None:
        states = {node.node_id: node.state for node in self.nodes}
        changed = True
        while changed:
            changed = False
            for node in self.nodes:
                if node.state == "pending" and any(states.get(dep) in {"failed", "blocked", "cancelled"}
                                                    for dep in node.depends_on):
                    node.state = "blocked"; states[node.node_id] = "blocked"; changed = True

    def to_dict(self) -> dict:
        return {"mission_id": self.mission_id, "goal": self.goal, "created": self.created,
                "nodes": [asdict(node) for node in self.nodes]}

    @classmethod
    def from_dict(cls, data: dict) -> "MissionGraph":
        nodes = []
        for item in data.get("nodes", []):
            row = dict(item); row["depends_on"] = tuple(row.get("depends_on", ()))
            nodes.append(MissionNode(**row))
        graph = cls(str(data.get("goal", "Desktop mission")), nodes,
                    str(data.get("mission_id", uuid.uuid4().hex)), str(data.get("created", "")))
        graph.validate()
        return graph


class MissionStore:
    """Encrypted, crash-safe checkpoints for one current desktop mission."""
    _lock = threading.Lock()

    @staticmethod
    def path():
        return config.APP_DIR / "mission.state"

    def save(self, graph: MissionGraph) -> None:
        with self._lock:
            config.APP_DIR.mkdir(parents=True, exist_ok=True)
            temporary = self.path().with_suffix(".tmp")
            temporary.write_text(seal(json.dumps(graph.to_dict(), ensure_ascii=False,
                                                 separators=(",", ":"))), encoding="utf-8")
            temporary.replace(self.path())

    def load(self) -> MissionGraph | None:
        try:
            return MissionGraph.from_dict(json.loads(open_text(self.path().read_text(encoding="utf-8"))))
        except Exception:
            return None

    def clear(self) -> None:
        try:
            self.path().unlink(missing_ok=True)
        except OSError:
            pass
