"""Begrenzte UTF-8-Dateioperationen; Pfade kommen aus Safety."""
import os
import tempfile
import stat
from config.agent import MAX_FILE_BYTES
from tools.safety import ToolBlocked


def read_file(path):
    if not path.is_file():
        raise ToolBlocked('Pfad ist keine reguläre Datei.')
    with path.open('rb') as handle:
        content = handle.read(MAX_FILE_BYTES + 1)
    if len(content) > MAX_FILE_BYTES or b'\x00' in content:
        raise ToolBlocked('Datei ist zu groß oder binär.')
    try:
        return content.decode('utf-8')
    except UnicodeDecodeError as exc:
        raise ToolBlocked('Datei ist kein UTF-8-Text.') from exc


def write_file(path, content):
    if path.exists() and not path.is_file():
        raise ToolBlocked('Ziel ist keine reguläre Datei.')
    data = content.encode('utf-8')
    if len(data) > MAX_FILE_BYTES:
        raise ToolBlocked('Inhalt ist zu groß.')
    if not path.parent.is_dir():
        raise ToolBlocked('Zielordner existiert nicht.')
    fd, temp = tempfile.mkstemp(prefix='.cls-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(data)
        if path.exists():
            os.chmod(temp, stat.S_IMODE(path.stat().st_mode))
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    verified = path.is_file() and not path.is_symlink() and path.stat().st_nlink == 1 and path.read_bytes() == data
    return {'ok': verified, 'written': len(data), 'verified': verified, 'path': str(path),
            'message': 'Datei geschrieben und Inhalt zurückgelesen.' if verified else 'Dateiprüfung fehlgeschlagen.'}


def edit_file(path, old, new):
    content = read_file(path)
    if not old or content.count(old) != 1:
        raise ToolBlocked('Der zu ersetzende Text muss genau einmal vorkommen.')
    return write_file(path, content.replace(old, new, 1))


def transfer_file(source, target, *, move=False):
    """Bounded regular-file transfer; callers must check BOTH paths with Safety."""
    if source == target or not source.is_file():
        raise ToolBlocked('Quelle muss eine reguläre Datei mit anderem Ziel sein.')
    if target.exists():
        raise ToolBlocked('Ziel existiert bereits; kein stilles Überschreiben.')
    with source.open('rb') as handle:
        data = handle.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise ToolBlocked('Datei ist zu groß.')
    # Exclusive creation also refuses a target created after preflight.
    with target.open('xb') as handle:
        created = os.fstat(handle.fileno())
        handle.write(data)
    verified = target.is_file() and target.read_bytes() == data
    if move and verified:
        if source.is_symlink() or source.stat().st_nlink > 1 or source.read_bytes() != data:
            try:
                current = target.lstat()
                if (not target.is_symlink() and target.resolve() == target and current.st_nlink == 1
                        and (current.st_dev, current.st_ino) == (created.st_dev, created.st_ino)
                        and target.read_bytes() == data):
                    target.unlink()  # Remove only the unchanged copy made by this call.
            except OSError:
                pass
            raise ToolBlocked('Quelle hat sich während der Übertragung verändert; Move abgebrochen.')
        source.unlink()
    verified = verified and (not source.exists() if move else source.is_file() and source.read_bytes() == data)
    return {'ok': verified, 'verified': verified, 'path': str(target), 'source': str(source),
            'written': len(data), 'message': 'Dateizustand geprüft.' if verified else 'Dateiprüfung fehlgeschlagen.'}


def file_info(path, root):
    exists = path.exists()
    return {'ok': True, 'verified': True, 'path': str(path), 'relative_path': str(path.relative_to(root)),
            'exists': exists, 'kind': 'file' if path.is_file() else 'directory' if path.is_dir() else 'missing',
            'size': path.stat().st_size if path.is_file() else None}


def open_path(path):
    """Dispatch only a checked existing path, never a user-provided shell command."""
    import subprocess
    import sys
    if not path.exists():
        raise ToolBlocked('Pfad existiert nicht.')
    if sys.platform == 'win32':
        os.startfile(str(path))
    else:
        try:
            result = subprocess.run(['open' if sys.platform == 'darwin' else 'xdg-open', str(path)],
                                    capture_output=True, timeout=10, shell=False)
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            raise ToolBlocked('Datei/Ordner konnte nicht an die Desktop-Anwendung übergeben werden.') from exc
        if result.returncode:
            raise ToolBlocked('Datei/Ordner konnte nicht an die Desktop-Anwendung übergeben werden.')
    return {'ok': True, 'verified': True, 'path': str(path),
            'message': 'Öffnungsauftrag an das Betriebssystem übergeben; Anzeige nicht überprüfbar.'}


def create_directory(path):
    path.mkdir()  # No recursive creation or silent adoption of existing directories.
    verified = path.is_dir() and not path.is_symlink()
    return {'ok': verified, 'verified': verified, 'path': str(path),
            'message': 'Ordner erstellt und geprüft.' if verified else 'Ordnerprüfung fehlgeschlagen.'}


def delete_file(path):
    if not path.is_file() or path.is_symlink() or path.stat().st_nlink != 1:
        raise ToolBlocked('Nur eine reguläre Datei ohne Links darf gelöscht werden.')
    path.unlink()
    verified = not os.path.lexists(path)
    return {'ok': verified, 'verified': verified, 'path': str(path), 'exists': not verified,
            'message': 'Datei gelöscht und Abwesenheit geprüft.' if verified else 'Löschprüfung fehlgeschlagen.'}
