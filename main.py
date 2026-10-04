"""Start the Electron desktop; --legacy-ui retains the previous Tk entry point."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
 
 
def main():
    parser = argparse.ArgumentParser(description='CLS Desktop')
    parser.add_argument('--legacy-ui', action='store_true', help='Bisherige Tk-Oberfläche starten')
    args = parser.parse_args()
    if args.legacy_ui:
        from desktop.app import CLSDesktopApp
        CLSDesktopApp().run()
        return 0
    shell = Path(__file__).resolve().parent / 'desktop-shell'
    npm = shutil.which('npm.cmd' if os.name == 'nt' else 'npm')
    if not npm or not (shell / 'node_modules').is_dir():
        print('CLS Desktop benötigt Node 24 und einmalig: npm ci --prefix desktop-shell\n'
              'Alternativ den Windows-Installer verwenden. Bisherige UI: python main.py --legacy-ui')
        return 2
    # Fixed npm script; no user-derived shell command.
    return subprocess.call([npm, 'run', 'desktop'], cwd=shell,
                           env={**os.environ, 'CLS_PYTHON': sys.executable})
 
 
if __name__ == '__main__':
    raise SystemExit(main())