from __future__ import annotations

import json
import platform
import statistics
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from . import config
from .crypto import open_text, seal
from .mission_graph import MissionGraph, MissionNode
from .plugin_runtime import PluginOperation
from .semantic import similarity
from .verification import verify


@dataclass(frozen=True)
class BenchmarkCase:
    name: str
    passed: bool
    duration_ms: float
    detail: str


def _case(name: str, operation) -> BenchmarkCase:
    started = time.perf_counter()
    try:
        detail = str(operation())
        passed = True
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"
        passed = False
    return BenchmarkCase(name, passed, round((time.perf_counter() - started) * 1000, 3), detail)


def run_suite(write_report: bool = False) -> dict:
    """Run fast, offline checks that can fail when reliability contracts regress."""
    def encryption():
        private = "private benchmark payload"
        wrapped = seal(private)
        assert private not in wrapped and open_text(wrapped) == private
        return "Encrypted storage round-trip preserved confidentiality"

    def graph():
        mission = MissionGraph("benchmark", [
            MissionNode("observe", "inspect", "active"),
            MissionNode("act", "invoke", "Save", ("observe",)),
            MissionNode("confirm", "inspect", "saved", ("act",)),
        ])
        mission.validate()
        assert [item.node_id for item in mission.ready()] == ["observe"]
        return "Dependency order and graph validation passed"

    def cycle_guard():
        bad = MissionGraph("cycle", [MissionNode("a", "x", "", ("b",)),
                                      MissionNode("b", "x", "", ("a",))])
        try:
            bad.validate()
        except ValueError:
            return "Cyclic plan rejected"
        raise AssertionError("Cyclic plan was accepted")

    def postcondition():
        outcome = verify(lambda value, result: value == result, "expected", "expected")
        assert outcome.verified and outcome.observed
        failure = verify(lambda _value, _result: False, "x", "y")
        assert not failure.verified
        return "Positive and negative postconditions distinguished"

    def retrieval():
        related = similarity("project planning", "planning the project milestones")
        unrelated = similarity("project planning", "cinematic voice microphone")
        assert related > unrelated
        return f"Related={related:.3f}; unrelated={unrelated:.3f}"

    def typed_contract():
        contract = PluginOperation("create_task", "Create one task", "object", "inherit")
        assert contract.input_type == "object" and contract.operation_id == "create_task"
        return "Typed plugin operation contract constructed"

    cases = [_case("Encrypted storage", encryption), _case("Mission dependency graph", graph),
             _case("Cycle rejection", cycle_guard), _case("Postcondition verification", postcondition),
             _case("Local related-memory retrieval", retrieval),
             _case("Typed plugin contract", typed_contract)]
    durations = [item.duration_ms for item in cases]
    report = {
        "schema": 1,
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "platform": platform.system(),
        "python": platform.python_version(),
        "passed": sum(item.passed for item in cases),
        "failed": sum(not item.passed for item in cases),
        "total_ms": round(sum(durations), 3),
        "median_ms": round(statistics.median(durations), 3) if durations else 0,
        "cases": [asdict(item) for item in cases],
    }
    if write_report:
        config.APP_DIR.mkdir(parents=True, exist_ok=True)
        destination = config.APP_DIR / "benchmark-latest.json"
        temporary = destination.with_suffix(".tmp")
        temporary.write_text(json.dumps(report, indent=2), encoding="utf-8")
        temporary.replace(destination)
        report["report_path"] = str(destination)
    return report
