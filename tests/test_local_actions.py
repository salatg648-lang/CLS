"""Local plans use real workspace files and the existing permission boundary."""
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from tests import test_automation as automation
from tests.test_automation import NativeProvider
from core.planner import local_plan
from core.workflow_engine import WorkflowEngine
from tools.registry import ToolContext
from tools.safety import Safety, ToolBlocked


class LocalActionsTests(unittest.TestCase):
    setUp = automation.AutomationTests.setUp
    tearDown = automation.AutomationTests.tearDown
    approve = automation.AutomationTests.approve

    def run_goal(self, goal, *, approve=False):
        task = self.core.create_task(goal, ai_policy={'mode': 'NEVER'})
        task = self.core.run_task(task['id'])
        while approve and task['status'] == 'NEEDS_CONFIRMATION':
            task = self.approve(task['id'])
        return task

    def test_read_workspace_absolute_and_directory_roles(self):
        (self.work/'note.txt').write_text('HELLO', encoding='utf-8')
        # The source checkout and process cwd are not the selected project workspace.
        for goal in ('Lies note.txt', f'Lies "{self.work / "note.txt"}"',
                     f'Lies note.txt aus "{self.work}"', 'Lies note.txt und sag mir, was darin steht.'):
            with self.subTest(goal=goal):
                task = self.run_goal(goal)
                self.assertEqual(task['status'], 'COMPLETED')
                self.assertIn('HELLO', task['result'])
                self.assertEqual(task['api_calls'], 0)
                self.assertEqual(task['tool_results'][0]['result']['path'], str(self.work/'note.txt'))
                self.assertEqual(self.core.get_task(task['id'])['tool_results'], task['tool_results'])

    def test_windows_path_grammar_is_preserved(self):
        root = r'D:\Desktop\Projekte'
        examples = {
            r'Lies D:\Desktop\Projekte\note.txt': ('read_file', {'path': root+r'\note.txt'}),
            r'Lies note.txt aus D:\Desktop\Projekte': ('read_file', {'path': root+r'\note.txt'}),
            r'Suche in D:\Desktop\Projekte nach note.txt': ('search_files', {'root': root, 'pattern': 'note.txt'}),
            r'Erstelle in D:\Desktop\Projekte test.txt mit TEST': ('write_file', {'path': root+r'\test.txt','content':'TEST'}),
            r'Kopiere note.txt nach D:\Desktop\Projekte\backup.txt': ('copy_file', {'source':'note.txt','target':root+r'\backup.txt'}),
        }
        for goal, (tool, args) in examples.items():
            with self.subTest(goal=goal):
                self.assertEqual(local_plan(goal)['steps'], [{'tool':tool, 'args':args}])

    def test_read_absolute_native_windows_when_available(self):
        if os.name != 'nt':
            self.skipTest('Native Windows filesystem requires Windows; grammar tested on every OS.')
        self.assertEqual(self.run_goal(f'Lies "{self.work / "note.txt"}"')['status'], 'COMPLETED')

    def test_write_then_read_and_edit_are_verified(self):
        task = self.run_goal('Erstelle test_write.txt mit TEST_WRITE und lies die Datei danach wieder aus.', approve=True)
        self.assertEqual(task['status'], 'COMPLETED')
        self.assertEqual((self.work/'test_write.txt').read_text(), 'TEST_WRITE')
        self.assertEqual(task['tool_results'][1]['args']['path'], str(self.work/'test_write.txt'))
        self.assertIn('TEST_WRITE', task['result'])
        (self.work/'note.txt').write_text('AAA')
        task = self.run_goal('Ändere AAA zu BBB in note.txt', approve=True)
        self.assertEqual(task['status'], 'COMPLETED')
        self.assertEqual((self.work/'note.txt').read_text(), 'BBB')
        self.assertTrue(task['tool_results'][0]['result']['verified'])

    def test_arbitrary_names_spaces_and_literal_content(self):
        task = self.run_goal('Erstelle "random document.md" mit "Inhalt mit in nach und lies"', approve=True)
        self.assertEqual(task['status'], 'COMPLETED')
        self.assertEqual((self.work/'random document.md').read_text(), 'Inhalt mit in nach und lies')
        self.assertIn('Inhalt mit in nach und lies', self.run_goal('Lies "random document.md"')['result'])

    def test_search_results_real_empty_and_chained(self):
        (self.work/'sub').mkdir()
        (self.work/'sub'/'other.txt').write_text('FOUND')
        task = self.run_goal('Suche in sub nach other.txt und lies anschließend den Inhalt.')
        self.assertEqual(task['status'], 'COMPLETED')
        self.assertIn('FOUND', task['result'])
        self.assertEqual(task['tool_results'][0]['result']['matches'], [str(Path('sub')/'other.txt')])
        task = self.run_goal('Suche nach missing.txt')
        self.assertEqual(task['tool_results'][0]['result']['matches'], [])
        self.assertIn('Keine passende Datei gefunden', task['result'])
        task = self.run_goal('Suche nach missing.txt und lies die Datei')
        self.assertEqual(task['status'], 'NEEDS_INFORMATION')
        self.assertEqual(len(task['tool_results']), 1)
        (self.work/'sub'/'note.txt').write_text('SECOND')
        task = self.run_goal('Suche note.txt und lies die Datei')
        self.assertEqual(task['status'], 'NEEDS_INFORMATION')
        self.assertEqual(len(task['tool_results']), 1)
        with patch('tools.registry.os.walk', return_value=[(str(self.work), [], ['phantom.txt'])]):
            self.assertEqual(self.core.tools.execute('search_files', {'pattern':'*'}, self.ctx)['matches'], [])

    def test_copy_move_and_verified_real_state(self):
        (self.work/'source.txt').write_bytes(b'\x00binary\xff')
        task = self.run_goal('Kopiere source.txt nach copy.txt', approve=True)
        self.assertEqual(task['status'], 'COMPLETED')
        self.assertEqual((self.work/'source.txt').read_bytes(), (self.work/'copy.txt').read_bytes())
        (self.work/'archive').mkdir()
        task = self.run_goal('Verschiebe source.txt nach archive/moved.txt', approve=True)
        self.assertEqual(task['status'], 'COMPLETED')
        self.assertFalse((self.work/'source.txt').exists())
        self.assertEqual((self.work/'archive'/'moved.txt').read_bytes(), b'\x00binary\xff')

    def test_false_verification_fails_task_and_not_completed(self):
        with patch('tools.registry.write_file', return_value={'ok': True, 'verified': False}):
            task = self.run_goal('Erstelle broken.txt mit HELLO', approve=True)
        self.assertEqual(task['status'], 'FAILED')
        self.assertFalse(task['verified'])
        self.assertFalse(task['tool_results'][0]['result']['ok'])
        # Actual readback failure must propagate, not merely a mocked ok flag.
        with patch('tools.file_tools.os.replace'):
            task = self.run_goal('Erstelle absent.txt mit HELLO', approve=True)
        self.assertNotEqual(task['status'], 'COMPLETED')
        self.assertFalse((self.work/'absent.txt').exists())

    def test_safety_source_target_traversal_absolute_links(self):
        outside = self.root/'outside.txt'
        outside.write_text('PRIVATE')
        for path in (r'..\outside.txt', '../outside.txt', str(outside), r'D:\outside.txt', '.env', 'note.txt:stream'):
            for tool,args in [('read_file', {'path':path}), ('copy_file',{'source':path,'target':'copy.txt'}),
                              ('move_file',{'source':'note.txt','target':path})]:
                with self.subTest(tool=tool,path=path), self.assertRaises(ToolBlocked):
                    self.core.tools.execute(tool,args,self.ctx,True)
        try:
            (self.work/'link').symlink_to(outside)
            os.link(outside,self.work/'hard')
        except OSError:
            return  # Windows without link privilege still exercises traversal above.
        for name in ('link','hard'):
            with self.assertRaises(ToolBlocked):
                self.core.tools.execute('copy_file',{'source':name,'target':'copy.txt'},self.ctx,True)
        self.assertEqual(outside.read_text(),'PRIVATE')

    def test_clipboard_roundtrip_file_transfer_and_external_block(self):
        state = {'text':''}
        def dispatch(op,text):
            if op == 'write': state['text'] = text
            return state['text']
        self.core.tools.clipboard.dispatch = dispatch
        task = self.run_goal('Kopiere "Hallo CLS" in die Zwischenablage.', approve=True)
        self.assertEqual(task['status'],'COMPLETED')
        self.assertEqual(state['text'],'Hallo CLS')
        self.assertIn('Hallo CLS',self.run_goal('Lies meinen Clipboard-Inhalt.')['result'])
        task = self.run_goal('Schreibe meinen Clipboard-Inhalt in clipboard.txt.',approve=True)
        self.assertEqual(task['status'],'COMPLETED')
        self.assertEqual((self.work/'clipboard.txt').read_text(),'Hallo CLS')
        self.assertEqual(self.core.get_path_privacy(self.work/'clipboard.txt'),'LOCAL_ONLY')
        self.assertFalse(self.core.context._experience_safe(task['id'],external=True))
        provider = NativeProvider(); provider.is_local=False
        with self.assertRaises(ToolBlocked): self.core.agent._provider_gate(task,provider)
        task=self.run_goal('Kopiere den Inhalt von note.txt in meine Zwischenablage.',approve=True)
        self.assertEqual(task['status'],'COMPLETED')
        self.assertEqual(state['text'],'Original')
        with self.assertRaises(ToolBlocked):
            self.core.tools.execute('clipboard_read',{},ToolContext(str(self.work),external=True))
        self.core.tools.clipboard.dispatch=lambda op,text:'unverändert'
        self.assertEqual(self.run_goal('Kopiere "Neu" ins Clipboard',approve=True)['status'],'FAILED')

    def test_info_open_and_chat_return_observations(self):
        task=self.run_goal('Existiert note.txt?')
        self.assertEqual(task['status'],'COMPLETED')
        self.assertTrue(task['tool_results'][0]['result']['exists'])
        self.assertFalse(self.run_goal('Existiert absent.txt?')['tool_results'][0]['result']['exists'])
        for goal in ('Zeig mir die Dateien im Projekt.', 'Welche Dateien sind im Projekt?'):
            self.assertIn('note.txt', [e['relative_path'] for e in self.run_goal(goal)['tool_results'][0]['result']['entries']])
        self.assertIn('note.txt', self.run_goal('Wo liegt note.txt?')['tool_results'][0]['result']['matches'])
        with patch('tools.registry.open_path', return_value={'ok':True,'verified':True,'message':'übergeben'}) as launch:
            task=self.run_goal('Öffne den Projektordner.',approve=True)
            self.assertEqual(task['status'],'COMPLETED')
            launch.assert_called_once_with(self.work)
        reply=self.core.chat('Lies note.txt')
        self.assertIn('Original',reply['text'])
        self.assertEqual(reply['provider'],'cls')

    def test_build_detection_real_cwd_exit_and_output(self):
        task=self.run_goal('Build ausführen')
        self.assertNotEqual(task['status'],'COMPLETED')
        self.assertIn('Kein passender',task['blocking']['reason'])
        (self.work/'module.py').write_text('x=1')
        task=self.run_goal('Build ausführen',approve=True)
        self.assertEqual(task['status'],'COMPLETED')
        result=task['tool_results'][0]['result']
        self.assertEqual(result['cwd'],str(self.work))
        self.assertEqual(result['exit_code'],0)
        (self.work/'tests').mkdir()
        (self.work/'tests'/'test_actual.py').write_text('import unittest\nclass T(unittest.TestCase):\n def test_failure(self): self.fail("REAL_FAILURE")\n')
        task=self.run_goal('Tests ausführen',approve=True)
        self.assertNotEqual(task['status'],'COMPLETED')
        self.assertIn('REAL_FAILURE',task['tool_results'][0]['result']['output'])
        self.assertNotEqual(task['tool_results'][0]['result']['exit_code'],0)

    def test_explicit_workspace_and_safe_auto_workspace(self):
        with patch('config.paths.WORKSPACE_BASE',self.root/'workspaces'):
            auto=self.core.create_project('CON',auto_workspace=True)
            self.assertEqual(Path(auto['path']).name,'_CON')
            self.assertTrue(Path(auto['path']).is_dir())
            auto=self.core.create_project('A:B? C.',auto_workspace=True)
            self.assertEqual(Path(auto['path']).name,'A_B_ C')
            explicit=self.core.create_project('Explicit',path=str(self.work),auto_workspace=True)
            self.assertEqual(explicit['path'],str(self.work))
            with self.assertRaises(ValueError): self.core.create_project('Relative',path='relative')
            with self.assertRaises((ValueError, OSError)): self.core.create_project('Missing',path=str(self.root/'missing'),auto_workspace=True)

    def test_missing_arguments_clarify_without_provider(self):
        for goal in ('Bearbeite note.txt','Kopiere note.txt','Schreibe test.txt'):
            task=self.run_goal(goal)
            self.assertEqual(task['status'],'NEEDS_INFORMATION')
            self.assertEqual(task['api_calls'],0)

    def test_saved_workflow_references_and_invalid_refs(self):
        workflow=self.core.save_workflow('Find+read','Find+read',[
            {'tool':'search_files','args':{'pattern':'note.txt'}},
            {'tool':'read_file','args':{'path':{'step':0,'field':'matches'}}}])
        task=self.core.create_task('Find+read',workflow_id=workflow['id'])
        task=self.core.run_task(task['id'])
        self.assertEqual(task['status'],'COMPLETED')
        self.assertIn('Original',task['result'])
        for reference in ({'step':1,'field':'matches'},{'step':-1,'field':'path'}, {'step':True,'field':'path'}):
            with self.assertRaises(ValueError):
                self.core.save_workflow('Bad','Bad',[{'tool':'read_file','args':{'path':reference}}])

    def test_pending_file_target_rechecked_and_privacy_preserved(self):
        task=self.run_goal('Kopiere note.txt nach duplicate.txt')
        self.assertEqual(task['status'],'NEEDS_CONFIRMATION')
        self.core.set_path_privacy(self.work/'note.txt','LOCAL_ONLY')
        task=self.approve(task['id'])
        self.assertEqual(task['status'],'COMPLETED')
        self.assertEqual(self.core.get_path_privacy(self.work/'duplicate.txt'),'LOCAL_ONLY')
        task=self.run_goal('Kopiere note.txt nach occupied.txt')
        (self.work/'occupied.txt').write_text('Existing')
        task=self.approve(task['id'])
        self.assertNotEqual(task['status'],'COMPLETED')
        self.assertEqual((self.work/'occupied.txt').read_text(),'Existing')

    def test_native_summary_cannot_invent_a_search_hit(self):
        from providers.base import ProviderTurn, ToolCall
        provider=NativeProvider([ProviderTurn(calls=[
            ToolCall('p','set_plan',{'steps':['Suchen']}),
            ToolCall('s','search_files',{'pattern':'missing.txt'}),
            ToolCall('f','finish_task',{'summary':'Die Datei liegt unter D:\\invented\\missing.txt'})])])
        self.registry.register(provider)
        task=self.core.create_task('Kontrolliere Dateibestand')
        task=self.core.run_task(task['id'])
        self.assertEqual(task['status'],'COMPLETED')
        self.assertIn('Keine passende Datei gefunden',task['result'])
        self.assertNotIn('invented',task['result'])

    def test_empty_creation_and_clarification_resume(self):
        task=self.run_goal('Erstelle empty.txt',approve=True)
        self.assertEqual(task['status'],'COMPLETED')
        self.assertEqual((self.work/'empty.txt').read_bytes(),b'')
        task=self.run_goal('Bearbeite note.txt')
        task=self.core.run_task(task['id'],information='Ändere Original zu Updated in note.txt')
        self.assertEqual(task['status'],'NEEDS_CONFIRMATION')
        self.assertEqual(self.approve(task['id'])['status'],'COMPLETED')
        self.assertEqual((self.work/'note.txt').read_text(),'Updated')

    def test_command_success_plus_read_is_not_generic_command_verification(self):
        from config.permissions import COMMANDS
        self.core.save_workflow('Command','Command',[
            {'tool':'run_command','args':{'command':'fixture'}},
            {'tool':'read_file','args':{'path':'note.txt'}}])
        with patch.dict(COMMANDS,{'fixture':{'argv':['{python}','-c','print("ran")'],'kind':'test'}}):
            task=self.run_goal('Command',approve=True)
        self.assertNotEqual(task['status'],'COMPLETED')
        self.assertFalse(task['verified'])

    def test_auto_workspace_does_not_create_disallowed_base(self):
        forbidden = self.root / 'not-allowed' / 'base'
        with patch('config.paths.WORKSPACE_BASE', forbidden), patch('config.paths.ALLOWED_ROOTS', [str(self.work)]):
            with self.assertRaises(ValueError):
                self.core.create_project('Blocked automatic project', auto_workspace=True)
        self.assertFalse(forbidden.exists())

    def test_local_chat_without_workspace_never_falls_through_to_ai(self):
        self.core.set_active_project(None)
        with patch.object(self.core.assistant, 'handle_message') as ai:
            for goal in ('Lies note.txt', 'Lies meinen Clipboard-Inhalt'):
                self.assertTrue(self.core.chat(goal)['error'])
            project = self.core.create_project('No workspace')
            self.core.set_active_project(project['id'])
            self.assertTrue(self.core.chat('Erstelle new.txt')['error'])
            ai.assert_not_called()
            self.core.chat('Hallo')
            ai.assert_called_once()

    def test_auto_workspace_cleanup_on_database_failure_preserves_explicit_path(self):
        import sqlite3
        original = self.db.execute
        def execute(sql, *args):
            if sql.startswith('INSERT INTO projects'):
                raise sqlite3.OperationalError('synthetic database failure')
            return original(sql, *args)
        with patch('config.paths.WORKSPACE_BASE', self.root/'auto'), patch.object(self.db, 'execute', side_effect=execute):
            with self.assertRaises(sqlite3.OperationalError):
                self.core.create_project('Failed creation', auto_workspace=True)
            self.assertFalse((self.root/'auto'/'Failed creation').exists())
            with self.assertRaises(sqlite3.OperationalError):
                self.core.create_project('Explicit failure', path=str(self.work), auto_workspace=True)
            self.assertEqual((self.work/'note.txt').read_text(), 'Original')

    def test_move_source_change_removes_only_own_copy(self):
        source, target = self.work/'note.txt', self.work/'moving.txt'
        original = Path.read_bytes
        def read_bytes(path):
            if path == source:
                source.write_bytes(b'changed concurrently')
            return original(path)
        with patch.object(Path, 'read_bytes', read_bytes), self.assertRaises(ToolBlocked):
            self.core.tools.execute('move_file', {'source':'note.txt','target':'moving.txt'}, self.ctx, True)
        self.assertFalse(target.exists())
        self.assertEqual(source.read_bytes(), b'changed concurrently')

    def test_failed_file_action_restores_privacy_only_for_unchanged_target(self):
        source, target = self.work/'note.txt', self.work/'occupied.txt'
        target.write_text('Existing')
        self.core.set_path_privacy(source, 'LOCAL_ONLY')
        self.core.set_path_privacy(target, 'SAFE_FOR_EXTERNAL')
        with self.assertRaises(ToolBlocked):
            self.core.tools.execute('copy_file', {'source':'note.txt','target':'occupied.txt'}, self.ctx, True)
        self.assertEqual(self.core.get_path_privacy(target), 'SAFE_FOR_EXTERNAL')
        local = ToolContext(str(self.work), local_only=True)
        def partial_write(path, content):
            path.write_text(content)
            return {'ok':False, 'verified':False}
        with patch('tools.registry.write_file', side_effect=partial_write):
            result = self.core.tools.execute('write_file', {'path':'partial.txt','content':'local clipboard'}, local, True)
        self.assertFalse(result['ok'])
        self.assertEqual(self.core.get_path_privacy(self.work/'partial.txt'), 'LOCAL_ONLY')

    def test_clarification_binds_missing_arguments_without_repeating_goal(self):
        for goal, information, expected in (
                ('Lies die Datei', 'note.txt', 'Original'),
                ('Kopiere note.txt', 'backup copy.txt', 'Dateizustand'),
                ('Schreibe text.txt', 'hello with spaces', 'geschrieben'),
                ('Ändere Original zu Updated', 'note.txt', 'geschrieben')):
            with self.subTest(goal=goal):
                task = self.run_goal(goal)
                self.assertEqual(task['status'], 'NEEDS_INFORMATION')
                task = self.core.run_task(task['id'], information=information)
                while task['status'] == 'NEEDS_CONFIRMATION':
                    task = self.approve(task['id'])
                self.assertEqual(task['status'], 'COMPLETED')
                self.assertIn(expected, task['result'])
        self.assertEqual((self.work/'backup copy.txt').read_text(), 'Original')
        self.assertEqual((self.work/'text.txt').read_text(), 'hello with spaces')
        task = self.run_goal('Kopiere')
        task = self.core.run_task(task['id'], information='note.txt')
        self.assertEqual(task['status'], 'NEEDS_INFORMATION')
        task = self.core.run_task(task['id'], information='second copy.txt')
        self.assertEqual(task['status'], 'NEEDS_CONFIRMATION')
        self.assertEqual(self.approve(task['id'])['status'], 'COMPLETED')
        self.assertEqual((self.work/'second copy.txt').read_text(), 'Updated')
        task = self.run_goal('Bearbeite note.txt')
        task = self.core.run_task(task['id'], information='irgendwie')
        self.assertEqual(task['status'], 'NEEDS_INFORMATION')
        self.assertIn('vollständigen Auftrag', task['blocking']['reason'])

    def test_desktop_open_errors_are_normal_tool_errors(self):
        import subprocess
        from tools.file_tools import open_path
        for error in (subprocess.TimeoutExpired(['xdg-open'], 10), FileNotFoundError('missing')):
            with self.subTest(error=type(error).__name__), patch('sys.platform', 'linux'), \
                    patch('subprocess.run', side_effect=error), self.assertRaises(ToolBlocked):
                open_path(self.work/'note.txt')

    def test_general_questions_with_punctuation_stay_in_chat(self):
        from core.assistant import Reply
        for goal in ('Was bedeutet Python 3.12?', 'Was ist TCP/IP?', 'Wie funktioniert Python 3.12?'):
            with self.subTest(goal=goal):
                self.assertIsNone(local_plan(goal))
                with patch.object(self.core.assistant, 'handle_message', return_value=Reply('AI response')) as ai:
                    self.assertEqual(self.core.chat(goal)['text'], 'AI response')
                    ai.assert_called_once()
        (self.work/'Makefile').write_text('all:')
        reply = self.core.chat('Wie groß ist Makefile?')
        self.assertFalse(reply['error'])
        self.assertIn('size: 4', reply['text'])
        self.assertEqual(local_plan('Wie groß ist note.txt?')['steps'][0]['tool'], 'file_info')
        self.assertEqual(local_plan('Was ist das für eine Datei "unknown.custom"?')['steps'][0]['tool'], 'file_info')

    def test_clipboard_adapter_rejects_nontext_before_dispatch(self):
        with patch.object(self.core.tools.clipboard, 'dispatch') as dispatch:
            for content in (None, 1, b'bytes', {}, []):
                with self.subTest(content=type(content).__name__), self.assertRaises(ToolBlocked):
                    self.core.tools.clipboard.write(content)
            dispatch.assert_not_called()
