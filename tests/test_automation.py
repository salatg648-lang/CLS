"""Phasen 4–6: echte Datei-/DB-/Prozessgrenzen, native Protokolle und Wiederaufnahme."""
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from capabilities.registry import CapabilityRegistry
from core.api import CLSCore
from infrastructure.database import Database
from memory.conversation import ConversationHistory
from memory.longterm import LongTermMemory
from providers.base import BaseProvider, ProviderTurn, ToolCall
from tools.registry import ToolContext
from tools.safety import ToolBlocked, ConfirmationRequired, Safety


class NativeProvider(BaseProvider):
    name, display_name = 'native', 'Test Native'
    capabilities = ['general_reasoning', 'coding', 'research']
    is_local = True

    def __init__(self, turns=()):
        self.turns, self.calls = list(turns), []

    def is_available(self):
        return True

    def supports_tool_calls(self):
        return True

    def chat(self, messages, model=None):
        return 'Rechercheantwort ' * 30

    def tool_chat(self, messages, tools, model=None):
        self.calls.append(json.loads(json.dumps(messages)))
        return self.turns.pop(0)


def turn(name, args):
    return ProviderTurn(calls=[ToolCall(name, name, args)])


class AutomationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.work = self.root / 'work'
        self.work.mkdir()
        (self.work / 'note.txt').write_text('Original', encoding='utf-8')
        self.db = Database(self.root / 'db.sqlite')
        self.registry = CapabilityRegistry()
        self.core = CLSCore(registry=self.registry, db=self.db,
            conversation=ConversationHistory(self.root / 'chat.json'),
            longterm=LongTermMemory(self.root / 'facts.json'), documents_dir=self.root / 'docs')
        self.project = self.core.create_project('Test', path=str(self.work))
        self.core.set_active_project(self.project['id'])
        self.ctx = ToolContext(str(self.work))

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def workflow(self, steps=None):
        return self.core.save_workflow('Notiz lesen', 'Notiz prüfen', steps or [
            {'tool': 'read_file', 'args': {'path': 'note.txt'}}])

    def approve(self, task_id, approved=True):
        pending = self.core.get_task(task_id)['pending']
        return self.core.run_task(task_id, approve=approved, confirmation_id=pending['confirmation_id'])

    def execute(self, name, args, approved=False, ctx=None):
        return self.core.tools.execute(name, args, ctx or self.ctx, approved)

    def test_path_traversal_sibling_links_and_sensitive_files(self):
        outside = self.root / 'work-other'
        outside.mkdir()
        (outside / 'secret').write_text('secret')
        try:
            (self.work / 'link').symlink_to(outside, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f'Symlinks werden nicht unterstützt: {exc}')
        (self.work / '.env.local').write_text('synthetic test')
        for path in ('../work-other/secret', str(outside / 'secret'), 'link/secret', '.env.local', '.git/config'):
            with self.subTest(path=path), self.assertRaises(ToolBlocked):
                self.execute('read_file', {'path': path})
        os.link(outside / 'secret', self.work / 'hardlink')
        with self.assertRaises(ToolBlocked):
            self.execute('write_file', {'path': 'hardlink', 'content': 'x'}, True)
        self.assertEqual((outside / 'secret').read_text(), 'secret')

    def test_mutations_need_exact_confirmation_and_edit_match(self):
        with self.assertRaises(ConfirmationRequired):
            self.execute('write_file', {'path': 'note.txt', 'content': 'Neu'})
        self.assertEqual((self.work / 'note.txt').read_text(), 'Original')
        self.assertTrue(self.execute('edit_file', {'path': 'note.txt', 'old': 'Original', 'new': 'Neu'}, True)['verified'])
        with self.assertRaises(ToolBlocked):
            self.execute('edit_file', {'path': 'note.txt', 'old': 'falsch', 'new': 'x'}, True)
        with self.assertRaises(ConfirmationRequired):
            self.execute('write_file', {'path': 'next.txt', 'content': 'x'})

    def test_schema_and_command_injection(self):
        for name, args in [('unknown', {}), ('read_file', {'path': 1}),
                           ('read_file', {'path': 'note.txt', 'approved': True}),
                           ('run_command', {'command': 'python_tests; touch PWNED'})]:
            with self.subTest(name=name), self.assertRaises(ToolBlocked):
                self.execute(name, args, True)
        self.assertFalse((self.work / 'PWNED').exists())

    def test_privacy_levels_search_and_external_egress(self):
        external = ToolContext(str(self.work), external=True)
        with self.assertRaises(ToolBlocked):
            self.execute('read_file', {'path': 'note.txt'}, ctx=external)
        external.consent = True
        self.assertTrue(self.execute('read_file', {'path': 'note.txt'}, ctx=external)['ok'])
        self.core.set_path_privacy(self.work / 'note.txt', 'LOCAL_ONLY')
        with self.assertRaises(ToolBlocked):
            self.execute('read_file', {'path': 'note.txt'}, ctx=external)
        self.assertEqual(self.execute('search_files', {'pattern': '*'}, ctx=external)['matches'], [])
        self.core.set_path_privacy(self.work / 'note.txt', 'BLOCKED')
        with self.assertRaises(ToolBlocked):
            self.execute('read_file', {'path': 'note.txt'})
        self.core.set_path_privacy(self.work / 'note.txt', 'SAFE_FOR_EXTERNAL')
        external.consent = False
        self.assertTrue(self.execute('read_file', {'path': 'note.txt'}, ctx=external)['ok'])

    def test_terminal_exit_status_timeout_and_environment(self):
        from config.permissions import COMMANDS
        commands = {
            'ok': {'argv': ['{python}', '-c', 'import os; print(os.environ.get("CLS_TEST_SECRET", "absent"))'], 'kind': 'test'},
            'bad': {'argv': ['{python}', '-c', 'raise SystemExit(7)'], 'kind': 'test'},
            'hang': {'argv': ['{python}', '-c', 'import time; time.sleep(10)'], 'kind': 'test'},
        }
        with patch.dict(COMMANDS, commands), patch.dict(os.environ, {'CLS_TEST_SECRET': 'private'}):
            with self.assertRaises(ConfirmationRequired):
                self.execute('run_tests', {'command': 'ok'})
            self.assertIn('absent', self.execute('run_tests', {'command': 'ok'}, True)['output'])
            self.assertEqual(self.execute('run_tests', {'command': 'bad'}, True)['exit_code'], 7)
            with patch('tools.terminal_tools.STEP_TIMEOUT', 0.05):
                self.assertTrue(self.execute('run_tests', {'command': 'hang'}, True)['timed_out'])

    def test_workflow_without_ai_and_experience_from_action_trail(self):
        self.workflow()
        task = self.core.create_task('Notiz prüfen')
        result = self.core.run_task(task['id'])
        self.assertEqual(result['status'], 'COMPLETED')
        self.assertEqual(result['api_calls'], 0)
        self.assertEqual(result['progress']['percent'], 100)
        experience = self.core.get_experiences(project_id=self.project['id'])[0]
        self.assertEqual(experience['summary']['steps'][0]['tool'], 'read_file')
        self.assertEqual(self.core.preview_decision('Notiz prüfen', self.project['id'])['reason'], 'Verifizierte Erfahrung')
        with self.assertRaises(ValueError):
            self.core.run_task(task['id'])

    def test_native_batch_confirmation_denial_and_no_text_parsing(self):
        provider = NativeProvider([ProviderTurn(calls=[
            ToolCall('plan', 'set_plan', {'steps': ['Ändern', 'Prüfen']}),
            ToolCall('write', 'write_file', {'path': 'note.txt', 'content': 'Neu'}),
        ])])
        self.registry.register(provider)
        task = self.core.create_task('Ändern')
        pending = self.core.run_task(task['id'])
        self.assertEqual(pending['status'], 'NEEDS_CONFIRMATION')
        self.assertEqual((self.work / 'note.txt').read_text(), 'Original')
        self.assertEqual(self.core.run_task(task['id'])['status'], 'NEEDS_CONFIRMATION')
        denied = self.approve(task['id'], False)
        self.assertEqual(denied['status'], 'FAILED')
        self.assertEqual((self.work / 'note.txt').read_text(), 'Original')
        provider.turns = [ProviderTurn(text='write_file({"path":"note.txt","content":"evil"})')]
        task = self.core.create_task('Weitere Aufgabe')
        self.assertEqual(self.core.run_task(task['id'])['status'], 'WAITING_FOR_USER')
        self.assertEqual((self.work / 'note.txt').read_text(), 'Original')

    def test_write_build_test_verification_and_separate_approvals(self):
        from config.permissions import COMMANDS
        self.core.save_workflow('Ändern', 'Ändern', [
            {'tool': 'write_file', 'args': {'path': 'note.txt', 'content': 'Neu'}},
            {'tool': 'run_build', 'args': {'command': 'build'}},
            {'tool': 'run_tests', 'args': {'command': 'test'}},
        ])
        commands = {n: {'argv': ['{python}', '-c', 'print("passed")'], 'kind': k}
                    for n, k in [('build', 'build'), ('test', 'test')]}
        with patch.dict(COMMANDS, commands):
            task = self.core.create_task('Ändern')
            result = self.core.run_task(task['id'])
            for expected in ('write_file', 'run_build', 'run_tests'):
                self.assertEqual(result['pending']['name'], expected)
                result = self.approve(task['id'])
            self.assertEqual(result['status'], 'COMPLETED')
            self.assertTrue(result['verified'])
            self.assertEqual((self.work / 'note.txt').read_text(), 'Neu')

    def test_stale_confirmation_cannot_approve_another_action(self):
        self.workflow([{'tool': 'write_file', 'args': {'path': 'note.txt', 'content': 'One'}},
                       {'tool': 'write_file', 'args': {'path': 'next.txt', 'content': 'Two'}},
                       {'tool': 'read_file', 'args': {'path': 'note.txt'}}])
        task = self.core.create_task('Notiz prüfen')
        first = self.core.run_task(task['id'])['pending']['confirmation_id']
        self.core.run_task(task['id'], approve=True, confirmation_id=first)
        with self.assertRaises(ValueError):
            self.core.run_task(task['id'], approve=True, confirmation_id=first)
        self.assertFalse((self.work / 'next.txt').exists())

    def test_workflow_write_read_verifies_file_effect(self):
        self.workflow([{'tool': 'write_file', 'args': {'path': 'note.txt', 'content': 'Neu'}},
                       {'tool': 'read_file', 'args': {'path': 'note.txt'}}])
        task = self.core.create_task('Notiz prüfen')
        self.core.run_task(task['id'])
        result = self.approve(task['id'])
        self.assertEqual(result['status'], 'COMPLETED')
        self.assertTrue(result['verified'])
        self.assertEqual((self.work / 'note.txt').read_text(), 'Neu')
        self.assertEqual(result['tool_results'][1]['result']['content'], 'Neu')

    def test_failed_tests_never_complete_workflow(self):
        from config.permissions import COMMANDS
        self.workflow([{'tool': 'run_tests', 'args': {'command': 'bad'}}])
        with patch.dict(COMMANDS, {'bad': {'argv': ['{python}', '-c', 'raise SystemExit(3)'], 'kind': 'test'}}):
            task = self.core.create_task('Notiz prüfen')
            self.core.run_task(task['id'])
            result = self.approve(task['id'])
            self.assertEqual(result['status'], 'BLOCKED')
            self.assertEqual(result['cursor'], 0)
            self.assertFalse(result['verified'])

    def test_tool_and_api_budgets_survive_resume(self):
        self.workflow()
        task = self.core.create_task('Notiz prüfen')
        with patch('config.agent.MAX_TOOL_CALLS', 0):
            result = self.core.run_task(task['id'])
        self.assertEqual(result['status'], 'BLOCKED')
        provider = NativeProvider([turn('set_plan', {'steps': ['Prüfen']})])
        self.registry.register(provider)
        task = self.core.create_task('AI Aufgabe')
        with patch('config.agent.MAX_API_CALLS_PER_TASK', 0):
            result = self.core.run_task(task['id'])
        self.assertEqual(result['status'], 'BLOCKED')
        self.assertEqual(provider.calls, [])

    def test_external_provider_needs_task_consent(self):
        provider = NativeProvider([turn('request_help', {'reason': 'Welche Datei?', 'status': 'NEEDS_INFORMATION'})])
        provider.is_local = False
        self.registry.register(provider)
        task = self.core.create_task('AI Aufgabe')
        self.assertEqual(self.core.run_task(task['id'])['status'], 'NEEDS_PERMISSION')
        self.assertEqual(provider.calls, [])
        task = self.core.create_task('AI Aufgabe', allow_external=True)
        result = self.core.run_task(task['id'])
        self.assertEqual(result['status'], 'NEEDS_INFORMATION')
        self.assertGreater(result['cost_reserved'], 0)

    def test_pause_and_restart_preserve_pending_confirmation(self):
        self.workflow([{'tool': 'write_file', 'args': {'path': 'note.txt', 'content': 'Neu'}},
                       {'tool': 'read_file', 'args': {'path': 'note.txt'}}])
        task = self.core.create_task('Notiz prüfen')
        self.core.run_task(task['id'])
        self.core.pause_task(task['id'])
        from tasks.task_manager import TaskManager
        manager = TaskManager(self.db, self.core.trail)
        self.assertEqual(manager.get(task['id'])['status'], 'PAUSED')
        self.assertIsNotNone(manager.get(task['id'])['pending'])
        self.assertEqual(self.core.run_task(task['id'])['status'], 'PAUSED')

    def test_interrupted_action_is_not_replayed(self):
        self.workflow()
        task = self.core.create_task('Notiz prüfen')
        task.update(status='IN_PROGRESS', in_flight=True)
        self.core.tasks.save(task)
        from tasks.task_manager import TaskManager
        TaskManager(self.db, self.core.trail)
        result = self.core.run_task(task['id'])
        self.assertEqual(result['status'], 'BLOCKED')
        self.assertEqual(result['tool_calls'], 0)

    def test_scheduler_interval_dedup_and_restart(self):
        workflow = self.workflow()
        schedule = self.core.scheduler.create(workflow['id'], self.project['id'], interval=60, clock=100)
        self.assertEqual(self.core.scheduler.dispatch(clock=159), [])
        task = self.core.scheduler.dispatch(clock=160)[0]
        self.assertEqual(self.core.scheduler.dispatch(clock=1000), [])
        self.core.run_task(task['id'])
        self.assertEqual(len(self.core.scheduler.dispatch(clock=1000)), 1)
        self.core.enable_schedule(schedule['id'], False)
        self.assertEqual(self.core.scheduler.dispatch(clock=2000), [])
        self.assertEqual(len(self.core.get_schedules()), 1)

    def test_event_scheduler_scope_and_loop_prevention(self):
        workflow = self.workflow()
        self.core.create_schedule(workflow['id'], self.project['id'], event='task.completed')
        task = self.core.create_task('Notiz prüfen')
        self.core.run_task(task['id'])
        self.assertEqual(len(self.core.get_tasks()), 2)
        self.core.tick_scheduler()
        self.assertEqual(len(self.core.get_tasks()), 2)
        self.assertTrue(all(t['status'] == 'COMPLETED' for t in self.core.get_tasks()))

    def test_workflow_snapshot_does_not_change_pending_task(self):
        workflow = self.workflow()
        task = self.core.create_task('Notiz prüfen')
        self.core.save_workflow('Notiz lesen', 'Anderes Ziel',
            [{'tool': 'read_file', 'args': {'path': 'missing'}}], workflow['id'])
        self.assertEqual(self.core.run_task(task['id'])['status'], 'COMPLETED')
        self.assertEqual(self.core.preview_decision('Notiz prüfen', self.project['id'])['kind'], 'ai')

    def test_multi_ai_consult_and_controlled_learning(self):
        provider = NativeProvider([
            turn('set_plan', {'steps': ['Recherche', 'Prüfen']}),
            turn('ask_ai', {'capability': 'research', 'question': 'Was ist Architektur?'}),
            turn('read_file', {'path': 'note.txt'}),
            turn('finish_task', {'summary': 'Geprüft'}),
        ])
        advisor = NativeProvider()
        advisor.name = 'advisor'
        advisor.capabilities = ['research']
        provider.capabilities = ['general_reasoning']
        self.registry.register(provider)
        self.registry.register(advisor)
        task = self.core.create_task('Recherche')
        result = self.core.run_task(task['id'])
        self.assertEqual(result['status'], 'COMPLETED')
        self.assertEqual(set(result['ai_providers_used']), {'native', 'advisor'})
        self.assertEqual(self.core.list_knowledge()[0]['trust'], 'CANDIDATE')

    def test_document_privacy_rechecked_for_external_context(self):
        doc = self.work / 'private.txt'
        doc.write_text('Quokka streng vertraulich')
        self.core.ingest_document(doc, self.project['id'])
        self.assertIn('vertraulich', self.core.context.build('Quokka').messages[0]['content'])
        self.assertNotIn('vertraulich', self.core.context.build('Quokka', external=True).messages[0]['content'])
        self.core.set_path_privacy(doc, 'SAFE_FOR_EXTERNAL')
        self.assertIn('vertraulich', self.core.context.build('Quokka', external=True).messages[0]['content'])
        self.core.set_path_privacy(doc, 'LOCAL_ONLY')
        self.assertNotIn('vertraulich', self.core.context.build('Quokka', external=True).messages[0]['content'])
        self.core.set_path_privacy(doc, 'BLOCKED')
        self.assertNotIn('vertraulich', self.core.context.build('Quokka').messages[0]['content'])

    def test_blocked_document_is_omitted_from_local_knowledge_reply(self):
        doc = self.work / 'private.txt'
        doc.write_text('Quokka vertraulich')
        self.core.ingest_document(doc)
        self.core.set_path_privacy(doc, 'BLOCKED')
        reply = self.core.chat('Was weißt du über Quokka?')
        self.assertNotIn('vertraulich', reply['text'])

    def test_local_candidate_stays_local_after_confirmation(self):
        provider = NativeProvider()
        provider.capabilities = ['research', 'general_reasoning']
        self.registry.register(provider)
        reply = self.core.chat('Architektur Recherche', mode='research')
        self.core.confirm_knowledge(reply['candidate_id'])
        self.assertEqual(self.core.get_knowledge_privacy(reply['candidate_id']), 'LOCAL_ONLY')
        self.assertEqual(self.core.context.build('Rechercheantwort', external=True).knowledge_ids, [])
        self.core.set_knowledge_privacy(reply['candidate_id'], 'SAFE_FOR_EXTERNAL')
        self.core.set_path_privacy(self.work, 'SAFE_FOR_EXTERNAL')
        self.assertIn(reply['candidate_id'], self.core.context.build('Rechercheantwort', external=True).knowledge_ids)

    def test_document_privacy_revocation_removes_history(self):
        doc = self.work / 'private.txt'
        doc.write_text('Quokka vertraulich')
        entry_id = self.core.ingest_document(doc)['document']['id']
        entry_id = self.db.query_one('SELECT id FROM knowledge_entries WHERE document_id=?', (entry_id,))['id']
        self.core.conversation.add('user', 'Quokka?', meta={'project_id': self.project['id']})
        self.core.conversation.add('assistant', 'Vertraulicher Inhalt',
                                   meta={'knowledge': [entry_id], 'project_id': self.project['id']})
        self.core.set_path_privacy(doc, 'SAFE_FOR_EXTERNAL')
        self.assertEqual(len(self.core.context.build('Weiter', external=True).messages), 4)
        self.core.set_path_privacy(doc, 'LOCAL_ONLY')
        self.assertEqual(len(self.core.context.build('Weiter', external=True).messages), 2)

    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'POSIX FIFO')
    def test_special_files_do_not_block_reads(self):
        os.mkfifo(self.work / 'pipe')
        with self.assertRaises(ToolBlocked):
            self.execute('read_file', {'path': 'pipe'})

    def test_scheduled_write_waits_for_user(self):
        workflow = self.workflow([{'tool': 'write_file', 'args': {'path': 'note.txt', 'content': 'Schedule'}},
                                  {'tool': 'read_file', 'args': {'path': 'note.txt'}}])
        self.core.create_schedule(workflow['id'], self.project['id'], event='project.activated')
        self.core.set_active_project(self.project['id'])
        self.core.tick_scheduler()
        task = self.core.get_tasks()[0]
        self.assertEqual(task['status'], 'NEEDS_CONFIRMATION')
        self.assertEqual((self.work / 'note.txt').read_text(), 'Original')
        self.core.set_active_project(self.project['id'])
        self.assertEqual(len(self.core.get_tasks()), 1)

    def test_confirmed_edit_error_returns_to_agent_without_pending_approval(self):
        provider = NativeProvider([
            turn('set_plan', {'steps': ['Ändern', 'Prüfen']}),
            turn('edit_file', {'path': 'note.txt', 'old': 'fehlt', 'new': 'Neu'}),
            turn('request_help', {'reason': 'Welche Textstelle?', 'status': 'NEEDS_INFORMATION'}),
        ])
        self.registry.register(provider)
        task = self.core.create_task('Ändern')
        self.core.run_task(task['id'])
        result = self.approve(task['id'])
        self.assertEqual(result['status'], 'NEEDS_INFORMATION')
        self.assertIsNone(result['pending'])
        errors = [m for m in provider.calls[-1] if m['role'] == 'tool' and not m['result'].get('ok')]
        self.assertTrue(errors)
        self.assertEqual((self.work / 'note.txt').read_text(), 'Original')

    def test_policy_change_invalidates_pending_permission(self):
        self.workflow([{'tool': 'write_file', 'args': {'path': 'note.txt', 'content': 'Neu'}},
                       {'tool': 'read_file', 'args': {'path': 'note.txt'}}])
        task = self.core.create_task('Notiz prüfen')
        self.core.run_task(task['id'])
        self.core.set_path_privacy(self.work / 'note.txt', 'BLOCKED')
        result = self.approve(task['id'])
        self.assertEqual(result['status'], 'NEEDS_PERMISSION')
        self.assertIsNone(result['pending'])
        self.assertEqual((self.work / 'note.txt').read_text(), 'Original')

    def test_missing_scheduled_project_directory_disables_schedule(self):
        workflow = self.workflow()
        schedule = self.core.scheduler.create(workflow['id'], self.project['id'], interval=60, clock=100)
        (self.work / 'note.txt').unlink()
        self.work.rmdir()
        self.assertEqual(self.core.scheduler.dispatch(clock=160), [])
        self.assertFalse(self.core.get_schedules()[0]['enabled'])

    @unittest.skipUnless(os.name == 'posix', 'POSIX-Dateirechte')
    def test_atomic_edit_preserves_mode(self):
        import stat
        path = self.work / 'note.txt'
        path.chmod(0o750)
        self.execute('edit_file', {'path': 'note.txt', 'old': 'Original', 'new': 'Neu'}, True)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o750)

    def test_duplicate_workflow_name_is_user_error(self):
        self.workflow()
        with self.assertRaises(ValueError):
            self.workflow()

    def test_unrelated_project_privacy_does_not_block_command_result(self):
        from config.permissions import COMMANDS
        self.core.set_path_privacy(self.root / 'other-project', 'LOCAL_ONLY')
        provider = NativeProvider([
            turn('set_plan', {'steps': ['Tests', 'Abschluss']}),
            turn('run_tests', {'command': 'ok'}),
            turn('finish_task', {'summary': 'Tests erfolgreich'}),
        ])
        provider.is_local = False
        self.registry.register(provider)
        with patch.dict(COMMANDS, {'ok': {'argv': ['{python}', '-c', 'print("ok")'], 'kind': 'test'}}):
            task = self.core.create_task('Testprojekt prüfen', allow_external=True)
            self.core.run_task(task['id'])
            result = self.approve(task['id'])
        self.assertEqual(result['status'], 'COMPLETED')
        self.assertEqual(result['read_paths'], [str(self.work)])

    def test_scheduler_failure_isolated_and_busy_task_deferred(self):
        workflow = self.workflow()
        first = self.core._scheduled_task(workflow['id'], self.project['id'], 'first')
        second = self.core._scheduled_task(workflow['id'], self.project['id'], 'second')
        original = self.core.run_task
        def run(task_id, **kwargs):
            if task_id == first['id']:
                raise ValueError('Ungültige Aufgabe')
            return original(task_id, **kwargs)
        with patch.object(self.core, 'run_task', side_effect=run):
            self.core.tick_scheduler()
        self.assertEqual(self.core.get_task(first['id'])['status'], 'BLOCKED')
        self.assertEqual(self.core.get_task(second['id'])['status'], 'COMPLETED')
        third = self.core._scheduled_task(workflow['id'], self.project['id'], 'third')
        with self.core.agent._lock:
            self.core.tick_scheduler()
        self.assertEqual(self.core.get_task(third['id'])['status'], 'CREATED')
        self.core.tick_scheduler()
        self.assertEqual(self.core.get_task(third['id'])['status'], 'COMPLETED')

    def test_failed_action_retry_limit_survives_successful_intermediate_reads(self):
        turns = [turn('set_plan', {'steps': ['Lesen', 'Ändern', 'Prüfen']})]
        for _ in range(3):
            turns.extend([turn('read_file', {'path': 'note.txt'}),
                          turn('edit_file', {'path': 'note.txt', 'old': 'fehlt', 'new': 'Neu'})])
        provider = NativeProvider(turns)
        self.registry.register(provider)
        task = self.core.create_task('Ändern')
        self.core.run_task(task['id'])
        for _ in range(3):
            result = self.approve(task['id'])
        self.assertEqual(result['status'], 'BLOCKED')
        self.assertEqual(max(result['failures'].values()), 3)
        self.assertEqual((self.work / 'note.txt').read_text(), 'Original')

    def test_same_named_documents_in_other_projects_do_not_affect_privacy(self):
        public = self.work / 'notes.txt'
        public.write_text('Quokka öffentliche Notizen')
        self.core.set_path_privacy(public, 'SAFE_FOR_EXTERNAL')
        self.core.ingest_document(public, self.project['id'])
        other_dir = self.root / 'other'
        other_dir.mkdir()
        private = other_dir / 'notes.txt'
        private.write_text('Quokka geheime Notizen')
        other = self.core.create_project('Other', path=str(other_dir))
        self.core.set_path_privacy(private, 'LOCAL_ONLY')
        self.core.ingest_document(private, other['id'])
        prompt = self.core.context.build('Quokka', external=True).messages[0]['content']
        self.assertIn('öffentliche Notizen', prompt)
        self.assertNotIn('geheime Notizen', prompt)

    def test_sqlite_personal_and_conversation_migration_once(self):
        facts_path, chat_path = self.root / 'legacy_facts.json', self.root / 'legacy_chat.json'
        facts_path.write_text('[{"id": 3, "content": "Robin", "tags": [], "category": "general"}]')
        chat_path.write_text('[{"role": "user", "content": "Hi"}]')
        facts = LongTermMemory(facts_path, db=self.db)
        facts.update_fact(3, 'Robin entwickelt CLS')
        chat = ConversationHistory(chat_path, db=self.db)
        chat.add('assistant', 'Hallo')
        self.assertEqual(LongTermMemory(facts_path, db=self.db).get_all()[0]['content'], 'Robin entwickelt CLS')
        self.assertEqual(len(ConversationHistory(chat_path, db=self.db).get_all()), 2)
        self.assertEqual(json.loads(facts_path.read_text())[0]['content'], 'Robin')


class ProviderProtocolTests(unittest.TestCase):
    def test_gemini_native_signature_roundtrip(self):
        from google.genai import types
        from providers.gemini import GeminiProvider
        from types import SimpleNamespace
        content = types.Content(role='model', parts=[types.Part(
            function_call=types.FunctionCall(name='read_file', args={'path': 'note.txt'}),
            thought_signature=b'synthetic-signature')])
        calls = []
        def generate(**kwargs):
            calls.append(kwargs)
            return SimpleNamespace(candidates=[SimpleNamespace(content=content)])
        provider = GeminiProvider(api_key='')
        provider._types = types
        provider.client = SimpleNamespace(models=SimpleNamespace(generate_content=generate))
        from tools.registry import DEFINITIONS
        from core.planner import CONTROL_SCHEMAS
        first = provider.tool_chat([{'role': 'user', 'content': 'Read'}], DEFINITIONS + CONTROL_SCHEMAS)
        declarations = calls[0]['config'].tools[0].function_declarations
        self.assertEqual(len(declarations), len(DEFINITIONS) + len(CONTROL_SCHEMAS))
        self.assertFalse(declarations[0].parameters_json_schema['additionalProperties'])
        self.assertEqual(first.calls[0].name, 'read_file')
        provider.tool_chat([{'role': 'user', 'content': 'Read'},
            {'role': 'assistant', 'content': '', 'native': first.native},
            {'role': 'tool', 'name': 'read_file', 'result': {'ok': True, 'content': 'hello'}}], [])
        self.assertEqual(calls[1]['contents'][1].parts[0].thought_signature, b'synthetic-signature')
        self.assertEqual(calls[1]['contents'][2].parts[0].function_response.name, 'read_file')

    def test_ollama_http_native_roundtrip_and_cloud_refusal(self):
        from http.server import BaseHTTPRequestHandler, HTTPServer
        from providers.ollama import OllamaProvider
        from providers.base import ProviderError
        payloads = []
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                payloads.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                data = {'message': {'role': 'assistant', 'content': '', 'tool_calls': [
                    {'function': {'name': 'read_file', 'arguments': {'path': 'note.txt'}}}]}}
                if len(payloads) > 1:
                    data = {'message': {'role': 'assistant', 'content': 'Gelesen.',
                                        'thinking': 'Separater interner Text.'}}
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps(data).encode())
            def log_message(self, *args):
                pass
        server = HTTPServer(('127.0.0.1', 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            provider = OllamaProvider(f'127.0.0.1:{server.server_port}')
            result = provider.tool_chat([{'role': 'user', 'content': 'Lesen'}], [])
            self.assertEqual(result.calls[0].arguments, {'path': 'note.txt'})
            self.assertFalse(payloads[0]['stream'])
            reply = provider.tool_chat([
                {'role': 'assistant', 'content': '', 'native': result.native},
                {'role': 'tool', 'name': 'read_file', 'result': {'ok': True, 'content': 'hello'}}], [])
            self.assertEqual(reply.text, 'Gelesen.')
            self.assertEqual(payloads[1]['messages'][0], result.native['message'])
            self.assertEqual(payloads[1]['messages'][1]['tool_name'], 'read_file')
            self.assertEqual(json.loads(payloads[1]['messages'][1]['content'])['content'], 'hello')
            self.assertEqual(provider.chat([{'role': 'user', 'content': 'Hallo'}]), 'Gelesen.')
            for payload in payloads:
                self.assertIs(payload['think'], False)
            for model in ('remote:cloud', 'remote/model'):
                with self.subTest(model=model), self.assertRaises(ProviderError):
                    provider.chat([{'role': 'user', 'content': 'x'}], model=model)
            self.assertEqual(len(payloads), 3)
            for host in ('https://example.com', 'http://example.com', 'http://192.168.1.1:11434'):
                with self.subTest(host=host), self.assertRaises(ValueError):
                    OllamaProvider(host)
        finally:
            server.shutdown()
            server.server_close()
            worker.join()

    def test_ollama_uses_its_own_request_timeout(self):
        from config.agent import STEP_TIMEOUT
        from config.providers import PROVIDER_CONFIG
        from providers.ollama import OllamaProvider
        from providers.base import ProviderError
        self.assertEqual(STEP_TIMEOUT, 60)
        self.assertEqual(PROVIDER_CONFIG['ollama']['request_timeout'], 180)
        provider = OllamaProvider('http://127.0.0.1:11434')
        with patch('providers.ollama.urllib.request.build_opener') as factory:
            opener = factory.return_value
            opener.open.return_value.__enter__.return_value.read.return_value = b'{"message":{"content":"OK"}}'
            with patch.dict(PROVIDER_CONFIG['ollama'], request_timeout=240):
                self.assertEqual(provider.chat([{'role': 'user', 'content': 'Hallo'}]), 'OK')
                self.assertEqual(opener.open.call_args.kwargs['timeout'], 240)
            opener.open.side_effect = TimeoutError('synthetic timeout')
            with self.assertRaises(ProviderError):
                provider.chat([{'role': 'user', 'content': 'Hallo'}])
            self.assertEqual(opener.open.call_args.kwargs['timeout'], 180)


if __name__ == '__main__':
    unittest.main()
