import tempfile
import unittest
import sys
import json
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

from core import backup, capabilities, config, instructions, local_core, manager_prompt, memory, metrics, permissions, planner, plugin_runtime, plugins, prompt, recovery, routines, weather, providers, workspace
from core.intent import is_weather_query, quick_reply, requested_location
from core.llm import (
    LLMClient, LLMError, _api_error, inspect_gemini_connection, normalize_gemini_key,
    route_mode, valid_gemini_key_format, validate_gemini_key,
)
from core.skills import Action, Registry
from core.tasks import Step, TaskExecutor
from core.desktop_intent import parse as parse_desktop_command
from core.windows_automation import split_target_text, validate_control_name, validate_target_text
from core.voice import VOICE_STYLES, _spoken_text
from core.speech import transcribe_fast_free, transcribe_offline
from core.language import detect_language, speech_locale, voice_for_text
from core.retrieval import relevance
from core.voice_activity import silence_blocks, valid_capture


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.old = (config.APP_DIR, config.CONFIG_PATH, memory.MEMORY_PATH, instructions.PATH,
                    manager_prompt.PATH, workspace.APP_DIR)
        config.APP_DIR = root
        config.CONFIG_PATH = root / "config.json"
        memory.MEMORY_PATH = root / "memory.json"
        instructions.PATH = root / "custom_instructions.txt"
        manager_prompt.PATH = root / "manager_prompt.txt"
        workspace.APP_DIR = root

    def tearDown(self):
        (config.APP_DIR, config.CONFIG_PATH, memory.MEMORY_PATH, instructions.PATH,
         manager_prompt.PATH, workspace.APP_DIR) = self.old
        self.tmp.cleanup()

    def test_prompt_precedes_relevant_memory(self):
        memory.remember("projects", "jarvis", "Futuristic desktop assistant")
        messages = prompt.system_messages("Tell me about Jarvis")
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("trusted AI brother", messages[0]["content"])
        self.assertIn("coordination manager", messages[0]["content"])
        self.assertIn("Futuristic desktop assistant", messages[1]["content"])

    def test_manager_prompt_is_separate_editable_and_rejects_secrets(self):
        manager_prompt.save("Coordinate projects and show the next action.")
        self.assertIn("Coordinate projects", prompt.system_messages("plan today")[0]["content"])
        with self.assertRaises(ValueError):
            manager_prompt.save("api_key=sk-abcdefghijklmnopqrstuvwxyz")
        self.assertIn("coordination manager", manager_prompt.restore_default())

    def test_plugin_manager_blocks_disabled_desktop_control(self):
        self.assertTrue(any(item.plugin_id == "chatgpt" and not item.installed for item in plugins.CATALOG))
        plugins.set_enabled({"desktop": False})
        registry = Registry(); registry.register(Action("test_action", "Test", "Test", lambda value: value))
        with self.assertRaises(PermissionError):
            TaskExecutor(registry).execute([Step("test_action", "blocked")])

    def test_desktop_plugin_discovers_bounded_control_actions(self):
        registry = Registry()
        registry.discover(Path(__file__).resolve().parent.parent / "skills")
        self.assertEqual(registry.errors, [])
        self.assertTrue({"open_app", "click_point", "move_pointer", "double_click", "right_click",
                         "scroll", "media_key", "screenshot", "inspect_active_app", "focus_window",
                         "invoke_control", "set_control_text", "window_layout"}
                        <= set(registry.actions))

    def test_app_aware_values_are_validated_before_execution(self):
        self.assertEqual(split_target_text("Search || Reda's project"), ("Search", "Reda's project"))
        self.assertEqual(validate_target_text("  Search box  ||  new query  "), "Search box || new query")
        self.assertEqual(validate_control_name("  Save   As  "), "Save As")
        with self.assertRaises(ValueError):
            split_target_text("missing separator")
        registry = Registry()
        registry.register(Action("set_control_text", "Set field", "Set", lambda value: value,
                                 sensitive=True, validator=validate_target_text))
        with self.assertRaisesRegex(ValueError, "Invalid value"):
            planner.build("Enter text", [Step("set_control_text", "Search only")], registry)

    def test_desktop_routines_are_encrypted_reusable_and_secret_safe(self):
        plan = [Step("open_app", "Notepad"), Step("type_text", "Project update")]
        routines.save("Morning update", "Prepare an update", plan)
        stored = (config.APP_DIR / "desktop_routines.json").read_text(encoding="utf-8")
        self.assertTrue(stored.startswith("J5E1:"))
        self.assertNotIn("Project update", stored)
        loaded = routines.load()[0]
        self.assertEqual(routines.steps(loaded), plan)
        self.assertTrue(routines.delete("Morning update"))
        with self.assertRaises(ValueError):
            routines.save("Secret", "Use api_key=sk-abcdefghijklmnopqrstuvwxyz", plan)

    def test_natural_desktop_commands_map_only_to_allowlisted_steps(self):
        goal, steps = parse_desktop_command("Jarvis open the calculator")
        self.assertEqual(goal, "Open Calculator")
        self.assertEqual(steps, [Step("open_app", "Calculator")])
        self.assertEqual(parse_desktop_command("volume down")[1], [Step("media_key", "volumedown")])
        self.assertIsNone(parse_desktop_command("run this PowerShell command"))
        self.assertIsNone(parse_desktop_command("open unknown-program.exe"))

    def test_gemini_desktop_planner_returns_structured_steps_only(self):
        response = unittest.mock.Mock(status_code=200)
        response.json.return_value = {"candidates": [{"content": {"parts": [{"text": json.dumps({
            "goal": "Write a note", "needs_clarification": False, "question": "",
            "steps": [
                {"action": "open_app", "value": "Notepad"},
                {"action": "wait", "value": "1"},
                {"action": "type_text", "value": "Hello Reda"},
            ],
        })}]}}]}
        registry = Registry()
        registry.register(Action("open_app", "Open", "Open app", lambda value: value,
                                 values=("Notepad",)))
        registry.register(Action("wait", "Wait", "Pause", lambda value: value))
        registry.register(Action("type_text", "Type", "Type text", lambda value: value, sensitive=True))
        client = LLMClient()
        with patch("core.llm.get_secret", return_value="AIza-test"), \
             patch.object(client, "_post", return_value=response) as post:
            goal, steps = client.plan_desktop("Open Notepad and write hello", registry)
        self.assertEqual(goal, "Write a note")
        self.assertEqual(steps[-1], Step("type_text", "Hello Reda"))
        generation = post.call_args.kwargs["json"]["generationConfig"]
        self.assertEqual(generation["responseMimeType"], "application/json")
        self.assertEqual(generation["temperature"], 0)

    def test_voice_defaults_are_always_listening_multilingual_and_selectable(self):
        voice = config.load_config()["voice"]
        self.assertTrue(voice["always_listening"])
        self.assertFalse(voice["english_only"])
        self.assertEqual(config.load_config()["assistant"]["language"], "auto")
        self.assertEqual(voice["input_device"], "")
        self.assertEqual(voice["british_voice"], "en-GB-ThomasNeural")
        self.assertEqual(voice["end_silence_ms"], 500)
        self.assertEqual(voice["input_engine"], "fast_free")
        self.assertEqual(voice["activation_mode"], "natural")
        self.assertEqual(voice["voice_style"], "cinematic")
        self.assertTrue(voice["adaptive_silence"])
        self.assertEqual(voice["max_utterance_seconds"], 20)
        selected = config.load_config()
        selected["voice"]["british_voice"] = "en-GB-RyanNeural"
        config.save_config(selected)
        self.assertEqual(config.load_config()["voice"]["british_voice"], "en-GB-RyanNeural")

    def test_voice_styles_offer_fast_deep_natural_and_custom_profiles(self):
        self.assertEqual(set(VOICE_STYLES), {"cinematic", "fast", "deep", "natural", "custom"})
        self.assertGreater(VOICE_STYLES["fast"]["rate"], VOICE_STYLES["cinematic"]["rate"])
        self.assertLess(VOICE_STYLES["deep"]["pitch"], VOICE_STYLES["cinematic"]["pitch"])

    def test_v51_voice_settings_migrate_to_natural_fast_profile(self):
        config.CONFIG_PATH.write_text(
            '{"voice":{"input_engine":"offline","british_voice":"en-GB-ThomasNeural",'
            '"recognition_profile_version":3,"output_profile_version":4,'
            '"speech_rate":-2,"speech_pitch":-4}}', encoding="utf-8")
        voice = config.load_config()["voice"]
        self.assertEqual(voice["input_engine"], "fast_free")
        self.assertEqual(voice["activation_mode"], "natural")
        self.assertEqual(voice["british_voice"], "en-GB-ThomasNeural")
        self.assertEqual((voice["speech_rate"], voice["speech_pitch"]), (-1, -4))

    def test_offline_speech_uses_local_recognizer(self):
        class Recognizer:
            def recognize_sphinx(self, audio, language):
                self.language = language
                return "  hey   jarvis plan today  "
        fake = SimpleNamespace(
            Recognizer=Recognizer,
            AudioData=lambda pcm, rate, width: (pcm, rate, width),
            UnknownValueError=ValueError,
        )
        with patch.dict(sys.modules, {"speech_recognition": fake}):
            text = transcribe_offline(b"\x00\x00" * 400, 16_000)
        self.assertEqual(text, "hey jarvis plan today")

    def test_fast_free_speech_uses_english_recognition_without_an_api_key(self):
        class Recognizer:
            def recognize_google(self, audio, language):
                self.language = language
                return "  plan   my day naturally  "
        fake = SimpleNamespace(
            Recognizer=Recognizer,
            AudioData=lambda pcm, rate, width: (pcm, rate, width),
            UnknownValueError=ValueError,
            RequestError=ConnectionError,
        )
        with patch.dict(sys.modules, {"speech_recognition": fake}):
            text = transcribe_fast_free(b"\x00\x00" * 400, 16_000)
        self.assertEqual(text, "plan my day naturally")

    def test_multilingual_language_voice_and_speech_routing(self):
        self.assertEqual(detect_language("Bonjour, comment peux-tu m'aider ?"), "fr")
        self.assertEqual(detect_language("كيف يمكنني تنظيم مشروعي؟"), "ar")
        self.assertEqual(speech_locale("es"), "es-ES")
        self.assertEqual(voice_for_text("Bonjour à tous", "en-GB-ThomasNeural", "auto"),
                         "fr-FR-HenriNeural")
        class Recognizer:
            locale = ""
            def recognize_google(self, audio, language):
                Recognizer.locale = language
                return "bonjour jarvis"
        fake = SimpleNamespace(
            Recognizer=Recognizer, AudioData=lambda pcm, rate, width: (pcm, rate, width),
            UnknownValueError=ValueError, RequestError=ConnectionError,
        )
        with patch.dict(sys.modules, {"speech_recognition": fake}):
            self.assertEqual(transcribe_fast_free(b"\x00\x00" * 400, 16_000, "fr"), "bonjour jarvis")
        self.assertEqual(Recognizer.locale, "fr-FR")

    def test_spoken_reply_removes_long_punctuation_pauses(self):
        spoken = _spoken_text("Good morning, Reda. The system is ready... Shall we begin?")
        self.assertNotRegex(spoken, r"[,;:…]")
        self.assertEqual(spoken, "Good morning Reda. The system is ready Shall we begin?")
        sourced = _spoken_text("Answer.\n\nSources:\n- Example: https://example.com/report")
        self.assertIn("Sources are shown on screen", sourced)
        self.assertNotIn("example.com", sourced)
        long_spoken = _spoken_text(("A useful sentence. " * 200).strip())
        self.assertLess(len(long_spoken), 1900)
        self.assertTrue(long_spoken.endswith("The full answer is on screen."))

    def test_adaptive_voice_activity_closes_short_turns_and_rejects_noise(self):
        self.assertEqual(silence_blocks(500, 4, True), 7)
        self.assertEqual(silence_blocks(500, 30, True), 10)
        self.assertEqual(silence_blocks(500, 4, False), 10)
        self.assertTrue(valid_capture(.001, .004, 4, 150))
        self.assertFalse(valid_capture(.001, .0012, 8, 150))

    def test_instant_intents_and_weather_location(self):
        self.assertEqual(quick_reply("Hi Jarvis", "JARVIS", "Reda"),
                         "Hello, Reda. How can I help?")
        self.assertTrue(is_weather_query("What's the weather report?"))
        self.assertEqual(requested_location("Weather in London?"), "London")
        self.assertEqual(quick_reply("Hola Jarvis", "JARVIS", "Reda", "es"),
                         "Hola, Reda. ¿Cómo puedo ayudarte?")
        self.assertTrue(is_weather_query("Quelle est la météo demain ?"))
        self.assertEqual(requested_location("Météo à Paris ?"), "Paris")

    def test_live_weather_report_uses_configured_location(self):
        payload = {
            "current": {"temperature_2m": 18, "apparent_temperature": 17,
                        "relative_humidity_2m": 60, "weather_code": 2,
                        "wind_speed_10m": 12},
            "daily": {"temperature_2m_max": [21], "temperature_2m_min": [11],
                      "precipitation_probability_max": [20]},
        }
        weather._CACHE.clear()
        with patch("core.weather.load_config", return_value={
                "weather": {"location": "Rabat", "automatic_location": False, "units": "metric"}}), \
             patch("core.weather._coordinates", return_value=(34.02, -6.84, "Rabat, Morocco")), \
             patch("core.weather._json", return_value=payload):
            result = weather.report()
            french = weather.report("", "fr")
        self.assertIn("Rabat, Morocco", result)
        self.assertIn("18°C", result)
        self.assertIn("partly cloudy", result)
        self.assertIn("À Rabat, Morocco", french)
        self.assertIn("partiellement nuageux", french)

    def test_legacy_integration_and_model_settings_do_not_return(self):
        config.CONFIG_PATH.write_text(
            '{"n8n":{"enabled":true,"webhook_path":"/old"},'
            '"voice":{"wake_phrase":"hey jarvis"},'
            '"llm":{"fast_model":"retired-model"}}', encoding="utf-8")
        loaded = config.load_config()
        self.assertNotIn("n8n", loaded)
        self.assertEqual(loaded["voice"]["wake_phrase"], "hey jarvis")
        self.assertEqual(loaded["llm"]["fast_model"], "gemini-3.5-flash-lite")

    def test_gemini_modes_select_fast_search_and_reflection_payloads(self):
        response = unittest.mock.Mock(status_code=200)
        response.json.return_value = {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}
        client = LLMClient()
        messages = [{"role": "system", "content": "protected"},
                    {"role": "user", "content": "question"}]
        with patch("core.llm.get_secret", return_value="AIza-test"), \
             patch.object(client.session, "post", return_value=response) as post:
            client._gemini(messages, config.load_config(), "chat")
            self.assertIn("gemini-3.5-flash-lite", post.call_args.args[0])
            client._gemini(messages, config.load_config(), "deep_search")
            self.assertEqual(post.call_args.kwargs["json"]["tools"], [{"google_search": {}}])
            client._gemini(messages, config.load_config(), "reflection")
            thinking = post.call_args.kwargs["json"]["generationConfig"]["thinkingConfig"]
            self.assertEqual(thinking["thinkingBudget"], 2048)

    def test_auto_intelligence_routes_to_lightest_reliable_mode(self):
        self.assertEqual(route_mode("Write a short welcome message"), "chat")
        self.assertEqual(route_mode("What is the latest Gemini news today?"), "deep_search")
        self.assertEqual(route_mode("Analyse the risks and help me decide"), "reflection")
        self.assertEqual(route_mode("Quelles sont les dernières actualités avec des sources ?"), "deep_search")
        self.assertEqual(route_mode("حلل المخاطر وساعدني في اتخاذ قرار"), "reflection")

    def test_intelligence_profiles_change_reasoning_and_answer_budget(self):
        response = unittest.mock.Mock(status_code=200)
        response.json.return_value = {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}
        client = LLMClient(); messages = [{"role": "user", "content": "Analyse this plan"}]
        thorough = config.load_config()
        thorough["assistant"].update({"intelligence_profile": "thorough", "response_length": "detailed"})
        with patch("core.llm.get_secret", return_value="AIza-test"), \
             patch.object(client.session, "post", return_value=response) as post:
            client._gemini(messages, thorough, "reflection")
        generation = post.call_args.kwargs["json"]["generationConfig"]
        self.assertEqual(generation["thinkingConfig"]["thinkingBudget"], 3072)
        self.assertGreaterEqual(generation["maxOutputTokens"], 1800)

    def test_multilingual_retrieval_handles_unicode_and_diacritics(self):
        self.assertGreater(relevance("strategie commerciale", "Notre stratégie commerciale pour demain"), 0)
        memory.remember("projects", "école", "Préparer le contrôle de mathématiques")
        self.assertEqual(memory.search("preparer mathematiques")[0]["key"], "école")

    def test_voice_turn_uses_one_gemini_request_for_transcript_and_answer(self):
        response = unittest.mock.Mock(status_code=200)
        response.json.return_value = {"candidates": [{"content": {"parts": [{
            "text": "<status>ok</status><transcript>Plan my day</transcript>"
                    "<answer>Start with your most important task.</answer>"
        }]}}]}
        client = LLMClient()
        with patch("core.llm.get_secret", return_value="AIza-test"), \
             patch.object(client.session, "post", return_value=response) as post:
            result = client.chat_audio(b"\x00\x00" * 4000, 16_000)
        self.assertEqual(post.call_count, 1)
        self.assertEqual(result["transcript"], "Plan my day")
        self.assertIn("important task", result["answer"])

    def test_structured_gemini_voice_rejects_low_confidence_background_audio(self):
        response = unittest.mock.Mock(status_code=200)
        response.json.return_value = {"candidates": [{"content": {"parts": [{"text": json.dumps({
            "status": "ok", "transcript": "maybe television", "answer": "Hello",
            "detected_language": "en", "confidence": .2,
        })}]}}]}
        client = LLMClient()
        with patch("core.llm.get_secret", return_value="AIza-test"), \
             patch.object(client.session, "post", return_value=response) as post:
            result = client.chat_audio(b"\x00\x00" * 4000, 16_000)
        self.assertEqual(result["status"], "no_speech")
        generation = post.call_args.kwargs["json"]["generationConfig"]
        self.assertEqual(generation["responseMimeType"], "application/json")
        self.assertIn("confidence", generation["responseSchema"]["required"])

    def test_voice_429_uses_one_different_available_model(self):
        limited = unittest.mock.Mock(status_code=429)
        success = unittest.mock.Mock(status_code=200)
        success.json.return_value = {"candidates": [{"content": {"parts": [{
            "text": "<status>ok</status><transcript>Hello</transcript><answer>Hello, Reda.</answer>"
        }]}}]}
        client = LLMClient()
        with patch("core.llm.get_secret", return_value="AIza-test"), \
             patch("core.llm._AVAILABLE_MODELS", {"gemini-3.5-flash-lite", "gemini-3.5-flash"}), \
             patch.object(client.session, "post", side_effect=[limited, success]) as post:
            result = client.chat_audio(b"\x00\x00" * 4000, 16_000, "auto")
        self.assertEqual(post.call_count, 2)
        self.assertIn("gemini-3.5-flash:", post.call_args.args[0])
        self.assertEqual(result["answer"], "Hello, Reda.")
        self.assertNotIn("tools", post.call_args.kwargs["json"])

    def test_text_chat_recovers_from_model_specific_rate_limit(self):
        limited = unittest.mock.Mock(status_code=429)
        success = unittest.mock.Mock(status_code=200)
        success.json.return_value = {"candidates": [{"content": {"parts": [{"text": "Recovered answer"}]}}]}
        client = LLMClient(); messages = [{"role": "user", "content": "Help me plan"}]
        with patch("core.llm.get_secret", return_value="AIza-test"), \
             patch("core.llm._AVAILABLE_MODELS", {"gemini-3.5-flash-lite", "gemini-3.5-flash"}), \
             patch.object(client.session, "post", side_effect=[limited, success]) as post:
            answer = client._gemini(messages, config.load_config(), "chat")
        self.assertEqual(answer, "Recovered answer")
        self.assertEqual(post.call_count, 2)
        self.assertIn("gemini-3.5-flash:", post.call_args.args[0])

    def test_credentials_are_never_stored(self):
        result = memory.remember("notes", "api_key", "sk-abcdefghijklmnopqrstuvwxyz")
        self.assertTrue(result.startswith("Refused:"))
        self.assertEqual(memory.search(), [])

    def test_memory_round_trip_and_forget(self):
        memory.remember("businesses", "studio", "Benyassek Studio")
        self.assertNotIn("Benyassek Studio", memory.MEMORY_PATH.read_text(encoding="utf-8"))
        self.assertTrue(memory.MEMORY_PATH.read_text(encoding="utf-8").startswith("J5E1:"))
        self.assertEqual(memory.search("studio")[0]["value"], "Benyassek Studio")
        self.assertTrue(memory.forget("studio").startswith("Forgotten"))

    def test_v6_organized_memory_metadata_and_editing(self):
        memory.remember("goals", "v6", "Ship a stable assistant", importance=5, pinned=True)
        row = memory.search("stable assistant")[0]
        self.assertEqual((row["importance"], row["pinned"], row["source"]), (5, True, "user"))
        self.assertTrue(memory.update("goals", "v6", value="Ship a tested stable assistant", pinned=False))
        updated = memory.search("tested stable")[0]
        self.assertFalse(updated["pinned"])

    def test_v6_local_core_answers_without_a_provider(self):
        from datetime import datetime
        self.assertEqual(local_core.respond("what time is it", datetime(2026, 11, 2, 14, 30)), "It is 14:30.")
        self.assertIn("local core is online", local_core.respond("system status").lower())

    def test_v6_planner_validates_allowlist_and_permissions(self):
        registry = Registry()
        registry.register(Action("open_app", "Open application", "Open", lambda value: value,
                                 values=("Notepad",)))
        plan = planner.build("Open my notes", [Step("open_app", "Notepad")], registry)
        self.assertEqual(plan.steps[0].label, "Open application")
        self.assertFalse(plan.requires_approval)
        with self.assertRaises(ValueError):
            planner.build("Open unknown", [Step("open_app", "Unknown.exe")], registry)

    def test_v6_plugin_manifests_cannot_load_arbitrary_code(self):
        manifest = config.APP_DIR / "plugin.json"
        manifest.write_text(
            '{"id":"calendar","name":"Calendar","version":"1.0.0",'
            '"adapter":"calendar_adapter","permissions":["calendar_read"]}', encoding="utf-8")
        loaded = plugin_runtime.load_manifest(manifest, {"calendar_adapter"})
        self.assertEqual(loaded.permissions, ("calendar_read",))
        manifest.write_text(
            '{"id":"shell","name":"Shell","version":"1.0.0",'
            '"adapter":"../../evil.py","permissions":["arbitrary_shell"]}', encoding="utf-8")
        with self.assertRaises(ValueError):
            plugin_runtime.load_manifest(manifest, {"calendar_adapter"})

    def test_v6_capabilities_label_future_features_honestly(self):
        registry = Registry(); registry.register(Action("test_action", "Test", "Test", lambda value: value))
        with patch("core.capabilities.get_secret", return_value=""):
            rows = {row["id"]: row for row in capabilities.snapshot(registry)}
        self.assertEqual(rows["iphone_interface"]["state"], "future")
        self.assertEqual(rows["remote_relay"]["state"], "future")
        self.assertNotEqual(rows["desktop_control"]["state"], "future")
        self.assertEqual(rows["natural_desktop"]["state"], "setup_required")
        self.assertEqual(rows["memory"]["state"], "ready")
        self.assertEqual(rows["multilingual"]["state"], "ready")
        with patch("core.capabilities.get_secret", return_value="AIza-test"):
            connected = {row["id"]: row for row in capabilities.snapshot(registry)}
        self.assertEqual(connected["deep_research"]["state"], "ready")
        self.assertEqual(connected["natural_desktop"]["state"], "ready")

    def test_password_backup_is_encrypted_and_inspectable(self):
        config.CONFIG_PATH.write_text('{"assistant":{"name":"JARVIS"}}', encoding="utf-8")
        destination = config.APP_DIR / "test.j5backup"
        backup.create(destination, "strong-password")
        raw = destination.read_bytes()
        self.assertTrue(raw.startswith(backup.MAGIC))
        self.assertNotIn(b'"assistant"', raw)
        self.assertIn("manifest.json", backup.inspect(destination, "strong-password"))
        with self.assertRaises(ValueError): backup.inspect(destination, "wrong-password")

    def test_recovery_state_is_encrypted_and_detects_interruption(self):
        recovery.save({"draft": "unfinished private draft", "chat_mode": "reflection"}, clean_exit=False)
        self.assertNotIn(b"unfinished private draft", (config.APP_DIR / "recovery.state").read_bytes())
        restored = recovery.begin()
        self.assertEqual(restored["draft"], "unfinished private draft")

    def test_runtime_metrics_report_latency(self):
        metrics.record("test.operation", .125)
        row = next(item for item in metrics.snapshot() if item["name"] == "test.operation")
        self.assertEqual(row["latest_ms"], 125)

    def test_application_permission_overrides_global_action_policy(self):
        action = Action("open_app", "Open app", "Open an approved application", lambda value: value)
        cfg = config.load_config(); cfg["permissions"]["low_risk"] = "automatic"
        cfg["permissions"]["applications"] = {"Notepad": "ask", "Calculator": "allow"}
        with patch("core.permissions.load_config", return_value=cfg):
            self.assertTrue(permissions.decide(action, "Notepad").approval_required)
            self.assertFalse(permissions.decide(action, "Calculator").approval_required)

    def test_today_record_can_be_completed_without_losing_history(self):
        item = workspace.save("Today", "Finish maths", "Created now")
        workspace.save("Completed", "Finish maths", "Completed now")
        workspace.delete(item)
        self.assertEqual(workspace.records("Today"), [])
        self.assertEqual(workspace.records("Completed")[0][1], "Finish maths")

    def test_provider_router_uses_only_installed_enabled_provider(self):
        cfg = config.load_config()
        cfg["providers"]["primary"] = "anthropic"
        cfg["providers"]["enabled"]["anthropic"] = True
        self.assertEqual(providers.select(cfg).provider_id, "gemini")

    def test_gemini_key_is_tested_before_it_is_saved(self):
        models = unittest.mock.Mock(status_code=200)
        models.json.return_value = {"models": [{
            "name": "models/gemini-3.5-flash-lite",
            "supportedGenerationMethods": ["generateContent"],
        }]}
        generated = unittest.mock.Mock(status_code=200)
        generated.json.return_value = {"candidates": [{"content": {"parts": [{"text": "CONNECTED"}]}}]}
        with patch("core.llm.requests.get", return_value=models), \
             patch("core.llm.requests.post", return_value=generated):
            key = "AIza" + "A" * 32
            result = validate_gemini_key(key, True)
        self.assertIn("Gemini connected successfully", result)
        rejected = unittest.mock.Mock(status_code=403)
        with patch("core.llm.requests.get", return_value=rejected), self.assertRaises(LLMError):
            validate_gemini_key("not-a-key")

    def test_gemini_registration_returns_safe_stage_diagnostics(self):
        models = unittest.mock.Mock(status_code=200)
        models.json.return_value = {"models": [{
            "name": "models/gemini-3.5-flash-lite", "supportedGenerationMethods": ["generateContent"],
        }]}
        generated = unittest.mock.Mock(status_code=429)
        key = "AIza" + "B" * 32
        with patch("core.llm.requests.get", return_value=models), \
             patch("core.llm.requests.post", return_value=generated):
            report = inspect_gemini_connection(key, True)
        self.assertEqual(report["generation"], "quota_limited")
        self.assertEqual(report["model_count"], 1)
        self.assertNotIn(key, json.dumps(report))
        leaked = unittest.mock.Mock()
        leaked.json.return_value = {"error": {"message": f"token={key}"}}
        self.assertNotIn(key, _api_error(leaked))

    def test_gemini_key_can_be_extracted_from_pasted_text(self):
        key = "AIza" + "A" * 32
        self.assertEqual(normalize_gemini_key(f"Here is the key: `{key}`\n"), key)
        self.assertTrue(valid_gemini_key_format(key))
        self.assertFalse(valid_gemini_key_format("AQ.oauth-token"))

    def test_verified_key_is_not_rejected_when_optional_generation_times_out(self):
        models = unittest.mock.Mock(status_code=200)
        models.json.return_value = {"models": [{
            "name": "models/gemini-3.5-flash-lite",
            "supportedGenerationMethods": ["generateContent"],
        }]}
        import requests
        with patch("core.llm.requests.get", return_value=models), \
             patch("core.llm.requests.post", side_effect=requests.Timeout):
            result = validate_gemini_key("AIza" + "A" * 32, True)
        self.assertIn("key can still be saved", result)

    def test_custom_instructions_are_separate_and_reject_secrets(self):
        instructions.save("Be concise and prioritize schoolwork.")
        self.assertIn("prioritize schoolwork", prompt.system_messages("hello")[0]["content"])
        with self.assertRaises(ValueError):
            instructions.save("api_key=sk-abcdefghijklmnopqrstuvwxyz")

    def test_persistent_desktop_access_uses_registered_actions(self):
        calls = []
        registry = Registry()
        registry.register(Action("test_action", "Test action", "Test", lambda value: calls.append(value) or "done"))
        executor = TaskExecutor(registry)
        cfg = config.load_config()
        self.assertTrue(cfg["desktop"]["persistent_access"])
        self.assertFalse(cfg["assistant"]["serious_mode"])
        progress = []
        with patch("core.tasks.record") as audit_record:
            self.assertEqual(
                executor.execute([Step("test_action", "one")],
                                 progress=lambda current, total, label: progress.append((current, total, label))),
                ["1. done"],
            )
        self.assertEqual(progress, [(1, 1, "Test action")])
        self.assertEqual(audit_record.call_count, 2)
        self.assertEqual(audit_record.call_args_list[-1].args[-1], "reported")
        self.assertEqual(calls, ["one"])

    def test_desktop_failure_identifies_the_exact_step(self):
        registry = Registry()
        registry.register(Action("broken_action", "Broken action", "Test",
                                 lambda _value: (_ for _ in ()).throw(ValueError("window unavailable"))))
        with patch("core.tasks.record") as audit_record, self.assertRaisesRegex(
                RuntimeError, r"Step 1 \(Broken action\) failed: window unavailable"):
            TaskExecutor(registry).execute([Step("broken_action", "one")])
        self.assertIn("failed: window unavailable", audit_record.call_args.args[-1])

    def test_sensitive_desktop_action_is_enforced_in_backend(self):
        registry = Registry()
        registry.register(Action("sensitive_action", "Sensitive", "Test", lambda value: "done", sensitive=True))
        executor = TaskExecutor(registry)
        with self.assertRaises(PermissionError):
            executor.execute([Step("sensitive_action", "private")])
        self.assertEqual(
            executor.execute([Step("sensitive_action", "private")], approved_sensitive=True),
            ["1. done"],
        )


if __name__ == "__main__":
    unittest.main()
