"""Desktop transport uses real Core, confirmation tokens and project boundaries."""
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from tests import test_automation as automation
from desktop.bridge import DesktopBridge, METHODS, serve


class DesktopBridgeTests(unittest.TestCase):
    setUp = automation.AutomationTests.setUp
    tearDown = automation.AutomationTests.tearDown

    def test_explicit_api_surface_and_snapshot_does_not_expose_secrets(self):
        bridge = DesktopBridge(self.core)
        for method in ('__getattribute__', 'tools.execute', 'db', 'close', '_scheduled_task', 'eval'):
            with self.subTest(method=method), self.assertRaises(ValueError):
                bridge.dispatch(method, {})
        with self.assertRaises(ValueError):
            bridge.dispatch('snapshot', {'unexpected': True})
        snapshot = bridge.dispatch('snapshot', {})
        self.assertEqual(snapshot['activeProject']['path'], str(self.work))
        self.assertFalse(snapshot['demo'])
        self.assertNotIn('api_key', json.dumps(snapshot))

    def test_real_task_write_requires_exact_confirmation_and_preserves_result(self):
        bridge = DesktopBridge(self.core)
        task = bridge.dispatch('create_task', {'goal': 'Erstelle bridge.txt mit DESKTOP', 'ai_policy': {'mode': 'NEVER'}})
        pending = bridge.dispatch('run_task', {'task_id': task['id']})
        self.assertEqual(pending['status'], 'NEEDS_CONFIRMATION')
        self.assertFalse((self.work / 'bridge.txt').exists())
        with self.assertRaises(ValueError):
            bridge.dispatch('run_task', {'task_id': task['id'], 'approve': True, 'confirmation_id': 'invalid'})
        result = bridge.dispatch('run_task', {'task_id': task['id'], 'approve': True,
                                            'confirmation_id': pending['pending']['confirmation_id']})
        self.assertEqual(result['status'], 'COMPLETED')
        self.assertEqual((self.work/'bridge.txt').read_text(), 'DESKTOP')
        self.assertTrue(result['tool_results'][0]['result']['verified'])
        snapshot = bridge.dispatch('snapshot', {})
        self.assertEqual(snapshot['experiences'][0]['task_id'], task['id'])
        outside = bridge.dispatch('create_task', {'goal': 'Lies ../outside.txt', 'ai_policy': {'mode': 'NEVER'}})
        self.assertEqual(bridge.dispatch('run_task', {'task_id': outside['id']})['status'], 'NEEDS_PERMISSION')

    def test_preview_cannot_enable_providers_or_change_task_policy(self):
        bridge = DesktopBridge(self.core, demo=True)
        for name, params in [('configure_provider', {'name':'ollama','enabled':True}),
                             ('ingest_document', {'path':str(self.work/'note.txt')}),
                             ('update_task_policy', {'task_id':'x','ai_policy':{'mode':'ALLOWED'}})]:
            with self.subTest(method=name), self.assertRaises(ValueError):
                bridge.dispatch(name, params)
        task = bridge.dispatch('create_task', {'goal':'Lies note.txt','ai_policy':{'mode':'ALLOWED'},'allow_external':True})
        self.assertEqual(task['ai_policy']['mode'], 'NEVER')
        self.assertFalse(task['external'])

    def test_transport_rejects_invalid_frames_and_redacts_provider_error(self):
        out = io.StringIO()
        request = io.StringIO('[]\n'+json.dumps({'id':'one','method':'configure_provider','params':{'name':'invalid'}})+'\n')
        with patch.object(self.core,'close'), patch.object(self.core,'configure_provider',side_effect=ValueError('synthetic-secret')):
            serve(self.core, request, out, demo=False)
        messages=[json.loads(line) for line in out.getvalue().splitlines()]
        self.assertEqual(messages[0], {'event':'ready'})
        self.assertNotIn('synthetic-secret', out.getvalue())
        self.assertTrue(any(m.get('id')=='one' and m.get('error') for m in messages))

    def test_data_directory_override_in_fresh_process(self):
        target=self.root/'isolated'
        env={**os.environ,'CLS_DATA_DIR':str(target)}
        result=subprocess.run([sys.executable,'-c','from infrastructure.paths import DATA, DB_FILE; print(DATA); print(DB_FILE)'],
                              env=env,capture_output=True,text=True,check=True)
        self.assertEqual(result.stdout.splitlines(), [str(target),str(target/'cls.db')])
