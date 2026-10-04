"""Provider-Payloads statt Prompt-Versprechen: Retrieval, Grenzen und Ergebnisprüfung."""
import json
import unittest
from unittest.mock import patch

from tests import test_task_policy as policy_fixtures
from providers.base import ProviderTurn, ToolCall, ProviderError
from core.context_minimizer import excerpt, minimize
from config.knowledge import CONTEXT_MAX_CHARS, CONTEXT_MAX_ENTRIES
from tools.safety import LimitReached


class RetrievalTests(unittest.TestCase):
    setUp = policy_fixtures.PolicyTests.setUp
    tearDown = policy_fixtures.PolicyTests.tearDown
    provider = policy_fixtures.PolicyTests.provider

    def task(self, goal='Atlas pagination', mode='ALLOWED', **policy):
        return self.core.create_task(goal, ai_policy={'mode':mode, **policy}, allow_external=True)

    def test_five_hundred_entries_scope_privacy_counts_and_small_actual_payload(self):
        for i in range(492):
            self.core.knowledge.add_entry(f'Unrelateditem{i} gardening.', check_conflicts=False)
        for i in range(8):
            entry = self.core.knowledge.add_entry(f'Quasar instruction{i} relevant.', check_conflicts=False)['entry']
            if i < 3:
                self.core.privacy.set_entry(entry['id'], 'LOCAL_ONLY')
        provider = self.provider(local=False)
        task = self.task('Quasar')
        self.core.run_task(task['id'])
        payload = json.dumps(provider.calls)
        for i in range(3):
            self.assertNotIn(f'instruction{i}', payload)
        for i in range(3, 8):
            self.assertIn(f'instruction{i}', payload)
        self.assertNotIn('gardening', payload)
        context = self.core.trail.list(task['id'], 'knowledge_selected')[0]['detail']
        self.assertEqual((context['selected'], context['privacy_excluded'], context['unrelated_entries']), (5, 3, 492))
        self.assertLess(len(json.dumps(context)), 2000)
        self.assertFalse(any('content' in ref for ref in context['sources']))

    def test_large_file_tail_is_retrieved_without_sending_the_file(self):
        unrelated = '\n'.join(f'Gardening unrelated item {i}.' for i in range(500))
        relevant = 'Atlas pagination uses cursor_token as the continuation parameter.'
        (self.work / 'handbook.md').write_text(unrelated + '\n' + relevant + '\nUnrelated final topic.')
        provider = self.provider(local=False)
        task = self.task()
        self.core.run_task(task['id'])
        payload = json.dumps(provider.calls)
        self.assertIn(relevant, payload)
        self.assertNotIn('Gardening unrelated', payload)
        self.assertNotIn('Unrelated final', payload)
        self.assertNotIn(unrelated, payload)
        result = self.core.context.retrieve_task(task, external=True)
        doc = next(r for r in result.records if r['category'] == 'DOCUMENTATION')
        self.assertGreater(doc['source_chars'], len(doc['content']) * 10)
        self.assertTrue(doc['excerpted'])

    def test_large_knowledge_entry_and_chat_use_relevant_tail(self):
        body = 'Gardening advice.\n' * 500 + 'Atlas pagination uses cursor_token.'
        self.core.add_knowledge(body)
        task = self.task()
        result = self.core.context.retrieve_task(task, external=True)
        self.assertEqual(result.records[0]['content'], 'Atlas pagination uses cursor_token.')
        prompt = self.core.context.build('Atlas pagination', external=True).messages[0]['content']
        self.assertIn('cursor_token', prompt)
        self.assertNotIn('Gardening advice.\nGardening', prompt)

    def test_context_minimizer_deduplicates_and_applies_shared_serialized_budget(self):
        records = [{'reference':f'knowledge:{i}', 'category':'CLS_KNOWLEDGE', 'trust':'CONFIRMED',
            'content':f'Atlas pagination variant{i} '+('details '*120),
            'provenance':[{'name':'x'*10000,'url':'y'*10000}]*20} for i in range(30)]
        records += [dict(records[0], reference='file:duplicate')]
        result = minimize(records, 'Atlas pagination')
        self.assertGreater(result.stats['duplicates'], 0)
        self.assertGreater(result.stats['budget_excluded'], 0)
        self.assertLessEqual(len(result.records), CONTEXT_MAX_ENTRIES)
        self.assertLessEqual(len(json.dumps(result.records, ensure_ascii=False)), CONTEXT_MAX_CHARS)
        self.assertTrue(all('Atlas pagination' in r['content'] for r in result.records))

    def test_same_text_across_sources_is_sent_once(self):
        text = 'Atlas pagination uses cursor_token.'
        self.core.add_knowledge(text)
        (self.work / 'atlas.md').write_text(text)
        result = self.core.context.retrieve_task(self.task(), external=True)
        self.assertEqual(len(result.records), 1)
        self.assertEqual(result.stats['duplicates'], 1)

    def test_scope_policy_and_private_conflict_partner_do_not_leak(self):
        other = self.core.create_project('Other', path=str(self.work))
        self.core.add_knowledge('Atlas ForeignSentinel', project_id=other['id'])
        public = self.core.add_knowledge('Atlas needs Java 17')['entry']
        private = self.core.add_knowledge('Atlas needs Java 21 PRIVATE-SENTINEL')['entry']
        self.core.privacy.set_entry(private['id'], 'LOCAL_ONLY')
        own = self.core.add_knowledge('Atlas OwnSentinel', project_id=self.project['id'])['entry']
        task = self.task('Atlas', knowledge_sources=['PROJECT_KNOWLEDGE'])
        result = self.core.context.retrieve_task(task, external=True)
        self.assertEqual([r['reference'] for r in result.records], [f"knowledge:{own['id']}"])
        self.assertNotIn('ForeignSentinel', json.dumps(result.records))
        self.assertNotIn('PRIVATE-SENTINEL', json.dumps(result.records))
        self.assertNotIn(f"knowledge:{public['id']}", json.dumps(result.records))

    def test_missing_knowledge_is_a_gap_and_fallback_request_is_targeted(self):
        provider = self.provider(local=False)
        task = self.task('Quasar continuation parameter', mode='FALLBACK')
        result = self.core.run_task(task['id'])
        self.assertIn('missing_knowledge', result['local_assessment']['knowledge_gaps'])
        self.assertIn('Zulässige Belege fehlen', json.dumps(provider.calls, ensure_ascii=False))
        self.assertIn('Quasar continuation parameter', json.dumps(provider.calls))
        events = list(reversed(self.core.trail.list(task['id'])))
        self.assertLess(next(i for i,e in enumerate(events) if e['kind']=='local_assessment'),
                        next(i for i,e in enumerate(events) if e['kind']=='ai_call'))

    def test_uncertain_knowledge_does_not_fake_local_completion(self):
        self.core.knowledge.add_entry('Atlas uses a cursor.', trust='UNCERTAIN')
        provider = self.provider()
        task = self.task('Was weißt du über Atlas?', mode='FALLBACK')
        result = self.core.run_task(task['id'])
        self.assertIn('low_confidence', result['local_assessment']['knowledge_gaps'])
        self.assertTrue(provider.calls)
        self.assertNotEqual(result['status'], 'COMPLETED')

    def test_conflicting_knowledge_never_policy_stays_blocked_without_call(self):
        self.core.add_knowledge('Atlas needs Java 17')
        self.core.add_knowledge('Atlas needs Java 21')
        provider = self.provider()
        task = self.task('Was weißt du über Atlas?', mode='NEVER')
        result = self.core.run_task(task['id'])
        self.assertIn('conflicting_knowledge', result['local_assessment']['knowledge_gaps'])
        self.assertEqual(result['status'], 'BLOCKED')
        self.assertFalse(provider.calls)

    def test_old_relevant_fact_marks_freshness_without_overwriting_trust(self):
        entry = self.core.add_knowledge('Atlas pagination uses cursor.')['entry']
        self.db.execute('UPDATE knowledge_entries SET updated_at=? WHERE id=?', ('2020-01-01T00:00:00', entry['id']))
        result = self.core.context.retrieve_task(self.task())
        self.assertIn('freshness_unverified', result.gaps)
        self.assertEqual(result.records[0]['trust'], 'CONFIRMED')
        self.assertEqual(result.records[0]['version'], 1)

    def test_next_step_uses_its_query_not_all_task_knowledge(self):
        self.core.add_knowledge('Atlas AtlasSentinel')
        self.core.add_knowledge('Neptune NeptuneSentinel')
        task = self.task('Atlas und Neptune')
        task['plan'] = ['Atlas', 'Neptune']
        task['progress']['completed_steps'] = ['Atlas']
        message = self.core.agent._knowledge_message(task, external=True)
        self.assertIn('NeptuneSentinel', message['content'])
        self.assertNotIn('AtlasSentinel', message['content'])

    def test_file_tool_results_are_minimized_in_actual_next_request(self):
        body = 'GardeningUnrelated.\n'*500 + 'Atlas pagination uses cursor_token.'
        (self.work / 'handbook.md').write_text(body)
        provider = self.provider(local=False, turns=[ProviderTurn(calls=[
            ToolCall('p','set_plan',{'steps':['Atlas pagination prüfen']}),
            ToolCall('r','read_file',{'path':'handbook.md','query':'Atlas pagination'})]),
            ProviderTurn(text='Weitere Prüfung erforderlich.')])
        task = self.task()
        self.core.run_task(task['id'])
        self.assertEqual(len(provider.calls), 2)
        sent = json.dumps(provider.calls[1])
        self.assertIn('cursor_token', sent)
        self.assertNotIn('GardeningUnrelated', sent)
        response = next(m for m in provider.calls[1] if m['role']=='tool' and m['name']=='read_file')
        self.assertTrue(response['result']['context_minimized'])
        self.assertEqual(response['call_id'], 'r')

    def test_old_tool_rounds_not_replayed_and_native_signature_is_preserved(self):
        task = self.task()
        native = {'provider':'gemini','content':{'parts':[{'function_call':{'id':'new','name':'read_file','args':{'path':'note.txt'}},
                                                       'thought_signature':'synthetic-signature'}]}}
        task['messages'] = [{'role':'system','content':'system'}, {'role':'user','content':task['goal']},
            {'role':'assistant','native':{'provider':'gemini','content':{'parts':[]}},'content':'old'},
            {'role':'tool','name':'read_file','call_id':'old','result':{'content':'OLD-FULL-FILE '*4000}},
            {'role':'assistant','content':'','native':native},
            {'role':'tool','name':'read_file','call_id':'new','result':{'content':'Atlas relevant.'}}]
        messages = self.core.context.provider_messages(task, {'role':'system','content':'references'}, 'Atlas')
        self.assertNotIn('OLD-FULL-FILE', json.dumps(messages))
        self.assertEqual(next(m['native'] for m in messages if m.get('native')), native)
        self.assertEqual([m['call_id'] for m in messages if m['role']=='tool'], ['new'])

    def test_total_request_budget_blocks_before_api_reservation(self):
        provider = self.provider()
        task = self.task()
        with patch('core.agent.PROVIDER_REQUEST_MAX_CHARS', 30):
            result = self.core.run_task(task['id'])
        self.assertEqual(result['status'], 'BLOCKED')
        self.assertIn('Kontextbudget', result['blocking']['reason'])
        self.assertEqual(result['api_calls'], 0)
        self.assertFalse(provider.calls)

    def test_ai_answer_remains_candidate_and_confirmed_entry_is_unchanged(self):
        original = self.core.add_knowledge('Atlas needs Java 17')['entry']
        provider = self.provider(local=False)
        provider.chat = lambda *a, **k: 'Atlas needs Java 21'
        task = self.task('Atlas Java')
        result = self.core.agent._consult(task, 'coding', 'Welche Java Version braucht Atlas?')
        assessment = result['verification']
        self.assertFalse(result['ok'])
        self.assertEqual(assessment['status'], 'conflict')
        self.assertTrue(assessment['conflict_ids'])
        candidate = self.core.get_knowledge_entry(assessment['candidate_id'])
        self.assertNotEqual(candidate['trust'], 'CONFIRMED')
        unchanged = self.core.get_knowledge_entry(original['id'])
        self.assertEqual((unchanged['content'], unchanged['trust'], unchanged['current_version']),
                         ('Atlas needs Java 17', 'CONFIRMED', 1))
        task['verified'] = True
        with self.assertRaisesRegex(ValueError, 'Widersprüchliche'):
            self.core.agent._finish(task, 'Fertig')

    def test_consistent_new_answer_is_still_unverified_candidate(self):
        self.core.add_knowledge('Atlas supports cursor pagination.')
        provider = self.provider(local=False)
        provider.chat = lambda *a, **k: 'Atlas cursor_token selects the next page.'
        task = self.task()
        result = self.core.agent._consult(task, 'coding', 'Atlas pagination')
        self.assertEqual(result['verification']['status'], 'unverified')
        candidate = self.core.get_knowledge_entry(result['verification']['candidate_id'])
        self.assertEqual(candidate['trust'], 'CANDIDATE')
        self.assertNotIn(f"knowledge:{candidate['id']}", [r['reference'] for r in self.core.get_task_knowledge(task['id'])])

    def test_duplicate_answer_never_changes_existing_trust_or_privacy(self):
        original = self.core.add_knowledge('Atlas uses cursor pagination.', project_id=self.project['id'])['entry']
        provider = self.provider(local=True)
        provider.chat = lambda *a, **k: original['content']
        result = self.core.agent._consult(self.task(), 'coding', 'Atlas pagination')
        self.assertEqual(result['verification']['status'], 'matching_evidence')
        self.assertFalse(result['verification']['created'])
        self.assertEqual(self.core.get_knowledge_privacy(original['id']), 'SAFE_FOR_EXTERNAL')
        self.assertEqual(self.core.get_knowledge_entry(original['id'])['trust'], 'CONFIRMED')

    def test_candidate_keeps_source_privacy_after_confirmation(self):
        original = self.core.add_knowledge('Atlas cursor pagination supports continuation.')['entry']
        provider = self.provider(local=False)
        provider.chat = lambda *a, **k: 'Atlas cursor pagination advances through pages.'
        task = self.task()
        result = self.core.agent._consult(task, 'coding', 'Atlas pagination')
        candidate = result['verification']['candidate_id']
        self.core.confirm_knowledge(candidate)
        self.core.set_knowledge_privacy(original['id'], 'LOCAL_ONLY')
        self.assertFalse(self.core.context._may_use(self.core.get_knowledge_entry(candidate), True))
        self.assertTrue(self.core.context._may_use(self.core.get_knowledge_entry(candidate), False))
        refs = [r['reference'] for r in self.core.context.retrieve_task(task, external=True).records]
        self.assertNotIn(f'knowledge:{candidate}', refs)

    def test_changed_reference_version_is_not_used_for_new_conflict(self):
        entry = self.core.add_knowledge('Atlas needs Java 17')['entry']
        task = self.task('Atlas Java')
        references = self.core.context.retrieve_task(task, external=True).records
        self.core.update_knowledge(entry['id'], content='Atlas needs Java 21')
        result = self.core.knowledge.assess_task_answer('Atlas Java', 'Atlas needs Java 21', 'fixture',
                                                      self.project['id'], references)
        self.assertEqual(result['conflict_ids'], [])
        self.assertEqual(self.core.get_knowledge_entry(entry['id'])['current_version'], 2)

    def test_private_conflict_reference_itself_is_not_exported(self):
        a = self.core.add_knowledge('Atlas needs Java 17')['entry']
        b = self.core.add_knowledge('Atlas needs Java 21')['entry']
        self.core.set_knowledge_privacy(b['id'], 'LOCAL_ONLY')
        result = self.core.context.retrieve_task(self.task('Atlas Java'), external=True)
        self.assertEqual(len(result.records), 1)
        self.assertEqual(result.records[0]['reference'], f"knowledge:{a['id']}")
        self.assertEqual(result.records[0]['conflicts_with'], [])
        self.assertTrue(result.records[0]['conflict_unresolved'])

    def test_counts_remain_accurate_without_fts(self):
        self.core.add_knowledge('Atlas pagination')
        self.core.add_knowledge('Unrelated gardening')
        with patch.object(self.db, 'fts_available', False):
            result = self.core.context.retrieve_task(self.task())
        self.assertEqual(result.stats['matching_entries'], 1)
        self.assertEqual(result.stats['unrelated_entries'], 1)

    def test_external_chat_excludes_irrelevant_facts_and_bounds_old_history(self):
        for content in ('GardenSecret is unrelated.', 'Atlas uses cursors.'):
            fact = self.core.add_memory(content)
            self.core.set_memory_privacy(fact['id'], 'SAFE_FOR_EXTERNAL')
        self.core.conversation.add('user', 'OldBulkContext '*2000, meta={'project_id': self.project['id']})
        self.core.conversation.add('assistant', 'OldBulkAnswer '*2000, meta={'project_id': self.project['id']})
        messages = self.core.context.build('Atlas pagination', external=True).messages
        self.assertNotIn('GardenSecret', json.dumps(messages))
        self.assertIn('Atlas uses cursors.', messages[0]['content'])
        self.assertTrue(all(len(m['content']) <= 1200 for m in messages[1:-1]))

    def test_edit_task_and_subtask_policy_is_atomic_persistent_and_not_after_execution(self):
        task = self.core.create_task('Feature', ai_policy={'mode':'NEVER','areas':{'front':{'mode':'NEVER'}}},
                                     subtasks=[{'area':'front','goal':'Atlas'}])
        changed = self.core.update_task_policy(task['id'], {'mode':'FALLBACK','areas':{
            'front':{'mode':'ALLOWED','allowed_providers':['perplexity'],'knowledge_sources':['PROJECT_KNOWLEDGE']}}})
        self.assertEqual(changed['id'], task['id'])
        self.assertEqual(changed['subtask_ids'], task['subtask_ids'])
        self.assertEqual(changed['subtasks'][0]['ai_policy'], changed['ai_policy'])
        self.assertEqual(self.core.get_task(changed['subtask_ids'][0])['effective_policy']['allowed_providers'], ['perplexity'])
        before = changed['ai_policy']
        with self.assertRaises(ValueError):
            self.core.update_task_policy(task['id'], {'areas':{'unknown':{}}})
        self.assertEqual(self.core.get_task(task['id'])['ai_policy'], before)
        child = self.core.tasks.get(task['subtask_ids'][0]); child['api_calls']=1; self.core.tasks.save(child)
        with self.assertRaises(ValueError):
            self.core.update_task_policy(task['id'], {'mode':'NEVER'})
        self.assertFalse(self.core.get_task(task['id'])['policy_editable'])

    def test_edit_blocked_never_task_without_execution_clears_old_assessment(self):
        task = self.task(mode='NEVER')
        self.core.run_task(task['id'])
        changed = self.core.update_task_policy(task['id'], {'mode':'ALLOWED'})
        self.assertEqual(changed['status'], 'CREATED')
        self.assertIsNone(changed['local_assessment'])
        self.assertNotIn('policy_blocked_required', changed)
        provider = self.provider()
        self.core.run_task(task['id'])
        self.assertTrue(provider.calls)

    def test_inner_punctuation_keeps_dotted_identifiers_and_versions(self):
        sentence = 'Atlas.API supports Python 3.12 and https://example.test/docs.'
        self.assertEqual(excerpt(sentence+' Unrelated gardens.', 'Atlas'), sentence)
        long_line = 'prefix.segment '*4000 + 'Atlas.API requires version 3.12'
        self.assertIn('Atlas.API', excerpt(long_line, 'Atlas'))

    def test_fts_diacritic_and_prefix_matches_survive_minimization(self):
        sentence = 'Übertragung und Konfiguration benötigen gültige Schlüssel.'
        self.core.add_knowledge(sentence)
        for query in ('ubertrag', 'konfig', 'schlüssel'):
            with self.subTest(query=query):
                result = self.core.context.retrieve_task(self.task(query), external=True)
                self.assertEqual(result.records[0]['content'], sentence)
                self.assertNotIn('missing_knowledge', result.gaps)
        # Decomposed accents change normalized offsets; retain original spelling in a long line.
        decomposed = 'e\u0301 '*1000 + 'Übertragung benötigt Schlüssel.'
        self.assertIn('Übertragung benötigt Schlüssel.', excerpt(decomposed, 'ubertrag'))

    def test_repeated_short_tool_results_keep_each_call_result(self):
        task = self.task()
        task['messages'] = [{'role':'system','content':'system'}, {'role':'user','content':'Atlas'},
            {'role':'assistant','content':'Prüfen'},
            *[{'role':'tool','name':'run_tests','call_id':str(i),
               'result':{'output':'FAILED: ImportError'}} for i in range(2)]]
        messages = self.core.context.provider_messages(task, {'role':'system','content':'context'}, 'Atlas')
        results = [m for m in messages if m['role']=='tool']
        self.assertEqual([m['call_id'] for m in results], ['0', '1'])
        self.assertEqual([m['result']['output'] for m in results], ['FAILED: ImportError'] * 2)

    def test_small_tool_result_and_unmatched_long_result_remain_useful(self):
        task = self.task()
        task['messages'] = [{'role':'system','content':'system'}, {'role':'user','content':'Atlas'},
            {'role':'assistant','content':'Prüfen'},
            {'role':'tool','name':'run_tests','call_id':'t','result':{'output':'FAILED: ImportError'}},
            {'role':'tool','name':'read_file','call_id':'r','result':{'content':'unmatched_header '+('data '*1000)}}]
        messages = self.core.context.provider_messages(task, {'role':'system','content':'context'}, 'Atlas')
        results = [m['result'] for m in messages if m['role']=='tool']
        self.assertEqual(results[0]['output'], 'FAILED: ImportError')
        self.assertTrue(results[1]['content'].startswith('unmatched_header'))
        self.assertLessEqual(len(results[1]['content']), 1200)

    def test_followup_user_information_stays_after_latest_tool_round(self):
        task = self.task()
        task['messages'] = [{'role':'system','content':'system'}, {'role':'user','content':'Original'},
            {'role':'assistant','content':'Lesen'},
            {'role':'tool','name':'read_file','call_id':'r','result':{'content':'Atlas data'}},
            {'role':'user','content':'Nachtrag: verwende Neptune'}]
        messages = self.core.context.provider_messages(task, {'role':'system','content':'context'}, 'Neptune')
        roles = [m['role'] for m in messages if m['role'] != 'system']
        self.assertEqual(roles, ['user','assistant','tool','user'])
        self.assertEqual(messages[-1]['content'], 'Nachtrag: verwende Neptune')

    def test_targeted_file_query_reaches_beyond_normal_output_limit(self):
        for newline in ('\n', '\r\n'):
            with self.subTest(newline=repr(newline)):
                body = ('Gardening.' + newline)*6000 + 'Atlas.API cursor_token selects the nächste page.'
                # Explicit bytes exercise both line endings on every OS. Retrieval
                # preserves them and counts decoded characters, not UTF-8 bytes.
                (self.work/'large.md').write_bytes(body.encode('utf-8'))
                task = self.task()
                result = self.core.tools.execute('read_file', {'path':'large.md','query':'Atlas.API'}, self.core.agent._context(task))
                self.assertIn('cursor_token', result['content'])
                self.assertNotIn('Gardening', result['content'])
                self.assertEqual(result['source_chars'], len(body))

    def test_orphan_in_progress_task_can_be_paused_without_run_loop(self):
        task = self.task()
        self.core.tasks.status(task, 'IN_PROGRESS')
        self.assertEqual(self.core.pause_task(task['id'])['status'], 'PAUSED')
        self.assertFalse(self.core.agent._lock.locked())

    def test_active_run_uses_deferred_pause(self):
        task = self.task()
        self.core.tasks.status(task, 'IN_PROGRESS')
        self.core.agent._lock.acquire()
        try:
            self.assertEqual(self.core.pause_task(task['id'])['status'], 'IN_PROGRESS')
            self.assertIn(task['id'], self.core.agent._pauses)
        finally:
            self.core.agent._lock.release()

    def test_manual_both_valid_resolution_is_not_reopened_by_same_answer(self):
        self.core.add_knowledge('Atlas needs Java 17')
        provider = self.provider(local=False)
        provider.chat = lambda *a, **k: 'Atlas needs Java 21'
        task = self.task('Atlas Java')
        first = self.core.agent._consult(task, 'coding', 'Atlas Java')
        conflict_id = first['verification']['conflict_ids'][0]
        self.core.resolve_conflict(conflict_id, 'both_valid')
        second = self.core.agent._consult(task, 'coding', 'Atlas Java')
        self.assertEqual(second['verification']['status'], 'reviewed_conflict')
        self.assertTrue(second['ok'])
        self.assertFalse(task.get('unresolved_ai_conflict'))
        self.assertEqual(self.core.get_conflicts(), [])

    def test_empty_advisor_answer_is_not_a_successful_result(self):
        provider = self.provider()
        provider.chat = lambda *a, **k: ''
        with self.assertRaises(ProviderError):
            self.core.agent._consult(self.task(), 'coding', 'Atlas')
        self.assertEqual(self.core.list_knowledge(trust='CANDIDATE'), [])

    def test_identical_multi_statement_answer_is_not_compared_against_itself(self):
        body = 'Atlas unterstützt Caching. Atlas unterstützt Caching nicht.'
        original = self.core.add_knowledge(body, project_id=self.project['id'])['entry']
        refs = self.core.context.retrieve_task(self.task('Atlas Caching'), external=True).records
        result = self.core.knowledge.assess_task_answer('Atlas Caching', body, 'fixture', self.project['id'], refs)
        self.assertEqual(result['status'], 'matching_evidence')
        self.assertEqual(result['conflict_ids'], [])
        self.assertEqual(self.core.get_knowledge_entry(original['id'])['trust'], 'CONFIRMED')

    def test_partial_reference_cannot_create_a_self_conflict_blocker(self):
        body = 'Atlas unterstützt Caching. Atlas unterstützt Caching nicht.'
        original = self.core.add_knowledge(body, project_id=self.project['id'])['entry']
        refs = [{'reference':f"knowledge:{original['id']}", 'content':'Atlas unterstützt Caching.', 'version':1}]
        result = self.core.knowledge.assess_task_answer('Atlas Caching', body, 'fixture', self.project['id'], refs)
        self.assertEqual(result['status'], 'unverified')
        self.assertEqual(result['conflict_ids'], [])

    def test_decimal_version_is_not_split_into_a_false_contradiction(self):
        original = self.core.add_knowledge('Atlas requires version 3.12')['entry']
        refs = self.core.context.retrieve_task(self.task('Atlas version'), external=True).records
        result = self.core.knowledge.assess_task_answer('Atlas version', 'Atlas requires version 3.12. Use caching.',
                                                      'fixture', self.project['id'], refs)
        self.assertEqual(result['status'], 'unverified')
        self.assertEqual(result['conflict_ids'], [])
        self.assertEqual(self.core.get_knowledge_entry(original['id'])['trust'], 'CONFIRMED')

    def test_incomplete_ollama_http_response_is_a_normal_provider_error(self):
        import http.client
        from providers.ollama import OllamaProvider
        from providers.base import ProviderError
        provider = OllamaProvider(host='http://127.0.0.1:11434')
        with patch('providers.ollama.urllib.request.build_opener') as factory:
            factory.return_value.open.side_effect = http.client.IncompleteRead(b'partial', 20)
            with self.assertRaises(ProviderError):
                provider._post({'model':'fixture-local'})

    def test_bad_ollama_host_does_not_prevent_other_providers_starting(self):
        from capabilities.registry import build_default_registry
        from config.providers import PROVIDER_CONFIG
        from tests.test_automation import NativeProvider
        gemini = NativeProvider()
        gemini.name = 'gemini'
        with patch('capabilities.registry.ACTIVE_PROVIDERS', ['ollama','gemini']), \
             patch.dict(PROVIDER_CONFIG['ollama'], {'enabled':True}), \
             patch.dict(PROVIDER_CONFIG['gemini'], {'enabled':True}), \
             patch.dict('os.environ', {'OLLAMA_HOST':'https://outside.invalid'}), \
             patch('providers.gemini.GeminiProvider', return_value=gemini):
            registry = build_default_registry()
        self.assertIsNone(registry.get('ollama'))
        self.assertIs(registry.get('gemini'), gemini)
