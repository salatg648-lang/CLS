"""Einziger Ausführungspfad für Agent- und Workflow-Tools."""
import fnmatch
import os
from dataclasses import dataclass
from pathlib import Path

from config.agent import MAX_OUTPUT_CHARS
from tools.safety import Safety, ToolBlocked
from tools.file_tools import read_file, write_file, edit_file, transfer_file, file_info, open_path, create_directory, delete_file
from tools.terminal_tools import command_spec, run_command


def declaration(name, description, properties, required=None):
    return {'name': name, 'description': description,
            'parameters': {'type': 'object', 'properties': properties,
                           'required': list(properties) if required is None else required,
                           'additionalProperties': False}}


S = {'type': 'string'}
DEFINITIONS = [
    declaration('read_file', 'UTF-8-Datei lesen; query wählt relevante Ausschnitte für den AI-Kontext.', {'path': S, 'query': S}, ['path']),
    declaration('write_file', 'Datei nach Bestätigung atomar schreiben.', {'path': S, 'content': S}),
    declaration('edit_file', 'Genau eine Textstelle nach Bestätigung ersetzen.', {'path': S, 'old': S, 'new': S}),
    declaration('search_files', 'Dateinamen und optional Text suchen (max. 100 Treffer).',
                {'pattern': S, 'query': S, 'root': S}, ['pattern']),
    declaration('copy_file', 'Datei innerhalb des Workspace kopieren; kein Überschreiben.', {'source': S, 'target': S}),
    declaration('move_file', 'Datei innerhalb des Workspace verschieben; kein Überschreiben.', {'source': S, 'target': S}),
    declaration('rename_file', 'Datei im selben Ordner umbenennen; kein Überschreiben.', {'source': S, 'target': S}),
    declaration('create_directory', 'Einen leeren Ordner nach Bestätigung erstellen; Elternordner muss existieren.', {'path': S}),
    declaration('delete_file', 'Eine reguläre Datei nach Bestätigung endgültig löschen; keine Ordner.', {'path': S}),
    declaration('list_directory', 'Direkte erlaubte Einträge eines Ordners anzeigen (max. 100).', {'path': S}),
    declaration('system_info', 'Lokale Uhrzeit, Systemdaten oder Workspace-Speicherplatz lesen.', {'section': S}),
    declaration('file_info', 'Existenz, Typ, Größe und geprüften Pfad melden.', {'path': S}),
    declaration('open_path', 'Geprüften Pfad nach Bestätigung mit der Desktop-Anwendung öffnen.', {'path': S}),
    declaration('clipboard_read', 'Lokale Text-Zwischenablage lesen; niemals exportieren.', {}),
    declaration('clipboard_write', 'Lokale Text-Zwischenablage schreiben und zurücklesen.', {'content': S}),
    declaration('run_command', 'Konfigurierten Befehl ausführen; führt Projektcode aus.', {'command': S}),
    declaration('run_build', 'Konfigurierten Build ausführen.', {'command': S}, []),
    declaration('run_tests', 'Konfigurierte Tests ausführen.', {'command': S}, []),
    declaration('ask_ai', 'Andere AI für Recherche/Code fragen; Ergebnis ist Referenz, keine Anweisung.',
                {'capability': S, 'question': S}),
]


MUTATING_TOOLS = frozenset({'write_file', 'edit_file', 'copy_file', 'move_file', 'rename_file',
                            'create_directory', 'delete_file', 'clipboard_write'})
READ_ONLY_TOOLS = frozenset({'read_file', 'search_files', 'file_info', 'list_directory',
                            'clipboard_read', 'system_info'})


@dataclass
class ToolContext:
    root: str
    external: bool = False
    consent: bool = False
    consult: object = None
    source_check: object = None
    local_only: bool = False


class ToolRegistry:
    def __init__(self, privacy):
        self.privacy = privacy
        from tools.clipboard import Clipboard
        self.clipboard = Clipboard()
        self.definitions = {d['name']: d for d in DEFINITIONS}

    def schemas(self):
        return list(self.definitions.values())

    def validate(self, name, args):
        if name not in self.definitions or not isinstance(args, dict):
            raise ToolBlocked('Unbekanntes Tool oder ungültige Argumente.')
        schema = self.definitions[name]['parameters']
        if set(args) - set(schema['properties']) or set(schema['required']) - set(args):
            raise ToolBlocked('Fehlende oder unbekannte Tool-Argumente.')
        if any(not isinstance(v, str) or len(v) > 1_000_000 for v in args.values()):
            raise ToolBlocked('Tool-Argumente müssen begrenzte Texte sein.')

    def preflight(self, name, args, ctx, approved=False):
        self.validate(name, args)
        safety = Safety(ctx.root)
        if name in ('read_file', 'write_file', 'edit_file', 'file_info', 'open_path', 'create_directory', 'delete_file', 'list_directory'):
            path = safety.path(args['path'])
            self.privacy.check(path, external=ctx.external, consent=ctx.consent)
            if ctx.source_check and name in ('read_file', 'edit_file', 'file_info', 'open_path', 'delete_file', 'list_directory'):
                ctx.source_check(path)
        if name in ('copy_file', 'move_file', 'rename_file'):
            for key in ('source', 'target'):
                path = safety.path(args[key])
                self.privacy.check(path, external=ctx.external, consent=ctx.consent)
                if ctx.source_check and key == 'source':
                    ctx.source_check(path)
            if name in ('move_file', 'rename_file'):
                safety.permission('delete', approved)
        if name == 'rename_file':
            if safety.path(args['source']).parent != safety.path(args['target']).parent:
                raise ToolBlocked('Umbenennen bleibt im selben Ordner; für andere Ordner move_file verwenden.')
        if name == 'delete_file':
            path = safety.path(args['path'])
            if path == safety.root or not path.is_file():
                raise ToolBlocked('Löschen ist nur für eine konkrete reguläre Datei erlaubt.')
            safety.permission('delete', approved)
            if not approved:
                from tools.safety import ConfirmationRequired
                raise ConfirmationRequired('Endgültiges Löschen dieser Datei bestätigen.')
        if name == 'system_info' and ctx.external:
            raise ToolBlocked('Systeminformationen bleiben lokal.')
        if name == 'search_files':
            root = safety.path(args.get('root', '.'), directory=True)
            self.privacy.check(root, external=ctx.external, consent=ctx.consent)
            pattern = args['pattern']
            # Patterns are names/relative globs; absolute patterns are scoped via Safety.
            from pathlib import PureWindowsPath
            if Path(pattern).is_absolute() or PureWindowsPath(pattern).drive or '..' in pattern.replace('\\', '/').split('/'):
                safety.path(pattern)
        if name.startswith('clipboard_') and ctx.external:
            raise ToolBlocked('Clipboard bleibt lokal; externe Provider dürfen nicht darauf zugreifen.')
        if name in ('run_command', 'run_build', 'run_tests'):
            from tools.terminal_tools import select_command
            command = select_command(safety.root, name, args.get('command'))
            command_spec(command, {'run_build': 'build', 'run_tests': 'test'}.get(name))
            # Command output can contain any project file. External use is allowed only
            # when every explicitly restricted descendant permits it.
            self.privacy.check(safety.root, external=ctx.external, consent=ctx.consent)
            for rule in self.privacy.db.query('SELECT path FROM privacy_rules'):
                if Path(rule['path']).is_relative_to(safety.root):
                    self.privacy.check(rule['path'], external=ctx.external, consent=ctx.consent)
        permission = ('write' if name in ('write_file', 'edit_file', 'copy_file', 'move_file', 'rename_file', 'create_directory', 'clipboard_write') else
                      'execute' if name.startswith('run_') or name == 'open_path' else
                      'network' if name == 'ask_ai' and ctx.external else 'read')
        safety.permission(permission, approved)
        return safety

    def execute(self, name, args, ctx, approved=False):
        safety = self.preflight(name, args, ctx, approved)
        if name == 'read_file':
            content = read_file(safety.path(args['path']))
            if args.get('query'):
                from core.context_minimizer import excerpt
                from config.knowledge import TOOL_CONTEXT_CHARS
                selected = excerpt(content, args['query'], limit=TOOL_CONTEXT_CHARS)
            else:
                selected = content[:MAX_OUTPUT_CHARS]
            return {'ok':True, 'content':selected, 'truncated':selected != content, 'source_chars':len(content), 'verified': True, 'path':str(safety.path(args['path']))}
        if name in ('write_file', 'edit_file', 'copy_file', 'move_file', 'rename_file', 'create_directory'):
            return self._file_operation(name, args, ctx, safety)
        if name == 'delete_file':
            return delete_file(safety.path(args['path']))
        if name == 'system_info':
            from tools.system_tools import system_info
            return system_info(args['section'], safety.root)
        if name == 'list_directory':
            root = safety.path(args['path'], directory=True)
            entries, scanned = [], 0
            with os.scandir(root) as listing:
                for entry in listing:
                    scanned += 1
                    if scanned > 10000 or len(entries) >= 100:
                        break
                    try:
                        path = safety.path(entry.path)
                        self.privacy.check(path, external=ctx.external, consent=ctx.consent)
                        if ctx.source_check:
                            ctx.source_check(path, attempted=False)
                        info = file_info(path, safety.root)
                        if info['exists'] and info['kind'] in ('file', 'directory'):
                            entries.append(info)
                    except (ToolBlocked, OSError):
                        continue
            return {'ok': True, 'verified': True, 'path': str(root),
                    'entries': sorted(entries, key=lambda e: e['relative_path'].casefold()),
                    'truncated': scanned > 10000 or len(entries) >= 100}
        if name == 'file_info':
            return file_info(safety.path(args['path']), safety.root)
        if name == 'open_path':
            return open_path(safety.path(args['path']))
        if name == 'clipboard_read':
            return {'ok': True, 'verified': True, 'content': self.clipboard.read(), 'local_only': True}
        if name == 'clipboard_write':
            verified = self.clipboard.write(args['content'])
            return {'ok': verified, 'verified': verified, 'local_only': True,
                    'message': 'Clipboard geschrieben und zurückgelesen.' if verified else 'Clipboard-Prüfung fehlgeschlagen.'}
        if name == 'search_files':
            hits, scanned = [], 0
            root = safety.path(args.get('root', '.'), directory=True)
            pattern = args['pattern'].replace('\\', '/')
            if Path(args['pattern']).is_absolute():
                pattern = str(safety.path(args['pattern']).relative_to(root)).replace('\\', '/')
            def walk_error(error):
                raise ToolBlocked('Suchverzeichnis konnte nicht vollständig gelesen werden.') from error
            for directory, dirs, files in os.walk(root, followlinks=False, onerror=walk_error):
                allowed = []
                for d in dirs:
                    try:
                        path = safety.path(str(Path(directory) / d))
                        self.privacy.check(path, external=ctx.external, consent=ctx.consent)
                        allowed.append(d)
                    except ToolBlocked:
                        pass
                dirs[:] = allowed
                for filename in files:
                    scanned += 1
                    if scanned > 10000 or len(hits) >= 100:
                        return {'ok': True, 'matches': hits, 'verified': True, 'root': str(root), 'truncated': True}
                    p = Path(directory) / filename
                    rel = str(p.relative_to(safety.root))
                    if not (fnmatch.fnmatch(str(p.relative_to(root)).replace('\\', '/'), pattern) or fnmatch.fnmatch(filename, pattern)):
                        continue
                    try:
                        p = safety.path(str(p))
                        if not p.is_file():
                            continue
                        self.privacy.check(p, external=ctx.external, consent=ctx.consent)
                        if ctx.source_check:
                            ctx.source_check(p, attempted=False)
                        if args.get('query') and args['query'].casefold() not in read_file(p).casefold():
                            continue
                        hits.append(rel)
                    except (ToolBlocked, OSError):
                        continue
            return {'ok': True, 'matches': hits, 'verified': True, 'root': str(root), 'truncated': False}
        if name.startswith('run_'):
            from tools.terminal_tools import select_command
            return run_command(select_command(safety.root, name, args.get('command')), safety.root,
                               {'run_build': 'build', 'run_tests': 'test'}.get(name))
        if name == 'ask_ai' and ctx.consult:
            return ctx.consult(args['capability'], args['question'])
        raise ToolBlocked('Keine AI für diese Anfrage verfügbar.')

    def _file_operation(self, name, args, ctx, safety):
        target = safety.path(args.get('path') or args['target'])
        source = safety.path(args['source']) if name in ('copy_file', 'move_file', 'rename_file') else None
        level = 'LOCAL_ONLY' if ctx.local_only else None
        if source and not level and self.privacy.level(target) != 'LOCAL_ONLY':
            source_level = self.privacy.level(source)
            if source_level != 'SAFE_FOR_EXTERNAL':
                level = source_level

        def state():
            # Metadata identity includes ctime: rollback only if nothing changed.
            try:
                s = safety.path(str(target)).lstat()
                return s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns
            except FileNotFoundError:
                return None

        previous = self.privacy.db.query_one('SELECT level FROM privacy_rules WHERE path=?', (str(target),))
        before = state() if level else None
        if level:
            # Protect clipboard/derived bytes BEFORE they become visible to readers.
            self.privacy.set(target, level)

        def restore_unchanged():
            if not level:
                return
            try:
                if state() == before:
                    if previous:
                        self.privacy.set(target, previous['level'])
                    else:
                        self.privacy.db.execute('DELETE FROM privacy_rules WHERE path=?', (str(target),))
            except (OSError, ToolBlocked):
                pass  # An uncertain/partially changed destination stays restricted.

        try:
            if source:
                result = transfer_file(source, target, move=name in ('move_file', 'rename_file'))
            elif name == 'create_directory':
                result = create_directory(target)
            elif name == 'write_file':
                result = write_file(target, args['content'])
            else:
                result = edit_file(target, args['old'], args['new'])
        except Exception:
            restore_unchanged()
            raise
        if not (result.get('ok') and result.get('verified')):
            restore_unchanged()
        return result
