"""Build on the target OS. Bundles the existing CLS core, not a replacement backend."""
import os
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[2]
subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir',
    '--name', 'cls-core', '--distpath', str(root / 'build'),
    '--workpath', str(root / 'build' / 'pyinstaller-work'),
    '--specpath', str(root / 'build'), '--paths', str(root),
    '--add-data', str(root / 'prompts') + os.pathsep + 'prompts',
    '--collect-submodules', 'providers', '--collect-submodules', 'capabilities',
    '--collect-submodules', 'tools', '--collect-submodules', 'desktop',
    '--exclude-module', 'desktop.app', '--exclude-module', 'desktop.views',
    '--exclude-module', 'desktop.components', '--exclude-module', 'tkinter',
    str(root / 'desktop' / 'bridge_entry.py')], cwd=root, check=True)
