"""Pfadprüfung und Berechtigungen vor jedem Tool-Aufruf."""
import fnmatch
import os
from pathlib import Path, PureWindowsPath

from config.permissions import PERMISSIONS, SENSITIVE_FILES


class ToolBlocked(ValueError):
    pass


class PermissionDenied(ToolBlocked):
    pass


class LimitReached(ToolBlocked):
    pass


class ConfirmationRequired(ValueError):
    pass


def sensitive(path):
    return any(part.lower() in {'.git', '.ssh', '.aws', '.venv', 'venv'}
               or any(fnmatch.fnmatch(part.lower(), pattern.lower())
                      for pattern in [*SENSITIVE_FILES, '.env*', '*.p12', '*.pfx'])
               for part in Path(path).parts)


class Safety:
    def __init__(self, root):
        raw = Path(root).expanduser()
        if not raw.is_absolute():
            raise PermissionDenied('Arbeitsordner muss ein absoluter Projektpfad sein.')
        self.root = raw.resolve(strict=True)
        from config.paths import ALLOWED_ROOTS
        if ALLOWED_ROOTS and not any(self.root.is_relative_to(Path(p).expanduser().resolve()) for p in ALLOWED_ROOTS):
            raise PermissionDenied('Arbeitsordner ist nicht in config/paths.py freigegeben.')
        if not self.root.is_dir() or self.root == Path(self.root.anchor):
            raise PermissionDenied('Ein konkreter Arbeitsordner ist erforderlich.')

    def path(self, value, *, directory=False):
        if not isinstance(value, str) or not value or '\x00' in value:
            raise PermissionDenied('Ungültiger Pfad.')
        # On POSIX, Windows drive/UNC paths must never become filenames under root.
        # On Windows, reject drive-relative paths and alternate data streams too.
        windows = PureWindowsPath(value)
        if windows.is_reserved() or value.startswith(('\\\\?\\', '\\\\.\\')):
            raise PermissionDenied('Gerätepfade sind nicht erlaubt.')
        if (windows.drive and (not windows.is_absolute() or os.name != 'nt')):
            raise PermissionDenied('Windows-Pfad ist auf diesem System nicht eindeutig auflösbar.')
        if any(':' in part for part in windows.parts[1:] if windows.drive) or (not windows.drive and ':' in value):
            raise PermissionDenied('Alternative Datenströme sind nicht erlaubt.')
        raw = Path(value.replace('\\', '/'))
        raw = raw if raw.is_absolute() else self.root / raw
        resolved = raw.resolve()
        if not resolved.is_relative_to(self.root) or sensitive(raw) or sensitive(resolved):
            raise PermissionDenied('Pfad liegt außerhalb des Arbeitsordners oder ist geschützt.')
        # Keine Links: auch Links innerhalb des Projekts sind nicht als Schreibziel erlaubt.
        for part in [raw, *raw.parents]:
            if part == self.root:
                break
            if part.is_symlink() or (hasattr(part, 'is_junction') and part.is_junction()):
                raise PermissionDenied('Symbolische Links sind nicht erlaubt.')
        if resolved.exists() and resolved.is_file() and resolved.stat().st_nlink > 1:
            raise PermissionDenied('Datei mit mehreren Hardlinks ist nicht erlaubt.')
        if directory and not resolved.is_dir():
            raise PermissionDenied('Arbeitsverzeichnis nicht gefunden.')
        return resolved

    def permission(self, permission, approved=False):
        policy = PERMISSIONS.get(permission, 'never')
        if policy == 'never':
            raise PermissionDenied(f'Berechtigung {permission} ist gesperrt.')
        if policy != 'auto' and not approved:
            raise ConfirmationRequired(f'{permission}: Bestätigung für diesen Aufruf erforderlich.')
