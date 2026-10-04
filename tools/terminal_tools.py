"""Exakte konfigurierte Befehle, ohne Shell, mit Timeout und begrenztem Output.

Dies ist keine OS-Sandbox: Builds und Tests führen Projektcode aus.
"""
import os
import signal
import shutil
import subprocess
import sys
import threading
from config.agent import STEP_TIMEOUT, MAX_OUTPUT_CHARS
from config.permissions import COMMANDS
from tools.safety import ToolBlocked


def command_spec(command, kind=None):
    spec = COMMANDS.get(command)
    if not spec or (kind and spec['kind'] != kind):
        raise ToolBlocked('Befehl ist für dieses Tool nicht freigegeben.')
    interpreter = sys.executable
    if '{python}' in spec['argv'] and getattr(sys, 'frozen', False):
        # A PyInstaller executable is the CLS Core, not a general Python CLI.
        interpreter = shutil.which('python' if os.name == 'nt' else 'python3')
        if not interpreter or os.path.realpath(interpreter) == os.path.realpath(sys.executable):
            raise ToolBlocked('Python-Builds und -Tests benötigen einen installierten Python-Interpreter im PATH.')
    return [interpreter if a == '{python}' else a for a in spec['argv']]


def run_command(command, cwd, kind=None):
    argv = command_spec(command, kind)
    env = {k: os.environ[k] for k in ('PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'LANG') if k in os.environ}
    process = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               start_new_session=os.name != 'nt', shell=False)
    chunks = bytearray()
    truncated = False

    def drain():
        nonlocal truncated
        with process.stdout:
            while block := process.stdout.read(4096):
                room = max(0, MAX_OUTPUT_CHARS - len(chunks))
                chunks.extend(block[:room])
                truncated |= len(block) > room

    def stop():
        try:
            if os.name != 'nt':
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        except ProcessLookupError:
            pass

    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    timed_out = False
    try:
        process.wait(timeout=STEP_TIMEOUT)
    except subprocess.TimeoutExpired:
        timed_out = True
        stop()
        process.wait()
    reader.join(timeout=1)
    if reader.is_alive():
        stop()  # Unterprozesse dürfen keine offenen Pipes/Jobs hinterlassen.
        reader.join(timeout=1)
    return {'ok': process.returncode == 0 and not timed_out, 'exit_code': process.returncode,
            'timed_out': timed_out, 'output': bytes(chunks).decode('utf-8', errors='replace'),
            'truncated': truncated, 'command': command, 'argv': argv, 'cwd': str(cwd),
            'verified': process.returncode == 0 and not timed_out, 'output_streams': 'stdout+stderr'}


def select_command(root, tool, command=None):
    """Only configured commands; automatic choices require workspace evidence."""
    if command:
        return command
    from tools.safety import Safety
    safety = Safety(str(root))
    if tool == 'run_tests' and safety.path('tests').is_dir():
        return 'python_tests'
    if tool == 'run_build':
        # This configured build is Python syntax compilation, not package creation.
        if any(safety.path(name).is_file() for name in ('pyproject.toml', 'setup.py')):
            return 'python_build'
        for path in root.glob('*.py'):
            if safety.path(str(path)).is_file():
                return 'python_build'
    raise ToolBlocked('Kein passender Build-/Test-Befehl erkannt. Konfigurierten Befehl ausdrücklich auswählen.')
