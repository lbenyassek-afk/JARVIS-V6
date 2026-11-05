import unittest
import tempfile
import http.client
import json
from pathlib import Path
from unittest.mock import patch, Mock
from core.session import VoiceSession
from core import workspace, config, conversation
from core.companion import CompanionServer
from core.llm import LLMClient

class V6Tests(unittest.TestCase):
    def test_v6_icon_contains_standard_windows_sizes(self):
        icon = Path(__file__).resolve().parent.parent / "jarvis.ico"
        raw = icon.read_bytes()
        self.assertEqual(raw[:4], b"\x00\x00\x01\x00")
        self.assertGreaterEqual(int.from_bytes(raw[4:6], "little"), 10)

    def test_companion_requires_auth_and_only_queues_commands(self):
        server = CompanionServer("127.0.0.1", 0, "test-companion-token")
        host, port = server.start()
        try:
            connection = http.client.HTTPConnection(host, port, timeout=3)
            connection.request("POST", "/v1/commands", json.dumps({"text": "plan my day"}),
                               {"Content-Type": "application/json"})
            self.assertEqual(connection.getresponse().status, 401)
            connection.close()
            connection = http.client.HTTPConnection(host, port, timeout=3)
            body = json.dumps({"requestId": "phone-1", "text": "plan my day"})
            connection.request("POST", "/v1/commands", body,
                               {"Content-Type": "application/json",
                                "Authorization": "Bearer test-companion-token"})
            self.assertEqual(connection.getresponse().status, 202)
            self.assertEqual(server.next_command().text, "plan my day")
        finally:
            connection.close(); server.stop()
    def test_wake_timeout_and_goodbye(self):
        session=VoiceSession(10, wake_phrases=['hey jarvis', 'jarvis'])
        self.assertIsNone(session.accept('hello',now=1))
        self.assertEqual(session.accept('Hey Jarvis plan today',now=2),'plan today')
        self.assertEqual(session.accept('continue',now=3),'continue')
        self.assertIsNone(session.accept('continue',now=14))
        session.accept('hey jarvis',now=15)
        self.assertIsNone(session.accept('goodbye',now=16))
        self.assertIsNone(session.accept('continue',now=17))
        self.assertEqual(session.accept('Jarvis check memory', now=18), 'check memory')

    def test_natural_voice_does_not_require_wake_phrase(self):
        session = VoiceSession(45, wake_phrases=['hey jarvis', 'jarvis'])
        self.assertEqual(session.resolve('plan my afternoon', require_wake=False, now=1),
                         'plan my afternoon')
        self.assertEqual(session.resolve('hey jarvis check the weather', require_wake=False, now=2),
                         'check the weather')
    def test_records_persist_and_reject_credentials(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(workspace, 'APP_DIR', Path(tmp)), \
             patch.object(config, 'APP_DIR', Path(tmp)):
            workspace.save('Projects','School','Study chapter one')
            self.assertEqual(workspace.records('Projects')[0][1],'School')
            raw = (Path(tmp) / 'workspace.sqlite3').read_bytes()
            self.assertNotIn(b'Study chapter one', raw)
            with self.assertRaises(ValueError): workspace.save('Projects','password','secret')
    def test_profile_is_v6(self):
        self.assertEqual(config.APP_DIR.name,'JARVIS-V6')
        self.assertEqual(config.DEFAULTS['interface']['visual_mode'], 'orb')
        self.assertEqual(config.DEFAULTS['interface']['presence_profile_version'], 1)

    def test_v6_presence_offers_five_distinct_saved_designs(self):
        from ui.main_window import PRESENCE_MODES, PRESENCE_STATUS
        modes = [value for _label, value in PRESENCE_MODES]
        self.assertEqual(modes, ['orb', 'core', 'face', 'hybrid', 'minimal'])
        self.assertEqual(set(modes), set(PRESENCE_STATUS))

    def test_v6_appearance_themes_are_coordinated_and_customizable(self):
        from ui.main_window import THEME_PRESETS, resolve_theme
        self.assertEqual(len(THEME_PRESETS), 6)
        self.assertEqual(resolve_theme({'appearance_profile': 'arctic'})['accent'], '#65C7FF')
        custom = resolve_theme({'appearance_profile': 'obsidian', 'accent_color': '#12abef'})
        self.assertEqual(custom['accent'], '#12ABEF')
        invalid = resolve_theme({'appearance_profile': 'obsidian', 'accent_color': 'blue'})
        self.assertEqual(invalid['accent'], THEME_PRESETS['obsidian']['accent'])

    def test_conversation_contexts_are_isolated(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(config, 'APP_DIR', Path(tmp)):
            with patch.object(config, 'load_config', return_value={'assistant': {'active_mode': 'school'}}):
                conversation.remember_exchange('School exam is Friday', 'I will plan revision for Friday.')
            with patch.object(config, 'load_config', return_value={'assistant': {'active_mode': 'business'}}):
                conversation.remember_exchange('Business launch is Monday', 'Launch plan noted.')
                business = conversation.recent_messages(20)
            self.assertNotIn(b'Business launch is Monday', (Path(tmp) / 'conversation.sqlite3').read_bytes())
            self.assertTrue(any('Business launch' in row['content'] for row in business))
            self.assertFalse(any('School exam' in row['content'] for row in business))
    def test_chat_context_persists_and_retrieves_relevant_older_turns(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(config, 'APP_DIR', Path(tmp)):
            conversation.remember_exchange('My client project is called Atlas', 'Atlas is saved as the client project.')
            for index in range(12):
                conversation.remember_exchange(f'Routine note {index}', f'Routine answer {index}')
            context = conversation.relevant_messages('What did we decide about Atlas?', 6, 4)
            self.assertTrue(any('Atlas' in row['content'] for row in context))
            self.assertTrue(any('saved as the client project' in row['content'] for row in context))
            conversation.remember_exchange('Do not save this: private thought', 'Understood')
            self.assertFalse(any('private thought' in row['content'] for row in conversation.recent_messages(40)))
    def test_retired_model_retries_only_once(self):
        client=LLMClient()
        with patch.object(client.session,'post',side_effect=[Mock(status_code=404),Mock(status_code=200)]) as post, patch('core.llm.validate_gemini_key'), patch('core.llm.get_secret',return_value='test'), patch('core.llm._AVAILABLE_MODELS',{'gemini-new-flash'}):
            result=client._post('https://generativelanguage.googleapis.com/v1beta/models/old:generateContent')
            self.assertEqual(result.status_code,200)
            self.assertEqual(post.call_count,2)
