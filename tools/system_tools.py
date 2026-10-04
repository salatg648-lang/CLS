"""Small read-only observations; no shell, environment dump or network access."""
import os
import platform
import shutil
from datetime import datetime
from tools.safety import ToolBlocked


def system_info(section, root):
    if section == 'time':
        values = {'local_time': datetime.now().astimezone().isoformat(timespec='seconds')}
    elif section == 'system':
        values = {'system': platform.system(), 'release': platform.release(),
                  'architecture': platform.machine(), 'logical_cpus': os.cpu_count()}
    elif section == 'disk':
        usage = shutil.disk_usage(root)
        values = {'path': str(root), 'total_bytes': usage.total, 'used_bytes': usage.used,
                  'free_bytes': usage.free}
    elif section == 'processes':
        values = {'processes': _processes()}
    else:
        raise ToolBlocked('Unterstützte Systemabfragen: time, system, disk, processes.')
    return {'ok': True, 'verified': True, 'local_only': True, 'details': values}


def _processes():
    # Fixed OS query only; never include command lines, environments or user arguments.
    import csv
    import io
    import subprocess
    # Absolute OS utility paths prevent a workspace/PATH executable from replacing the query.
    command = ([os.path.join(os.environ.get('SystemRoot', r'C:\Windows'), 'System32', 'tasklist.exe'), '/FO', 'CSV', '/NH']
               if os.name == 'nt' else ['/bin/ps', '-A', '-o', 'pid=,comm='])
    try:
        result = subprocess.run(command, capture_output=True, text=True, errors='replace',
                                timeout=5, shell=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ToolBlocked('Prozessliste auf diesem System nicht verfügbar.') from exc
    if result.returncode:
        raise ToolBlocked('Prozessliste konnte nicht gelesen werden.')
    entries = []
    if os.name == 'nt':
        for row in csv.reader(io.StringIO(result.stdout)):
            if len(row) >= 2 and row[1].isdigit():
                entries.append({'pid': int(row[1]), 'name': row[0][:200]})
    else:
        for line in result.stdout.splitlines():
            parts = line.strip().split(None, 1)
            if len(parts) == 2 and parts[0].isdigit():
                entries.append({'pid': int(parts[0]), 'name': parts[1][:200]})
    # Counts are real observations; only the displayed list is bounded.
    return {'items': entries[:100], 'truncated': len(entries) > 100}
