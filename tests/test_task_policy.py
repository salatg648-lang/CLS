"""Task-Policies an echten SQLite-/Tool-Grenzen; Provider sind reine Protokoll-Fixtures."""
import json
import unittest
from unittest.mock import patch

from tests import test_automation as automation
from providers.base import ProviderTurn, ToolCall
from tasks.policy import normalize, effective, PolicyDenied, KNOWLEDGE_SOURCES
from tools.safety import PermissionDenied
from config.permissions import COMMANDS, PERMISSIONS


class PolicyTests(unittest.TestCase):
    setUp = automation.AutomationTests.setUp
    tearDown = automation.AutomationTests.tearDown
    approve = automation.AutomationTests.approve

    def provider(self, name='native', *, local=True, turns=None):
        provider = automation.NativeProvider(turns if turns is not None else [ProviderTurn(text='Information benötigt')])
        provider.name, provider.is_local = name, local
        provider.advice_calls = []
        def chat(messages, model=None):
            provider.advice_calls.append(messages)
            return 'Fixture-Antwort ohne Live-Aufruf.'
        provider.chat = chat
        self.registry.register(provider)
        return provider

    def task(self, mode='ALLOWED', **policy):
        return self.core.create_task('Unbekanntes Feature umsetzen', ai_policy={'mode': mode, **policy})

    def workflow(self, goal='Notiz prüfen', steps=None):
        return self.core.save_workflow(goal, goal, steps or [{'tool': 'read_file', 'args': {'path': 'note.txt'}}])

    def events(self, task, kind):
        return self.core.trail.list(task['id'], kind)

    def test_never_blocks_local_and_external_and_audits(self):
        local, external = self.provider(), self.provider('remote', local=False)
        task = self.task('NEVER')
        result = self.core.run_task(task['id'])
        self.assertEqual(result['status'], 'BLOCKED')
        self.assertEqual(result['api_calls'], 0)
        self.assertFalse(local.calls or external.calls)
        self.assertTrue(self.events(task, 'policy_blocked'))
        self.assertIn('AI call blocked by task policy', self.events(task, 'policy_blocked')[0]['detail']['reason'])

    def test_fallback_uses_local_workflow_without_model(self):
        provider = self.provider()
        self.workflow()
        task = self.core.create_task('Notiz prüfen', ai_policy={'mode': 'FALLBACK'})
        result = self.core.run_task(task['id'])
        self.assertEqual(result['status'], 'COMPLETED')
        self.assertFalse(provider.calls)
        self.assertFalse(result['local_assessment']['exhausted'])

    def test_fallback_requires_core_assessment_before_ai(self):
        provider = self.provider()
        task = self.task('FALLBACK')
        with self.assertRaises(PolicyDenied):
            self.core.agent._reserve_api(task, provider)
        result = self.core.run_task(task['id'])
        self.assertTrue(provider.calls)
        self.assertTrue(result['local_assessment']['exhausted'])
        assessment = self.events(task, 'local_assessment')[0]
        call = self.events(task, 'ai_call')[0]
        self.assertLess(assessment['id'], call['id'])

    def test_allowed_calls_provider_without_fallback(self):
        provider = self.provider(local=False)
        task = self.task()
        result = self.core.run_task(task['id'])
        self.assertEqual(result['api_calls'], 1)
        self.assertTrue(provider.calls)
        self.assertTrue(result['local_assessment']['exhausted'])
        # ALLOWED benötigt weiterhin keine Fallback-Freigabe als Voraussetzung.
        from tasks.policy import check_ai
        fresh = self.task()
        check_ai(fresh, provider)

    def test_provider_allowlist_filters_native_and_advisors(self):
        forbidden, allowed = self.provider('forbidden'), self.provider('allowed')
        task = self.task(allowed_providers=['allowed'])
        self.core.run_task(task['id'])
        self.core.agent._consult(self.core.tasks.get(task['id']), 'coding', 'Hilfe')
        self.assertFalse(forbidden.calls or forbidden.advice_calls)
        self.assertEqual(len(allowed.calls), 1)
        self.assertEqual(len(allowed.advice_calls), 1)

    def test_provider_failure_never_falls_back_to_disallowed(self):
        from providers.base import ProviderError
        forbidden, allowed = self.provider('forbidden'), self.provider('allowed')
        allowed.tool_chat = lambda *a, **k: (_ for _ in ()).throw(ProviderError('offline'))
        task = self.task(allowed_providers=['allowed'])
        self.assertEqual(self.core.run_task(task['id'])['status'], 'BLOCKED')
        self.assertFalse(forbidden.calls)

    def test_empty_allowlists_deny_all(self):
        provider = self.provider()
        task = self.task(allowed_providers=[], knowledge_sources=[])
        self.assertEqual(self.core.get_task_knowledge(task['id']), [])
        self.assertEqual(self.core.run_task(task['id'])['status'], 'BLOCKED')
        self.assertFalse(provider.calls)

    def test_knowledge_default_all_categories_scope_trust_and_provenance(self):
        self.core.add_knowledge('Atlas globales Wissen')
        self.core.add_knowledge('Atlas Projektregeln', project_id=self.project['id'])
        self.core.knowledge.add_entry('Atlas Recherche', source_type='web', url='https://example.test/atlas', trust='CONFIRMED')
        self.core.add_memory('Atlas Vorliebe')
        (self.work / 'atlas.md').write_text('Atlas Dokumentation')
        self.workflow('Atlas prüfen')
        old = self.core.create_task('Atlas prüfen')
        self.core.run_task(old['id'])
        other = self.core.create_project('Anderes Projekt', path=str(self.work))
        hidden = self.core.add_knowledge('Atlas fremdes Projekt', project_id=other['id'])['entry']
        candidate = self.core.knowledge.add_entry('Atlas unverifiziert', trust='CANDIDATE')['entry']
        task = self.core.create_task('Atlas', ai_policy={})
        self.assertEqual(task['ai_policy']['knowledge_sources'], 'ALL_AVAILABLE')
        sources = self.core.get_task_knowledge(task['id'])
        self.assertEqual({s['category'] for s in sources}, set(KNOWLEDGE_SOURCES))
        refs = {s['reference'] for s in sources}
        self.assertNotIn(f"knowledge:{hidden['id']}", refs)
        self.assertNotIn(f"knowledge:{candidate['id']}", refs)
        self.assertTrue(all('trust' in r and 'reference' in r for r in sources))

    def test_optional_knowledge_selection_filters_context_and_tools(self):
        self.core.add_knowledge('Atlas allgemein')
        entry = self.core.add_knowledge('Atlas Projekt', project_id=self.project['id'])['entry']
        task = self.core.create_task('Atlas', ai_policy={'knowledge_sources': ['PROJECT_KNOWLEDGE']})
        sources = self.core.get_task_knowledge(task['id'])
        self.assertEqual([s['reference'] for s in sources], [f"knowledge:{entry['id']}"])
        with self.assertRaises(PolicyDenied):
            self.core.tools.execute('read_file', {'path': 'note.txt'}, self.core.agent._context(task))
        (self.work / 'code.py').write_text('print(1)')
        self.assertTrue(self.core.tools.execute('read_file', {'path': 'code.py'}, self.core.agent._context(task))['ok'])

    def test_research_source_restriction_blocks_advisor(self):
        provider = self.provider()
        task = self.task(knowledge_sources=['PROJECT_KNOWLEDGE'])
        with self.assertRaises(PolicyDenied):
            self.core.agent._consult(task, 'research', 'Frage')
        self.assertFalse(provider.advice_calls)

    def test_area_inherits_ai_and_providers_but_defaults_all_knowledge(self):
        policy = normalize({'mode': 'FALLBACK', 'allowed_providers': ['gemini'],
            'knowledge_sources': ['PROJECT_KNOWLEDGE'], 'areas': {'Backend': {'mode': 'NEVER'},
            'Frontend': {'mode': 'ALLOWED', 'allowed_providers': ['perplexity']}, 'Tests': {}}})
        task = {'ai_policy': policy, 'policy_area': 'backend'}
        self.assertEqual(effective(task), {'mode': 'NEVER', 'allowed_providers': ['gemini'], 'knowledge_sources': 'ALL_AVAILABLE',
            'preferred_providers': [], 'required_capability': None, 'selected_provider': None,
            'local_only': False, 'allow_external': True})
        task['policy_area'] = 'frontend'
        self.assertEqual(effective(task)['allowed_providers'], ['perplexity'])
        task['policy_area'] = 'tests'
        self.assertEqual(effective(task)['mode'], 'FALLBACK')
        policy['areas']['tests']['knowledge_sources'] = ['EXPERIENCE']
        self.assertEqual(effective(task)['knowledge_sources'], ['EXPERIENCE'])

    def test_mixed_subtasks_use_their_own_policy_and_only_all_completed_finishes_parent(self):
        self.workflow('Backend prüfen')
        self.workflow('Tests prüfen')
        provider = self.provider('perplexity', turns=[ProviderTurn(calls=[
            ToolCall('p', 'set_plan', {'steps': ['Lesen']}),
            ToolCall('r', 'read_file', {'path': 'note.txt'}),
            ToolCall('f', 'finish_task', {'summary': 'Frontend geprüft'})])])
        task = self.core.create_task('Feature', ai_policy={'mode': 'FALLBACK', 'areas': {
            'backend': {'mode': 'NEVER'}, 'frontend': {'mode': 'ALLOWED', 'allowed_providers': ['perplexity']},
            'tests': {'mode': 'NEVER'}}}, subtasks=[{'area': a, 'goal': g} for a, g in [
                ('backend', 'Backend prüfen'), ('frontend', 'Frontend prüfen'), ('tests', 'Tests prüfen')]])
        result = self.core.run_task(task['id'])
        self.assertEqual(result['status'], 'COMPLETED')
        self.assertEqual([c['api_calls'] for c in result['subtasks']], [0, 1, 0])
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(len(self.core.get_tasks()), 1)

    def test_unresolved_subtask_keeps_parent_blocked(self):
        task = self.core.create_task('Feature', ai_policy={'mode': 'ALLOWED', 'areas': {'backend': {'mode': 'NEVER'}}},
            subtasks=[{'area': 'backend', 'goal': 'Unbekanntes Feature'}])
        result = self.core.run_task(task['id'])
        self.assertEqual(result['status'], 'BLOCKED')
        self.assertNotEqual(result['progress']['percent'], 100)
        self.assertEqual(self.core.get_experiences(project_id=self.project['id']), [])

    def test_area_rules_without_concrete_subtasks_fail_closed(self):
        provider = self.provider()
        task = self.core.create_task('Backend und Frontend', ai_policy={'mode': 'ALLOWED', 'areas': {'backend': {'mode': 'NEVER'}}})
        self.assertEqual(self.core.run_task(task['id'])['status'], 'NEEDS_INFORMATION')
        self.assertFalse(provider.calls)

    def test_subtask_scope_cannot_escape_project_or_sibling(self):
        with self.assertRaises(PermissionDenied):
            self.core.create_task('Feature', ai_policy={}, subtasks=[{'area': 'a', 'goal': 'x', 'path': '..'}])
        (self.work / 'backend').mkdir()
        task = self.core.create_task('Feature', ai_policy={}, subtasks=[{'area': 'a', 'goal': 'x', 'path': 'backend'}])
        child = self.core.get_task(task['subtask_ids'][0])
        with self.assertRaises(PermissionDenied):
            self.core.tools.execute('read_file', {'path': '../note.txt'}, self.core.agent._context(child))

    def test_subtasks_share_parent_api_budget(self):
        provider = self.provider(turns=[ProviderTurn(calls=[ToolCall('p','set_plan',{'steps':['Lesen']}),
            ToolCall('r','read_file',{'path':'note.txt'}),ToolCall('f','finish_task',{'summary':'geprüft'})])])
        task = self.core.create_task('Feature', ai_policy={'mode': 'ALLOWED'},
            subtasks=[{'area': a, 'goal': a} for a in ('a', 'b')])
        with patch('core.agent.limits.MAX_API_CALLS_PER_TASK', 1):
            result = self.core.run_task(task['id'])
        self.assertEqual(result['status'], 'BLOCKED')
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(result['api_calls'], 1)

    def test_local_only_never_sent_externally_even_with_all_and_consent(self):
        provider = self.provider(local=False)
        entry = self.core.add_knowledge('Atlas PRIVATER-INHALT')['entry']
        self.core.privacy.set_entry(entry['id'], 'LOCAL_ONLY')
        (self.work / 'atlas.md').write_text('Atlas PRIVATE-DATEI')
        self.core.set_path_privacy(self.work / 'atlas.md', 'LOCAL_ONLY')
        task = self.core.create_task('Atlas', ai_policy={'mode':'ALLOWED'}, allow_external=True)
        self.core.run_task(task['id'])
        sent = json.dumps(provider.calls)
        self.assertNotIn('PRIVATER-INHALT', sent)
        self.assertNotIn('PRIVATE-DATEI', sent)
        self.assertTrue(provider.calls)

    def test_local_context_cannot_leak_through_external_advisor(self):
        entry = self.core.add_knowledge('Atlas PRIVAT')['entry']
        self.core.privacy.set_entry(entry['id'], 'LOCAL_ONLY')
        self.provider()
        external = self.provider('remote', local=False)
        task = self.core.create_task('Atlas', ai_policy={'mode':'ALLOWED'}, allow_external=True)
        self.core.agent._knowledge_message(task, external=False)
        with self.assertRaises(PermissionDenied):
            self.core.agent._reserve_api(task, external)
        self.assertFalse(external.calls or external.advice_calls)

    def test_privacy_changes_rechecked_before_next_provider_call(self):
        provider = self.provider(local=False)
        entry = self.core.add_knowledge('Atlas sichtbar')['entry']
        task = self.core.create_task('Atlas', ai_policy={'mode':'ALLOWED'})
        self.core.agent._knowledge_message(task, external=True)
        self.core.privacy.set_entry(entry['id'], 'LOCAL_ONLY')
        with self.assertRaises(PermissionDenied):
            self.core.agent._reserve_api(task, provider)
        self.assertEqual(task['api_calls'], 0)

    def test_network_never_overrides_allowed_policy(self):
        provider = self.provider(local=False)
        task = self.task()
        with patch.dict(PERMISSIONS, {'network': 'never'}):
            self.assertEqual(self.core.run_task(task['id'])['status'], 'BLOCKED')
        self.assertFalse(provider.calls)

    def test_legacy_task_without_policy_retains_original_behavior(self):
        provider = self.provider()
        task = self.core.create_task('Legacy')
        task.pop('ai_policy')
        self.core.tasks.save(task)
        result = self.core.run_task(task['id'])
        self.assertEqual(result['api_calls'], 1)
        self.assertEqual(effective(task)['knowledge_sources'], 'ALL_AVAILABLE')
        self.assertTrue(provider.calls)

    def test_policy_and_child_rules_survive_database_restart(self):
        task = self.core.create_task('Restart', ai_policy={'mode':'NEVER','allowed_providers':['perplexity'],
            'areas':{'front':{'mode':'ALLOWED','knowledge_sources':['PROJECT_KNOWLEDGE']}}},
            subtasks=[{'area':'front','goal':'Frontend'}])
        self.db.close()
        from infrastructure.database import Database
        from tasks.task_manager import TaskManager
        from tasks.action_trail import ActionTrail
        self.db = Database(self.root / 'db.sqlite')
        manager = TaskManager(self.db, ActionTrail(self.db))
        restored = manager.get(task['id'])
        self.assertEqual(restored['ai_policy'], task['ai_policy'])
        child = manager.get(restored['subtask_ids'][0])
        self.assertEqual(effective(child), {'mode':'ALLOWED','allowed_providers':['perplexity'],
            'knowledge_sources':['PROJECT_KNOWLEDGE'], 'preferred_providers': [], 'required_capability': None,
            'selected_provider': None, 'local_only': False, 'allow_external': True})

    def test_denied_ai_can_continue_local_tools_and_verified_resolution(self):
        provider = self.provider(turns=[ProviderTurn(calls=[
            ToolCall('p','set_plan',{'steps':['Implementieren','Prüfen']}),
            ToolCall('a','ask_ai',{'capability':'coding','question':'Hilfe'}),
            ToolCall('w','write_file',{'path':'new.py','content':'x=1'}),
            ToolCall('b','run_build',{'command':'build'}),
            ToolCall('t','run_tests',{'command':'test'}),
            ToolCall('f','finish_task',{'summary':'Implementiert und geprüft'})])])
        provider.capabilities = ['general_reasoning']
        forbidden = self.provider('advisor')
        task = self.task(allowed_providers=['native'])
        commands = {n:{'argv':['{python}','-c','print("passed")'],'kind':k} for n,k in [('build','build'),('test','test')]}
        with patch.dict(COMMANDS, commands):
            result = self.core.run_task(task['id'])
            for _ in range(3):
                self.assertEqual(result['status'], 'NEEDS_CONFIRMATION')
                result = self.approve(task['id'])
        self.assertEqual(result['status'], 'COMPLETED')
        self.assertTrue(result['local_resolution'])
        self.assertTrue((self.work / 'new.py').exists())
        self.assertFalse(forbidden.calls or forbidden.advice_calls)
        self.assertTrue(self.events(task, 'policy_blocked'))

    def test_denied_ai_followed_by_read_cannot_claim_success(self):
        provider = self.provider(turns=[ProviderTurn(calls=[
            ToolCall('p','set_plan',{'steps':['Implementieren']}),
            ToolCall('a','ask_ai',{'capability':'coding','question':'Implementiere'}),
            ToolCall('r','read_file',{'path':'note.txt'}),
            ToolCall('f','finish_task',{'summary':'Fertig'}),
            ToolCall('h','request_help',{'status':'BLOCKED','reason':'Implementierung fehlt'})])])
        provider.capabilities = ['general_reasoning']
        task = self.task(allowed_providers=['native'])
        result = self.core.run_task(task['id'])
        self.assertEqual(result['status'], 'BLOCKED')
        self.assertIn('read_file', result['tools_used'])
        self.assertEqual(self.core.get_experiences(project_id=self.project['id']), [])

    def test_local_knowledge_answer_needs_no_model(self):
        self.core.add_knowledge('Atlas ist das Projektwerkzeug.')
        task = self.core.create_task('Was weißt du über Atlas?', ai_policy={'mode':'NEVER'})
        result = self.core.run_task(task['id'])
        self.assertEqual(result['status'], 'COMPLETED')
        self.assertIn('Atlas ist das Projektwerkzeug', result['result'])
        self.assertEqual(result['api_calls'], 0)

    def test_blocked_root_cannot_answer_locally(self):
        self.core.add_knowledge('Atlas vertraulich')
        self.core.set_path_privacy(self.work, 'BLOCKED')
        task = self.core.create_task('Was weißt du über Atlas?', ai_policy={'mode':'NEVER'})
        result = self.core.run_task(task['id'])
        self.assertEqual(result['status'], 'BLOCKED')
        self.assertEqual(result['result'], '')

    def test_unrelated_project_instructions_do_not_fake_knowledge_answer(self):
        self.project['instructions'] = 'Nutze Python'
        task = self.core.create_task('Was weißt du über Quokka?', ai_policy={'mode':'NEVER'})
        task['project'] = self.project
        self.core.tasks.save(task)
        self.assertEqual(self.core.run_task(task['id'])['status'], 'BLOCKED')

    def test_command_output_cannot_bypass_documentation_restriction(self):
        task = self.task(knowledge_sources=['PROJECT_KNOWLEDGE'])
        task['messages'] = []
        task['queue'] = [{'id':'x','name':'run_tests','arguments':{}}]
        self.core.agent._result(task, task['queue'][0], {'ok':True,'output':'excluded document content'})
        self.assertNotIn('output', task['messages'][0]['result'])

    def test_private_experience_is_filtered_and_nested_provenance_rechecked(self):
        origin = self.core.create_task('Atlas', allow_external=True)
        origin.update(verified=True, result='Atlas private result', status='COMPLETED',
                      read_paths=[str(self.work / 'note.txt')])
        self.core.tasks.save(origin)
        self.core.experience.record(origin)
        second = self.core.create_task('Atlas erneut', allow_external=True)
        second.update(verified=True, result='Atlas summary', status='COMPLETED',
            knowledge_used=[{'category':'EXPERIENCE','reference':'experience:'+origin['id']}])
        self.core.tasks.save(second)
        self.core.experience.record(second)
        self.core.set_path_privacy(self.work / 'note.txt','LOCAL_ONLY')
        task = self.core.create_task('Atlas', ai_policy={'mode':'ALLOWED'}, allow_external=True)
        sources = self.core.get_task_knowledge(task['id'], external=True)
        self.assertNotIn('EXPERIENCE', {s['category'] for s in sources})
        self.assertFalse(self.core.context._experience_external_safe(second['id']))

    def test_denied_source_cannot_be_ignored_to_finish_task(self):
        provider = self.provider(turns=[ProviderTurn(calls=[
            ToolCall('p','set_plan',{'steps':['Dokument prüfen']}),
            ToolCall('r','read_file',{'path':'note.txt'}),
            ToolCall('s','search_files',{'pattern':'*.py'}),
            ToolCall('f','finish_task',{'summary':'Fertig'}),
            ToolCall('h','request_help',{'status':'BLOCKED','reason':'Dokument gesperrt'})])])
        task = self.task(knowledge_sources=['PROJECT_KNOWLEDGE'])
        result = self.core.run_task(task['id'])
        self.assertEqual(result['status'], 'BLOCKED')
        self.assertTrue(result['policy_blocked_required'])
        self.assertEqual(self.core.get_experiences(project_id=self.project['id']), [])

    def test_search_filter_does_not_mark_filtered_sources_as_required(self):
        self.workflow('Suchen', [{'tool':'search_files','args':{'pattern':'*'}}])
        task = self.core.create_task('Suchen', ai_policy={'mode':'NEVER','knowledge_sources':['PROJECT_KNOWLEDGE']})
        self.assertEqual(self.core.run_task(task['id'])['status'], 'COMPLETED')

    def test_malformed_policy_rejected_without_partial_task(self):
        for policy in ({'mode':'SOMETIMES'}, {'allowed_providers':'gemini'}, {'knowledge_sources':['UNKNOWN']},
                       {'areas':{'a':{'mode':'INVALID'}}}, {'areas':{'a':{},'A':{}}}):
            with self.subTest(policy=policy), self.assertRaises(ValueError):
                self.core.create_task('Test', ai_policy=policy)
        self.assertEqual(self.core.get_tasks(), [])
