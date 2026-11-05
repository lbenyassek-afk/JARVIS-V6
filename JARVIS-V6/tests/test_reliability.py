import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import config
from core.adapters import AdapterCapability, AdapterRegistry, AdapterStatus
from core.benchmarks import run_suite
from core.mission_graph import MissionGraph, MissionNode, MissionStore
from core.plugin_runtime import load_manifest, verify_payload_integrity
from core.skills import Action, Registry
from core.tasks import Step, TaskExecutor
from core.verification import VerificationResult
from core.pillars import snapshot as pillar_snapshot


class ReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.old_app_dir, self.old_config_path = config.APP_DIR, config.CONFIG_PATH
        config.APP_DIR = self.root
        config.CONFIG_PATH = self.root / "config.json"

    def tearDown(self):
        config.APP_DIR, config.CONFIG_PATH = self.old_app_dir, self.old_config_path
        self.tmp.cleanup()

    def test_dependency_graph_rejects_cycles_and_exposes_only_ready_nodes(self):
        graph = MissionGraph("Save a note", [
            MissionNode("open", "open_app", "Notepad"),
            MissionNode("write", "type_text", "Hello", ("open",)),
        ])
        graph.validate()
        self.assertEqual([node.node_id for node in graph.ready()], ["open"])
        cyclic = MissionGraph("bad", [MissionNode("a", "x", "", ("b",)),
                                      MissionNode("b", "x", "", ("a",))])
        with self.assertRaisesRegex(ValueError, "cycle"):
            cyclic.validate()

    def test_mission_checkpoint_is_encrypted_and_round_trips(self):
        graph = MissionGraph.sequential([Step("inspect", "private window")])
        store = MissionStore(); store.save(graph)
        raw = store.path().read_text(encoding="utf-8")
        self.assertTrue(raw.startswith("J5E1:")); self.assertNotIn("private window", raw)
        self.assertEqual(store.load().nodes[0].value, "private window")
        registry = Registry(); executor = TaskExecutor(registry)
        self.assertEqual(executor.interrupted_mission().mission_id, graph.mission_id)
        executor.discard_checkpoint(); self.assertIsNone(executor.interrupted_mission())

    def test_verification_retries_only_idempotent_actions(self):
        calls = []
        def verifier(_value, _result):
            return VerificationResult(len(calls) > 1, "observed" if len(calls) > 1 else "not yet")
        registry = Registry()
        registry.register(Action("retry_action", "Retry", "Test", lambda value: calls.append(value) or "done",
                                 verifier=verifier, retry_safe=True))
        cfg = config.load_config(); cfg["desktop"].update({"step_delay": 0, "verification_settle_seconds": 0,
                                                            "verification_retries": 1})
        with patch("core.tasks.load_config", return_value=cfg), patch("core.tasks.plugin_enabled", return_value=True):
            self.assertEqual(TaskExecutor(registry).execute([Step("retry_action", "x")]), ["1. done"])
        self.assertEqual(calls, ["x", "x"])

    def test_failed_verification_blocks_dependants_and_preserves_checkpoint(self):
        registry = Registry()
        registry.register(Action("bad", "Bad", "Test", lambda _value: "reported",
                                 verifier=lambda _value, _result: False))
        registry.register(Action("later", "Later", "Test", lambda _value: "must not run"))
        graph = MissionGraph("failure", [MissionNode("first", "bad", ""),
                                          MissionNode("second", "later", "", ("first",))])
        cfg = config.load_config(); cfg["desktop"].update({"step_delay": 0, "verification_settle_seconds": 0})
        with patch("core.tasks.plugin_enabled", return_value=True), self.assertRaisesRegex(RuntimeError, "Expected state"):
            TaskExecutor(registry).execute_graph(graph, cfg=cfg)
        recovered = MissionStore().load()
        self.assertEqual([node.state for node in recovered.nodes], ["failed", "blocked"])

    def test_dry_run_validates_without_calling_handler(self):
        calls = []
        registry = Registry(); registry.register(Action("safe", "Safe", "Test", lambda value: calls.append(value)))
        cfg = config.load_config(); cfg["desktop"]["isolation_profile"] = "dry_run"
        with patch("core.tasks.load_config", return_value=cfg), patch("core.tasks.plugin_enabled", return_value=True):
            result = TaskExecutor(registry).execute([Step("safe", "preview")])
        self.assertIn("SIMULATED", result[0]); self.assertEqual(calls, [])

    def test_adapter_contract_blocks_undeclared_and_unapproved_operations(self):
        registry = AdapterRegistry()
        registry.register(AdapterStatus("calendar", True, "ready", (
            AdapterCapability("create_event", "Create event", False, True),)),
            {"create_event": lambda payload: payload["title"]})
        with self.assertRaises(PermissionError):
            registry.invoke("calendar", "create_event", {"title": "Study"})
        self.assertEqual(registry.invoke("calendar", "create_event", {"title": "Study"}, True), "Study")
        with self.assertRaises(ValueError):
            registry.invoke("calendar", "delete_everything", {}, True)

    def test_plugin_manifest_validates_typed_operations_domains_and_integrity(self):
        payload = self.root / "payload.bin"; payload.write_bytes(b"trusted payload")
        import hashlib
        digest = "sha256:" + hashlib.sha256(payload.read_bytes()).hexdigest()
        manifest = self.root / "plugin.json"
        manifest.write_text(json.dumps({
            "id": "tasks", "name": "Tasks", "version": "1.2.0", "adapter": "task_adapter",
            "permissions": ["business_data"], "domains": ["api.example.com"],
            "integrity": digest,
            "operations": [{"id": "create_task", "input_type": "object", "approval": "inherit"}],
        }), encoding="utf-8")
        loaded = load_manifest(manifest, {"task_adapter"})
        self.assertEqual(loaded.operations[0].operation_id, "create_task")
        self.assertTrue(verify_payload_integrity(payload, loaded.integrity))

    def test_offline_benchmark_suite_passes(self):
        report = run_suite(False)
        self.assertEqual(report["failed"], 0)
        self.assertGreaterEqual(report["passed"], 6)

    def test_product_pillars_have_stable_priority_and_honest_registration(self):
        registry = Registry(); registry.register(Action("safe", "Safe", "Test", lambda value: value))
        with patch("core.pillars.get_secret", return_value=""):
            rows = pillar_snapshot(registry)
        self.assertEqual([item["id"] for item in rows],
                         ["foundation", "registration", "desktop", "speed", "voice"])
        self.assertFalse(rows[1]["ready"])
        self.assertTrue(rows[2]["ready"])


if __name__ == "__main__":
    unittest.main()
