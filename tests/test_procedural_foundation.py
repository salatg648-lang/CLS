"""Persistente Episoden, Strategiescope und keine implizite Freigabe."""
import json
import sqlite3
import unittest

from tests import test_automation as automation
from infrastructure.database import Database, _SCHEMA_V1
from infrastructure.automation_schema import SCHEMA
from knowledge.base import KnowledgeBase
from knowledge.trust import evaluate
from memory.episodic import EpisodicMemory


class ProceduralFoundationTests(unittest.TestCase):
    setUp = automation.AutomationTests.setUp
    tearDown = automation.AutomationTests.tearDown

    def episode(self, project_id=None):
        task = self.core.create_task('Atlas prüfen', project_id=project_id or self.project['id'])
        self.core.trail.add(task['id'], 'tool', {'tool': 'run_tests', 'ok': False, 'exit_code': 1})
        self.core.trail.add(task['id'], 'error', {'tool': 'run_tests', 'exit_code': 1})
        self.core.trail.add(task['id'], 'replan', {'steps': ['Methode B prüfen']})
        self.core.trail.add(task['id'], 'tool', {'tool': 'run_tests', 'ok': True, 'exit_code': 0})
        task.update(status='COMPLETED', verified=True, result='Atlas geprüft', checks=['run_tests'])
        self.core.tasks.save(task)
        self.core.experience.record(task)
        return task

    def propose(self, ids, content='Bei Atlas zuerst Methode B prüfen.'):
        return self.core.propose_strategy(content, ids, applicability='Atlas mit gleichem Fehlermuster',
                                          rationale='A schlug fehl; nach Umplanung war B erfolgreich.')

    def test_episode_preserves_failure_replan_success_and_verification(self):
        task = self.episode()
        item = self.core.experience.get(task['id'])
        summary = item['summary']
        actions = summary['timeline']
        self.assertTrue(summary['timeline_complete'])
        self.assertEqual([a['id'] for a in actions], sorted(a['id'] for a in actions))
        self.assertEqual([a['kind'] for a in actions[-4:]], ['tool', 'error', 'replan', 'tool'])
        self.assertFalse(actions[-4]['detail']['ok'])
        self.assertTrue(actions[-1]['detail']['ok'])
        self.assertEqual(summary['verification'], {'verified': True, 'dirty': False, 'checks': ['run_tests']})
        self.assertEqual(summary['provenance']['project_id'], self.project['id'])
        self.assertEqual(self.core.list_knowledge(kind='strategy'), [])
        first = EpisodicMemory.fingerprint(item)
        task['result'] = 'Andere Beobachtung'
        self.core.experience.record(task)
        self.assertNotEqual(first, EpisodicMemory.fingerprint(self.core.experience.get(task['id'])))

    def test_truncated_trail_is_explicit(self):
        task = self.episode()
        with self.db.transaction():
            for _ in range(5001):
                self.db.execute("INSERT INTO actions(task_id,kind,detail,created_at) VALUES (?,'error','{}','now')",
                                (task['id'],))
        self.core.experience.record(task)
        summary = self.core.experience.get(task['id'])['summary']
        self.assertFalse(summary['timeline_complete'])
        self.assertEqual(len(summary['timeline']), 5000)

    def test_candidate_uses_existing_knowledge_provenance_and_persists(self):
        task = self.episode()
        entry = self.propose([task['id'], task['id']])
        self.assertEqual((entry['kind'], entry['trust']), ('strategy', 'CANDIDATE'))
        meta = entry['strategy']
        self.assertEqual(meta['status'], 'CANDIDATE')
        self.assertIsNone(meta['confidence'])
        self.assertIsNone(meta['verification'])
        self.assertEqual(meta['scope'], {'kind': 'project', 'project_id': self.project['id']})
        self.assertEqual(len(meta['evidence']), 1)
        self.assertEqual(entry['sources'][0]['reference'], 'derived:experience:' + task['id'] + '@' +
                         EpisodicMemory.fingerprint(self.core.experience.get(task['id'])))
        self.assertEqual(entry['versions'][0]['changed_by'], 'reflection')
        reopened = Database(self.db.path)
        try:
            self.assertEqual(KnowledgeBase(reopened).get_entry(entry['id'])['strategy'], meta)
        finally:
            reopened.close()

    def test_repetition_and_source_count_do_not_promote(self):
        entry = self.propose([self.episode()['id'], self.episode()['id']])
        for name in ('one', 'two'):
            self.core.add_knowledge_source(entry['id'], 'document', name=name)
        self.assertEqual(self.core.get_knowledge_entry(entry['id'])['trust'], 'CANDIDATE')
        for level in ('CONFIRMED', 'SUPPORTED', 'UNCERTAIN'):
            with self.assertRaises(ValueError):
                self.core.set_knowledge_trust(entry['id'], level)
        self.assertEqual(evaluate('CANDIDATE', [{'source_type': 'experience', 'name': name}
                                               for name in ('one', 'two')]), 'CANDIDATE')

    def test_scope_and_missing_evidence_cannot_be_bypassed(self):
        task = self.episode()
        other = self.core.create_project('Other', path=str(self.work))
        second = self.episode(other['id'])
        for ids in ([], ['missing'], [task['id'], second['id']], task['id']):
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                self.propose(ids)
        with self.assertRaises(ValueError):
            self.core.knowledge.add_entry('Atlas', kind='strategy', trust='CONFIRMED')
        for content in ('', None):
            with self.assertRaises(ValueError):
                self.propose([task['id']], content)
        self.assertEqual(self.core.list_knowledge(kind='strategy'), [])

    def test_legacy_episode_stays_unverified_as_strategy_evidence(self):
        task = self.episode()
        legacy = {'result': 'Atlas geprüft', 'steps': [], 'errors': [], 'solutions': [],
                  'verified': True, 'status': 'COMPLETED'}
        self.db.execute('UPDATE experiences SET summary=? WHERE task_id=?', (json.dumps(legacy), task['id']))
        entry = self.propose([task['id']])
        self.assertFalse(entry['strategy']['evidence'][0]['timeline_complete'])
        self.assertEqual(entry['trust'], 'CANDIDATE')
        self.assertEqual(self.core.get_experiences(project_id=self.project['id'])[0]['summary'], legacy)

    def test_no_context_injection_even_after_indirect_trust_change(self):
        entry = self.propose([self.episode()['id']])
        task = self.core.create_task('Atlas prüfen')
        for trust in ('CANDIDATE', 'SUPPORTED', 'CONFIRMED', 'CONFLICTING'):
            self.db.execute('UPDATE knowledge_entries SET trust=? WHERE id=?', (trust, entry['id']))
            for external in (False, True):
                found = self.core.context.find_knowledge('Atlas', self.project, external=external)
                self.assertNotIn(entry['id'], [e['id'] for e in found])
                records = self.core.context.task_sources(task, external=external)
                self.assertNotIn('knowledge:' + str(entry['id']), [r['reference'] for r in records])
            self.core.context.privacy = None
            try:
                self.assertEqual(self.core.context.find_knowledge('Atlas', self.project), [])
                self.assertNotIn('Methode B', self.core.send_message('Was weißt du über Atlas?'))
            finally:
                self.core.context.privacy = self.core.privacy

    def test_duplicates_and_edits_do_not_reinterpret_candidate_as_fact(self):
        entry = self.propose([self.episode()['id']])
        with self.assertRaises(ValueError):
            self.core.add_knowledge(entry['content'], project_id=self.project['id'])
        with self.assertRaises(ValueError):
            self.core.update_knowledge(entry['id'], content='Neue Behauptung')
        with self.assertRaises(ValueError):
            self.propose([self.episode()['id']], entry['content'])
        self.assertEqual(self.core.get_knowledge_entry(entry['id'])['trust'], 'CANDIDATE')

    def test_retirement_and_project_deletion_preserve_origin_scope(self):
        entry = self.propose([self.episode()['id']])
        self.core.delete_project(self.project['id'])
        kept = self.core.get_knowledge_entry(entry['id'])
        self.assertEqual(kept['strategy']['scope']['project_id'], self.project['id'])
        self.assertEqual((kept['strategy']['status'], kept['trust']), ('RETIRED', 'OUTDATED'))
        with self.assertRaises(ValueError):
            self.core.set_knowledge_trust(entry['id'], 'CANDIDATE')
        self.assertEqual(self.core.context.find_knowledge('Atlas', None), [])

    def test_schema_v3_migration_keeps_knowledge_and_is_idempotent(self):
        path = self.root / 'legacy.db'
        con = sqlite3.connect(path)
        con.executescript(_SCHEMA_V1 + SCHEMA)
        con.execute("INSERT INTO knowledge_entries(title,content,trust,created_at,updated_at) "
                    "VALUES ('Atlas','Atlas Wissen','CONFIRMED','now','now')")
        con.execute('PRAGMA user_version=3')
        con.commit()
        con.close()
        for _ in range(2):
            db = Database(path)
            try:
                item = KnowledgeBase(db).get_entry(1)
                self.assertEqual((item['content'], item['trust'], item['strategy']), ('Atlas Wissen', 'CONFIRMED', {}))
                self.assertEqual(db.query_one('PRAGMA user_version')['user_version'], 5)
            finally:
                db.close()
