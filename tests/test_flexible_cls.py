"""Flexible Provider und kontrollierte Wiederverwendung an den bestehenden Core-Grenzen."""
import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import patch

from tests import test_automation as automation
from tests.test_cls import FakeProvider
from capabilities.registry import CapabilityRegistry, build_default_registry
from core.router import Router
from providers.base import ProviderError, ProviderTurn, ToolCall
from providers.openai_compatible import OpenAICompatibleProvider
from tasks.policy import normalize, effective, check_ai, PolicyDenied
from tools.safety import PermissionDenied


class FlexibleCLSTests(unittest.TestCase):
    setUp = automation.AutomationTests.setUp
    tearDown = automation.AutomationTests.tearDown
    approve = automation.AutomationTests.approve

    def fake(self, name, *, local=True, caps=None, response='Atlas Antwort'):
        provider = FakeProvider(name, caps or ['general_reasoning', 'research', 'coding'])
        provider.is_local = local
        original = provider.chat
        def chat(messages, model=None):
            original(messages, model)
            if isinstance(response, Exception):
                raise response
            return response
        provider.chat = chat
        self.registry.register(provider)
        return provider

    def completed(self, project=None):
        task = self.core.create_task('Atlas kompilieren', project_id=(project or self.project)['id'])
        task.update(status='COMPLETED', verified=True, tools_used=['run_tests'], result='Atlas erfolgreich geprüft')
        self.core.trail.add(task['id'], 'tool', {'tool': 'run_tests', 'ok': True, 'exit_code': 0})
        self.core.tasks.save(task)
        self.core.experience.record(task)
        return task

    def other_project(self):
        path = self.root / 'other'
        path.mkdir(exist_ok=True)
        return self.core.create_project('Atlas Referenz', path=str(path), description='Atlas kompilieren')

    def test_settings_keys_priorities_and_restart(self):
        env = self.root / '.env'
        env.write_text('GEMINI_API_KEY=\nPERPLEXITY_API_KEY=\n')
        registry = build_default_registry(self.db, env)
        self.assertEqual({p.name for p in registry.all()}, {'gemini', 'perplexity', 'groq', 'openrouter', 'cometapi', 'ollama'})
        self.assertFalse(registry.available(registry.get('groq')))
        registry.configure('groq', enabled=True, model='fixture-model', capabilities=['research', 'coding'], api_key='synthetic-fixture')
        registry.configure('openrouter', enabled=True, model='fixture/model', capabilities=['research'], api_key='synthetic-router')
        registry.set_priority('research', ['openrouter', 'groq'])
        reopened = build_default_registry(self.db, env)
        self.assertEqual([p.name for p in reopened.providers_for('research')], ['openrouter', 'groq'])
        self.assertEqual(reopened.get('groq').model_for('coding'), 'fixture-model')
        self.assertNotIn('synthetic', self.db.query_one("SELECT value FROM app_state WHERE key='provider_settings'")['value'])
        # Windows chmod/stat do not expose POSIX owner/group/other permissions.
        # Keep the settings roundtrip checks active on Windows as well.
        if os.name == 'posix':
            self.assertEqual(env.stat().st_mode & 0o777, 0o600)
        reopened.configure('groq', enabled=False)
        self.assertNotIn('groq', [p.name for p in reopened.providers_for('coding')])
        reopened.configure('openrouter', api_key='')
        self.assertFalse(reopened.available(reopened.get('openrouter')))
        with self.assertRaises(ValueError):
            reopened.configure('groq', capabilities=['local_reasoning'])
        with self.assertRaises(ValueError):
            reopened.configure('groq', api_key='bad\nINJECTED=value')

    def test_chat_fallback_empty_invalid_error_and_manual_selection(self):
        first = self.fake('first', response=' ')
        second = self.fake('second', response={'error': 'not an answer'})
        third = self.fake('third')
        self.registry.set_priority('research', ['first', 'second', 'third'])
        reply = self.core.chat('Atlas erklären', 'research')
        self.assertEqual(reply['provider'], 'third')
        self.assertTrue(reply['fallback_used'])
        self.assertEqual(len(self.core.get_conversation()), 2)
        before = len(third.calls)
        reply = self.core.chat('Atlas erklären', 'research', provider='first')
        self.assertTrue(reply['error'])
        self.assertEqual(len(third.calls), before)
        self.assertEqual(len(first.calls), 2)
        self.assertEqual(len(second.calls), 1)
        self.assertEqual(len(self.core.get_conversation()), 2)

    def test_manual_chat_does_not_bypass_privacy_network_or_capability(self):
        provider = self.fake('external', local=False)
        self.core.set_path_privacy(self.work, 'LOCAL_ONLY')
        self.assertTrue(self.core.chat('Atlas erklären', provider='external')['error'])
        self.assertEqual(provider.calls, [])
        self.core.set_path_privacy(self.work, 'SAFE_FOR_EXTERNAL')
        from config.permissions import PERMISSIONS
        with patch.dict(PERMISSIONS, network='never'):
            self.assertTrue(self.core.chat('Atlas erklären', provider='external')['error'])
        self.assertEqual(provider.calls, [])
        self.assertTrue(self.core.chat('Hallo', provider='external', local_only=True)['error'])
        provider.capabilities = ['coding']
        self.assertTrue(self.core.chat('Hallo', provider='external')['error'])

    def test_task_preferences_capability_manual_and_local_constraints(self):
        a = self.fake('first')
        b = self.fake('second')
        external = self.fake('remote', local=False)
        task = self.core.create_task('Atlas erklären', ai_policy={'mode': 'ALLOWED',
            'preferred_providers': ['second', 'first'], 'required_capability': 'research', 'local_only': True})
        self.assertEqual([p.name for p in self.core.agent._candidates(task, 'research')], ['second', 'first'])
        task['ai_policy']['selected_provider'] = 'remote'
        self.assertEqual(self.core.agent._candidates(task, 'research'), [])
        with self.assertRaises(PolicyDenied):
            check_ai(task, external)
        task['ai_policy']['selected_provider'] = 'second'
        self.assertEqual([p.name for p in self.core.agent._candidates(task, 'research')], ['second'])
        policy = normalize({'local_only': True, 'areas': {'code': {'local_only': False}}})
        with self.assertRaises(PolicyDenied):
            check_ai({'ai_policy': policy, 'policy_area': 'code'}, external)
        for bad in ({'local_only': 'yes'}, {'required_capability': 'invalid'}, {'preferred_providers': 'first'}):
            with self.assertRaises(ValueError):
                normalize(bad)

    def test_native_invalid_turn_falls_back_without_false_success(self):
        first = automation.NativeProvider([ProviderTurn()])
        first.name = 'first'
        second = automation.NativeProvider([ProviderTurn(text='Bitte eine konkrete Eingabe geben')])
        second.name = 'second'
        self.registry.register(first)
        self.registry.register(second)
        task = self.core.create_task('Unbekannte Atlas-Aufgabe', ai_policy={'mode': 'ALLOWED'})
        result = self.core.run_task(task['id'])
        self.assertEqual(result['provider'], 'second')
        self.assertNotEqual(result['status'], 'COMPLETED')
        self.assertEqual(len(first.calls), 1)
        self.assertEqual(len(second.calls), 1)

    def test_native_fallback_never_transfers_foreign_signatures(self):
        first = automation.NativeProvider([ProviderTurn(calls=[
            ToolCall('plan', 'set_plan', {'steps': ['Atlas-Datei lesen']}),
            ToolCall('read', 'read_file', {'path': 'note.txt'})],
            native={'provider': 'first', 'signature': 'must-stay-with-first'})])
        first.name = 'first'
        original = first.tool_chat
        def call(messages, tools, model=None):
            if not first.turns:
                raise ProviderError('synthetic failure')
            return original(messages, tools, model)
        first.tool_chat = call
        second = automation.NativeProvider([ProviderTurn(text='Prüfung fortsetzen?')])
        second.name = 'second'
        self.registry.register(first)
        self.registry.register(second)
        task = self.core.create_task('Atlas-Datei prüfen', ai_policy={'mode': 'ALLOWED'})
        result = self.core.run_task(task['id'])
        self.assertEqual(result['provider'], 'second')
        self.assertNotIn('must-stay-with-first', json.dumps(second.calls))
        self.assertIn('read_file', json.dumps(second.calls))
        self.assertEqual(result['tool_calls'], 1)

    def test_memory_candidates_confirmation_privacy_and_restart(self):
        from memory.longterm import LongTermMemory
        memory = LongTermMemory(self.root / 'empty.json', db=self.db)
        self.core.longterm = self.core.context.longterm = memory
        candidate = self.core.propose_memory('Atlas ist mein bevorzugtes Projekt', category='preference')
        self.assertEqual(memory.usable(), [])
        self.assertEqual(self.core.context.build('Atlas').memory_ids, [])
        self.core.update_memory(candidate['id'], 'Atlas ist mein langfristiges Ziel')
        self.core.confirm_memory(candidate['id'])
        self.assertEqual(self.core.context.build('Atlas').memory_ids, [candidate['id']])
        self.assertEqual(self.core.context.build('Atlas', external=True).memory_ids, [])
        self.core.set_memory_privacy(candidate['id'], 'SAFE_FOR_EXTERNAL')
        self.assertEqual(self.core.context.build('Atlas', external=True).memory_ids, [candidate['id']])
        restored = LongTermMemory(self.root / 'empty.json', db=self.db)
        self.assertEqual(restored.get_all()[0]['version'], 2)
        self.assertEqual(restored.get_all()[0]['trust'], 'CONFIRMED')
        self.core.delete_memory(candidate['id'])
        self.assertEqual(self.core.context.build('Atlas').memory_ids, [])

    def test_ordinary_chat_is_not_personal_memory(self):
        self.fake('local')
        self.core.chat('Ich mag Atlas')
        self.assertEqual(self.core.get_personal_memory(), [])
        reply = self.core.chat('Lernvorschlag: Ich mag Atlas')
        self.assertEqual(reply['provider'], 'cls')
        self.assertEqual(self.core.get_personal_memory()[0]['trust'], 'CANDIDATE')
        self.assertEqual(self.core.longterm.usable(), [])

    def test_chat_history_stays_with_its_project(self):
        provider = self.fake('local', response='Antwort aus Projekt A')
        self.core.chat('Interne Details aus Projekt A')
        other = self.other_project()
        self.core.set_active_project(other['id'])
        self.core.chat('Hallo Projekt B')
        self.assertNotIn('Interne Details aus Projekt A', json.dumps(provider.calls[-1]))
        self.assertNotIn('Antwort aus Projekt A', json.dumps(provider.calls[-1]))

    def test_memory_privacy_revocation_blocks_old_answer_history(self):
        provider = self.fake('remote', local=False, response='Frühere persönliche Antwort')
        self.core.set_path_privacy(self.work, 'SAFE_FOR_EXTERNAL')
        fact = self.core.add_memory('Atlas ist mein bevorzugtes Tool')
        self.core.set_memory_privacy(fact['id'], 'SAFE_FOR_EXTERNAL')
        self.core.chat('Atlas erklären', provider='remote')
        self.core.set_memory_privacy(fact['id'], 'LOCAL_ONLY')
        self.core.chat('Atlas erneut erklären', provider='remote')
        sent = json.dumps(provider.calls[-1], ensure_ascii=False)
        self.assertNotIn('Frühere persönliche Antwort', sent)
        self.assertNotIn('bevorzugtes Tool', sent)

    def test_derived_chat_candidate_keeps_memory_provenance(self):
        self.core.set_path_privacy(self.work, 'SAFE_FOR_EXTERNAL')
        self.fake('local', response='Atlas Antwort mit einer persönlichen Präferenz. ' * 8)
        fact = self.core.add_memory('Atlas ist mein bevorzugtes Tool')
        reply = self.core.chat('Atlas erklären', mode='research')
        entry = self.core.confirm_knowledge(reply['candidate_id'])
        self.core.set_knowledge_privacy(entry['id'], 'SAFE_FOR_EXTERNAL')
        self.assertFalse(self.core.context._may_use(entry, True))
        self.core.set_memory_privacy(fact['id'], 'SAFE_FOR_EXTERNAL')
        self.assertTrue(self.core.context._may_use(entry, True))
        self.core.delete_memory(fact['id'])
        self.assertFalse(self.core.context._may_use(entry, False))

    def test_identical_chat_answer_does_not_taint_existing_evidence(self):
        content = 'Atlas verwendet einen explizit bestätigten Debugging-Hinweis. ' * 6
        entry = self.core.add_knowledge(content)['entry']
        before = self.core.knowledge.get_entry(entry['id'], with_details=True)
        result = self.core.knowledge.add_ai_candidate('Atlas?', content, 'gemini', references=[{
            'source_type': 'ai_provider', 'name': 'gemini',
            'reference': f"derived:knowledge:{entry['id']}@{entry['current_version']}"}])
        self.assertFalse(result['created'])
        self.assertEqual(before, self.core.knowledge.get_entry(entry['id'], with_details=True))
        self.assertTrue(self.core.context._may_use(result['entry'], False))

    def test_memory_edit_invalidates_old_chat_answer_history(self):
        provider = self.fake('remote', local=False, response='Frühere persönliche Antwort')
        self.core.set_path_privacy(self.work, 'SAFE_FOR_EXTERNAL')
        fact = self.core.add_memory('Atlas ist mein bevorzugtes Tool')
        self.core.set_memory_privacy(fact['id'], 'SAFE_FOR_EXTERNAL')
        self.core.chat('Atlas erklären', provider='remote')
        self.core.update_memory(fact['id'], 'Atlas ist nicht mehr mein bevorzugtes Tool')
        self.core.chat('Atlas erneut erklären', provider='remote')
        self.assertNotIn('Frühere persönliche Antwort', json.dumps(provider.calls[-1], ensure_ascii=False))

    def test_reference_scope_requires_both_task_and_entry_grants(self):
        other = self.other_project()
        entry = self.core.add_knowledge('Atlas braucht auf Server X Port 91', project_id=other['id'])['entry']
        task = self.core.create_task('Atlas prüfen')
        def refs(t):
            return {r['reference']: r for r in self.core.context.task_sources(t)}
        key = 'knowledge:' + str(entry['id'])
        self.assertNotIn(key, refs(task))
        selected = self.core.create_task('Atlas prüfen', reference_project_ids=[other['id']])
        self.assertNotIn(key, refs(selected))
        self.core.set_knowledge_reference(entry['id'], True)
        self.assertNotIn(key, refs(task))
        reference = refs(selected)[key]
        self.assertTrue(reference['reference_only'])
        self.assertEqual(reference['origin_project_id'], other['id'])
        self.assertEqual(self.core.knowledge.get_entry(entry['id'])['project_id'], other['id'])
        selected['knowledge_used'] = [reference]
        self.core.set_knowledge_trust(entry['id'], 'UNCERTAIN')
        with self.assertRaises(PermissionDenied):
            self.core.agent._provider_gate(selected, self.fake('local'))
        self.core.confirm_knowledge(entry['id'])
        self.core.set_knowledge_reference(entry['id'], False)
        with self.assertRaises(PermissionDenied):
            self.core.agent._provider_gate(selected, self.fake('local'))
        self.core.set_knowledge_reference(entry['id'], True)
        self.core.set_path_privacy(other['path'], 'BLOCKED')
        self.assertNotIn(key, refs(selected))
        self.assertEqual(self.core.find_reference_projects('Atlas', self.project['id']), [])

    def test_experience_reference_and_strategy_exclusion(self):
        other = self.other_project()
        episode = self.completed(other)
        strategy = self.core.propose_strategy('Atlas zuerst B prüfen', [episode['id']], applicability='Atlas', rationale='Beobachtung')
        task = self.core.create_task('Atlas prüfen', reference_project_ids=[other['id']])
        self.assertNotIn('experience:' + episode['id'], [r['reference'] for r in self.core.context.task_sources(task)])
        self.core.set_experience_reference(episode['id'], True)
        records = self.core.context.task_sources(task)
        reference = next(r for r in records if r['reference'] == 'experience:' + episode['id'])
        self.assertTrue(reference['reference_only'])
        self.assertEqual(reference['evidence_kind'], 'historical_experience')
        self.assertNotIn('knowledge:' + str(strategy['id']), [r['reference'] for r in records])
        with self.assertRaises(ValueError):
            self.core.set_knowledge_reference(strategy['id'], True)

    def test_project_storage_modes_and_decline_keep_experience(self):
        for mode, expected in [('NEVER', 'NOT_SELECTED'), ('ASK', 'PENDING'), ('AUTO', 'SAVED')]:
            self.core.set_project_memory_mode(self.project['id'], mode)
            task = self.completed()
            self.core._prepare_project_storage(task)
            stored = self.core.get_task(task['id'])['project_storage']
            self.assertEqual(stored['status'], expected)
            if mode == 'ASK':
                self.core.resolve_project_storage(task['id'], 'experience_only')
                self.assertEqual(self.core.get_task(task['id'])['project_storage']['status'], 'EXPERIENCE_ONLY')
            if mode == 'AUTO':
                entry = self.core.get_knowledge_entry(stored['entry_id'])
                self.assertEqual(entry['trust'], 'CANDIDATE')
                self.assertEqual(entry['project_id'], self.project['id'])
                self.assertEqual(self.core.get_knowledge_privacy(entry['id']), 'LOCAL_ONLY')
            self.assertIsNotNone(self.core.experience.get(task['id']))
        self.core.set_project_memory_mode(self.project['id'], 'ASK')
        task = self.completed()
        self.core._prepare_project_storage(task)
        self.core.set_path_privacy(self.work, 'BLOCKED')
        with self.assertRaises(ValueError):
            self.core.resolve_project_storage(task['id'], 'save')

    def test_actual_workflow_completion_creates_storage_prompt(self):
        from config.permissions import COMMANDS
        self.core.set_project_memory_mode(self.project['id'], 'ASK')
        self.core.save_workflow('Atlas-Test', 'Atlas-Test', [{'tool': 'run_tests', 'args': {'command': 'fixture'}}])
        with patch.dict(COMMANDS, fixture={'argv': ['{python}', '-c', 'print("passed")'], 'kind': 'test'}):
            task = self.core.create_task('Atlas-Test')
            self.core.run_task(task['id'])
            result = self.approve(task['id'])
        self.assertEqual(result['status'], 'COMPLETED')
        self.assertEqual(result['project_storage']['status'], 'PENDING')
        stored = self.core.resolve_project_storage(task['id'], 'save')
        entry = self.core.get_knowledge_entry(stored['project_storage']['entry_id'])
        self.assertTrue(entry['sources'][0]['reference'].startswith('derived:experience:'))
        self.assertFalse(self.core.context.find_knowledge('Atlas-Test', self.project))

    def test_project_deletion_does_not_globalize_regular_knowledge(self):
        entry = self.core.add_knowledge('Atlas Port 99', project_id=self.project['id'])['entry']
        self.core.delete_project(self.project['id'])
        kept = self.core.get_knowledge_entry(entry['id'])
        self.assertEqual(kept['origin_project_id'], self.project['id'])
        self.assertEqual(kept['trust'], 'OUTDATED')
        with self.assertRaises(ValueError):
            self.core.confirm_knowledge(entry['id'])
        self.assertEqual(self.core.context.find_knowledge('Atlas', None), [])


class CompatibleProtocolTests(unittest.TestCase):
    def provider(self, name='groq'):
        provider = OpenAICompatibleProvider(name, 'synthetic-fixture')
        provider.configured_models = {'default': 'fixture-model'}
        return provider

    def test_all_three_adapters_parse_tool_calls_and_preserve_roundtrip(self):
        for name in ('groq', 'openrouter', 'cometapi'):
            provider = self.provider(name)
            message = {'role': 'assistant', 'content': None, 'tool_calls': [
                {'id': 'call-1', 'type': 'function', 'function': {'name': 'read_file', 'arguments': '{"path":"note.txt"}'}}]}
            sent = []
            def post(payload):
                sent.append(payload)
                return {'choices': [{'message': message}]}
            provider._post = post
            turn = provider.tool_chat([{'role': 'user', 'content': 'Atlas'}], [])
            self.assertEqual(turn.calls[0].arguments, {'path': 'note.txt'})
            provider.tool_chat([{'role': 'assistant', 'native': turn.native},
                {'role': 'tool', 'call_id': 'call-1', 'result': {'ok': True}}], [])
            self.assertEqual(sent[-1]['messages'][0], message)
            self.assertEqual(sent[-1]['messages'][1]['tool_call_id'], 'call-1')

    def test_invalid_completions_fail_closed(self):
        provider = self.provider()
        bad = [{}, [], {'choices': [None]}, {'choices': [{'message': 7}]},
               {'error': {'message': 'failure'}}, {'choices': []},
               {'choices': [{'message': {'content': ' '}}]},
               {'choices': [{'finish_reason': 'length', 'message': {'content': 'partial'}}]},
               {'choices': [{'message': {'content': ['wrong-type']}}]},
               {'choices': [{'message': {'content': None, 'tool_calls': [
                   {'id': 'a', 'type': 'function', 'function': {'name': 'tool', 'arguments': '[]'}}]}}]}]
        for data in bad:
            provider._post = lambda payload: data
            with self.subTest(data=data), self.assertRaises(ProviderError):
                provider.tool_chat([{'role': 'user', 'content': 'fixture'}], [])

    def test_real_http_request_and_error_redaction(self):
        requests = []
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                requests.append((self.path, self.headers.get('Authorization'), json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
                status = 200 if len(requests) == 1 else 401
                self.send_response(status)
                self.end_headers()
                self.wfile.write(json.dumps({'choices': [{'message': {'content': 'fixture response'}}]} if status == 200
                                           else {'error': 'sensitive-fixture-body'}).encode())
            def log_message(self, *args):
                pass
        server = HTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            provider = self.provider()
            provider.url = f'http://127.0.0.1:{server.server_port}/chat/completions'
            self.assertEqual(provider.chat([{'role': 'user', 'content': 'fixture question'}]), 'fixture response')
            self.assertEqual(requests[0][2]['model'], 'fixture-model')
            self.assertEqual(requests[0][1], 'Bearer synthetic-fixture')
            with self.assertRaises(ProviderError) as error:
                provider.chat([{'role': 'user', 'content': 'fixture question'}])
            self.assertNotIn('sensitive-fixture-body', str(error.exception))
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
