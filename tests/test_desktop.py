"""The launcher uses a fixed desktop command and preserves the Python environment."""
import unittest
from unittest.mock import patch
from pathlib import Path
import sys
import main


class DesktopLauncherTests(unittest.TestCase):
    def test_desktop_command_and_python_are_bound_to_repository(self):
        with patch.object(sys, 'argv', ['main.py']), patch('main.shutil.which', return_value='/bin/npm'), patch.object(Path, 'is_dir', return_value=True), patch('main.subprocess.call', return_value=0) as run:
            self.assertEqual(main.main(), 0)
        args, kwargs = run.call_args
        self.assertEqual(args[0], ['/bin/npm', 'run', 'desktop'])
        self.assertEqual(kwargs['cwd'], Path(main.__file__).resolve().parent / 'desktop-shell')
        self.assertEqual(kwargs['env']['CLS_PYTHON'], sys.executable)
        self.assertNotIn('shell', kwargs)

    def test_missing_dependencies_fail_with_actionable_message(self):
        with patch.object(sys, 'argv', ['main.py']), patch('main.shutil.which', return_value=None), patch('main.subprocess.call') as run, patch('builtins.print') as message:
            self.assertEqual(main.main(), 2)
        run.assert_not_called()
        self.assertIn('npm ci --prefix desktop-shell', message.call_args.args[0])

    def test_packaged_core_uses_external_python_for_project_commands(self):
        from tools.terminal_tools import command_spec
        from tools.safety import ToolBlocked
        with patch('sys.frozen', True, create=True), patch('tools.terminal_tools.shutil.which', return_value='/usr/bin/project-python'):
            argv = command_spec('python_tests', 'test')
            self.assertEqual(argv[0], '/usr/bin/project-python')
            self.assertEqual(argv[1:4], ['-m', 'unittest', 'discover'])
        with patch('sys.frozen', True, create=True), patch('tools.terminal_tools.shutil.which', return_value=None):
            with self.assertRaisesRegex(ToolBlocked, 'Python-Interpreter'):
                command_spec('python_tests', 'test')
        with patch('sys.frozen', True, create=True), patch('tools.terminal_tools.shutil.which', return_value=sys.executable):
            with self.assertRaises(ToolBlocked):
                command_spec('python_build', 'build')
