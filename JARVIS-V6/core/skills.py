from __future__ import annotations

import importlib.util
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


NAME = re.compile(r"^[a-z][a-z0-9_]{1,50}$")


@dataclass(frozen=True)
class Action:
    name: str
    label: str
    description: str
    handler: Callable[[str], str]
    values: tuple[str, ...] = ()
    sensitive: bool = False
    validator: Callable[[str], str] | None = None
    # A verifier observes the resulting state after the handler returns. It
    # receives the reviewed value and the handler result and returns either a
    # bool or a VerificationResult (kept loosely typed to avoid a dependency
    # cycle). Actions without a verifier remain honestly "reported", rather
    # than being presented as externally verified.
    verifier: Callable[[str, str], object] | None = None
    retry_safe: bool = False
    read_only: bool = False


class Registry:
    def __init__(self):
        self.actions: dict[str, Action] = {}
        self.errors: list[str] = []

    def register(self, action: Action) -> None:
        if not NAME.fullmatch(action.name) or action.name in self.actions:
            raise ValueError(f"Invalid or duplicate action: {action.name}")
        self.actions[action.name] = action

    def discover(self, folder: Path) -> None:
        for path in sorted(folder.glob("*.py")):
            if path.name.startswith("_"):
                continue
            try:
                spec = importlib.util.spec_from_file_location(f"jarvis_skill_{path.stem}", path)
                if not spec or not spec.loader:
                    raise ImportError("No module loader")
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                skill = getattr(module, "SKILL", None)
                if not isinstance(skill, dict) or not isinstance(skill.get("actions"), list):
                    raise ValueError("SKILL must contain an actions list")
                for item in skill["actions"]:
                    self.register(Action(**item))
            except Exception as exc:
                self.errors.append(f"{path.name}: {exc}")
