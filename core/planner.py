"""Native Kontrollfunktionen; niemals Befehle aus Antworttext parsen."""
from tools.registry import declaration, S

CONTROL_SCHEMAS = [
    declaration('set_plan', 'Ziel zuerst in überprüfbare Schritte zerlegen.',
                {'steps': {'type': 'array', 'items': S, 'minItems': 1, 'maxItems': 20}}),
    declaration('finish_task', 'Erst nach erfolgreicher Prüfung abschließen.', {'summary': S}),
    declaration('request_help', 'Fehlende Information oder Hilfe beim Nutzer anfordern.',
                {'reason': S, 'status': {'type': 'string', 'enum': ['WAITING_FOR_USER', 'NEEDS_INFORMATION', 'BLOCKED']}}),
]


def validate_control(name, args):
    schema = next(s for s in CONTROL_SCHEMAS if s['name'] == name)['parameters']
    if not isinstance(args, dict) or set(args) != set(schema['required']):
        raise ValueError('Ungültige Kontrollfunktion.')
    if name == 'set_plan':
        if not isinstance(args['steps'], list) or not 1 <= len(args['steps']) <= 20:
            raise ValueError('Ungültiger Plan.')
        if any(not isinstance(s, str) or not s.strip() or len(s) > 1000 for s in args['steps']):
            raise ValueError('Ungültiger Planschritt.')
    elif any(not isinstance(v, str) or not v.strip() or len(v) > 10000 for v in args.values()):
        raise ValueError('Ungültige Kontrollargumente.')
    if name == 'request_help' and args['status'] not in ('WAITING_FOR_USER', 'NEEDS_INFORMATION', 'BLOCKED'):
        raise ValueError('Ungültiger Hilfe-Status.')


# A small declarative command grammar: verbs select an action, prepositions bind
# roles. It never executes paths or interprets model prose as commands.
import ntpath
import mimetypes
import posixpath
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Word:
    text: str
    quoted: bool = False

    @property
    def key(self):
        return self.text.casefold() if not self.quoted else ''


ACTIONS = {
    'read_file': ('lies', 'lese', 'lesen', 'read'),
    'write_file': ('erstelle', 'erzeuge', 'schreibe', 'create', 'write'),
    'edit_file': ('ändere', 'aendere', 'ersetze', 'bearbeite', 'edit'),
    'search_files': ('suche', 'finde', 'such', 'search', 'zeig', 'zeige', 'welche', 'wo'),
    'copy_file': ('kopiere', 'copy'), 'move_file': ('verschiebe', 'move'),
    'file_info': ('existiert', 'existieren', 'wie', 'was'),
    'open_path': ('öffne', 'oeffne', 'open'),
    'rename_file': ('benenne', 'rename'),
    'delete_file': ('lösche', 'loesche', 'delete'),
    'list_directory': ('liste', 'list'),
    'switch_project': ('wechsle', 'wechsel', 'wechseln'),
    'commands': ('führe', 'starte', 'run', 'tests', 'build'),
}
VERBS = {word: action for action, words in ACTIONS.items() for word in words}
FILLER = set('bitte mir die der das den dem meinen meine meinem mein einer eine einen im inhalt von datei dateien ordner danach anschließend anschliessend wieder aus und sag sage was darin steht ist groß gross für eine liegt sind projekt projektordner workspace arbeitsordner aktuell aktuellen aktuelles befinde mich bin ich welchem befinden auf um ordnerinhalt'.split())
CLIPBOARD = {'clipboard', 'clipboard-inhalt', 'zwischenablage', 'zwischenablageninhalt'}


def _words(text):
    # Only lexical tokenization uses a regex. Backslashes are never shell escapes.
    words = [Word(m[1:-1], True) if m[:1] in ('"', "'") else Word(m.rstrip('?!,;').removesuffix('.') if m not in ('.', '..') else m)
            for m in re.findall(r'"[^"\n]*"|\'[^\'\n]*\'|[^\s]+', text)]
    return [w for w in words if w.text or w.quoted]


def _text(words):
    return ' '.join(w.text for w in words)


def _objects(words):
    return [w.text for w in words if w.quoted or (w.key not in FILLER and w.key not in CLIPBOARD)]


class MissingArgument(ValueError):
    def __init__(self, label, connector=''):
        super().__init__(f'{label} fehlt. Bitte ergänzen oder den vollständigen Auftrag angeben.')
        self.connector = connector


def _one(values, label, connector=''):
    if not values:
        raise MissingArgument(label, connector)
    if len(values) != 1:
        raise ValueError(f'{label} bitte eindeutig angeben; Pfade mit Leerzeichen in Anführungszeichen setzen.')
    return values[0]


def _join(directory, path):
    module = ntpath if ntpath.splitdrive(directory)[0] or '\\' in directory else posixpath
    if ntpath.isabs(path) or posixpath.isabs(path):
        raise ValueError('Absoluten Dateipfad oder Verzeichnis mit Dateiname angeben, nicht beides.')
    return module.join(directory, path)


def _file_reference(word, root):
    if word.key in {'datei', 'dateien', 'ordner', 'projekt', 'projektordner'}:
        return True
    if '://' not in word.text and mimetypes.guess_type(word.text)[0] is not None:
        return True
    if root and word.text:
        from tools.safety import Safety, ToolBlocked
        try:
            return Safety(root).path(word.text).exists()
        except (OSError, ToolBlocked):
            pass
    return False


def local_plan(goal, root=None):
    """Return an ephemeral workflow, a clarification, or None for nonlocal goals.

    Output is data only; Safety and ToolRegistry remain the execution boundary.
    Result references are resolved only against successful preceding steps.
    """
    words = _words(goal)
    while words and words[0].key == 'bitte':
        words.pop(0)
    if words and words[0].key in CLIPBOARD and words[-1].key in VERBS:
        words = [words[-1], *words[:-1]]
    keys = {w.key for w in words}
    # Session context is a single explicit action, never a mid-workflow root change.
    if keys & {'projekt', 'workspace', 'arbeitsordner'}:
        if words and VERBS.get(words[0].key) == 'switch_project':
            values = _objects([w for w in words[1:] if w.key not in {'zu', 'zum', 'ins', 'in'}])
            return {'session_action': 'switch_project', 'name': ' '.join(values)}
        if keys & {'welchem', 'aktuelles', 'aktuellen', 'aktuell'} and keys & {'bin', 'zeige', 'zeig', 'zeige', 'anzeigen', 'welches', 'wo'}:
            return {'session_action': 'project_context'}
    sections = {'uhrzeit': 'time', 'datum': 'time', 'systeminfos': 'system',
                'hardwareinfos': 'system', 'systeminformationen': 'system', 'speicherplatz': 'disk', 'prozesse': 'processes'}
    section = next((sections[w.key] for w in words if w.key in sections), None)
    if section and all(w.key in FILLER | set(sections) | {'zeige', 'zeig', 'wie', 'viel', 'frei', 'uhr', 'spät', 'laufende', 'anzeigen'} for w in words):
        return {'id': None, 'name': 'Systemabfrage', 'steps': [{'tool': 'system_info', 'args': {'section': section}}], 'verification': 'effects'}
    if not words or words[0].key not in VERBS:
        if any(w.key in CLIPBOARD for w in words):
            return {'id': None, 'steps': [], 'error': 'Clipboard-Aktion bitte als Lesen oder Schreiben mit Ziel angeben.'}
        return None
    if words[0].key in ('wie', 'was', 'welche', 'wo') and not any(
            _file_reference(w, root) for w in words[1:]):
        return None
    steps = []
    def emit(tool, **args):
        steps.append({'tool': tool, 'args': args})
    def ref(field='path'):
        if not steps:
            raise MissingArgument('Dateipfad')
        if field == 'path' and steps[-1]['tool'] == 'search_files':
            field = 'matches'
        return {'step': len(steps)-1, 'field': field}
    try:
        clauses, current = [], []
        for i, word in enumerate(words):
            following = i + 1
            while following < len(words) and words[following].key in ('danach', 'anschließend', 'anschliessend'):
                following += 1
            if word.key == 'und' and following < len(words) and words[following].key in VERBS and not (current and VERBS.get(current[0].key) == 'commands' and words[following].key in ('build', 'tests')):
                clauses.append(current)
                current = []
            else:
                current.append(word)
        clauses.append(current)
        for clause in clauses:
            while clause and clause[0].key in ('danach', 'anschließend', 'anschliessend'):
                clause.pop(0)
            action = VERBS[clause[0].key]
            body = clause[1:]
            if action == 'write_file' and any(w.key == 'ordner' for w in body) and clause[0].key in ('erstelle', 'erzeuge', 'create'):
                action = 'create_directory'
            if action == 'search_files' and clause[0].key in ('zeig', 'zeige', 'welche') and any(w.key in ('dateien', 'ordnerinhalt') for w in body):
                action = 'list_directory'
            # An explicit request to report the result is presentation, not a new operation.
            report = next((i for i in range(len(body)-1) if body[i].key == 'und' and body[i+1].key in ('sag', 'sage')), None)
            if report is not None:
                body = body[:report]
            if action == 'commands':
                keys = [w.key for w in clause]
                if any(k not in set(VERBS) | FILLER | {'ausführen', 'ausfuehren', 'build', 'tests'} for k in keys):
                    raise ValueError('Build/Test-Aktion bitte eindeutig angeben; keine freien Shell-Befehle.')
                for name, tool in (('build', 'run_build'), ('tests', 'run_tests')):
                    if name in keys:
                        emit(tool)  # command selection uses workspace evidence at execution time
                if not steps:
                    raise ValueError('Build oder Tests angeben.')
                continue
            # Bind common grammatical roles, independently of action and filename.
            roles, role = {'object': []}, 'object'
            separators = {'in': 'directory', 'ins': 'directory', 'aus': 'directory', 'nach': 'target', 'mit': 'content', 'zu': 'replacement'}
            if action == 'rename_file':
                separators['in'] = 'target'
            for w in body:
                if role == 'content':
                    roles[role].append(w)
                    continue
                if w.key in separators and not (w.key == 'aus' and w is body[-1]):
                    role = separators[w.key]
                    roles.setdefault(role, [])
                else:
                    roles[role].append(w)
            clip = any(w.key in CLIPBOARD for w in body)
            clip_target = any(w.key in CLIPBOARD for w in roles.get('directory', []) + roles.get('target', []))
            if clip:
                if action == 'read_file':
                    emit('clipboard_read')
                elif action in ('copy_file', 'write_file') and clip_target:
                    objects = _objects(roles['object'])
                    if len(roles['object']) == 1 and roles['object'][0].quoted:
                        emit('clipboard_write', content=roles['object'][0].text)
                    else:
                        emit('read_file', path=_one(objects, 'Quelldatei'))
                        emit('clipboard_write', content=ref('content'))
                elif action in ('copy_file', 'write_file'):
                    targets = _objects(roles.get('directory', []) + roles.get('target', []))
                    emit('clipboard_read')
                    emit('write_file', path=_one(targets, 'Zieldatei'), content=ref('content'))
                else:
                    raise ValueError('Clipboard lesen oder mit eindeutigem Ziel schreiben.')
                continue
            objects = _objects(roles['object'])
            directories = _objects(roles.get('directory', []))
            target = _objects(roles.get('target', []))
            if action == 'list_directory':
                emit(action, path=_one(directories or objects, 'Ordner') if directories or objects else '.')
                continue
            if action == 'search_files':
                pattern = _one(target or objects, 'Suchmuster') if target or objects else '*'
                emit(action, pattern=pattern, root=_one(directories, 'Suchverzeichnis') if directories else '.')
                continue
            if action == 'edit_file':
                if not directories and roles['object'] and roles.get('replacement'):
                    raise MissingArgument('Dateipfad', 'in')
                if not directories or not roles['object'] or not roles.get('replacement'):
                    raise ValueError('Änderung als „Ändere ALT zu NEU in DATEI“ angeben.')
                emit(action, path=_one(directories, 'Datei'), old=_text(roles['object']), new=_text(roles['replacement']))
                continue
            if directories:
                # Both "Datei aus Ordner" and "in Ordner Datei" bind the same roles.
                if not objects and len(directories) == 2:
                    directory, path = directories
                else:
                    directory = _one(directories, 'Verzeichnis')
                    path = _one(objects, 'Datei')
                path = _join(directory, path)
            elif objects:
                path = _one(objects, 'Datei')
            elif action in ('file_info', 'open_path') and any(w.key in ('projekt', 'projektordner') for w in body):
                path = '.'
            else:
                path = ref()
            if action == 'write_file':
                if not roles.get('content') and clause[0].key not in ('erstelle', 'erzeuge', 'create'):
                    raise MissingArgument('Dateiinhalt', 'mit')
                emit(action, path=path, content=_text(roles.get('content', [])))
            elif action in ('copy_file', 'move_file', 'rename_file'):
                destination = _one(target or _objects(roles.get('replacement', [])), 'Zielpfad', 'nach')
                if action == 'rename_file' and not ntpath.dirname(destination) and not posixpath.dirname(destination):
                    module = ntpath if '\\' in path else posixpath
                    destination = module.join(module.dirname(path), destination)
                emit(action, source=path, target=destination)
            else:
                emit(action, path=path)
        return {'id': None, 'name': 'Lokale Aktionen', 'steps': steps, 'verification': 'effects'}
    except MissingArgument as exc:
        return {'id': None, 'name': 'Lokale Aktionen', 'steps': [], 'error': str(exc),
                'clarification': {'connector': exc.connector, 'goal': goal}}
    except (ValueError, IndexError) as exc:
        return {'id': None, 'name': 'Lokale Aktionen', 'steps': [], 'error': str(exc)}


def clarify_local_plan(goal, previous, information, root=None):
    """Fill one explicit grammatical role, or accept a complete corrected command."""
    revised = local_plan(information, root)
    if revised and not revised.get('error'):
        return revised
    revised = None
    clarification = previous.get('clarification')
    if clarification:
        words = _words(information)
        value = words[0].text if len(words) == 1 and words[0].quoted else information
        quote = next((q for q in ('"', "'") if q not in value), None)
        if quote and '\n' not in value:
            combined = clarification['goal'] + ' ' + clarification['connector'] + ' ' + quote + value + quote
            revised = local_plan(combined, root)
    else:
        revised = local_plan(goal + ' ' + information, root)
    if revised and (not revised.get('error') or revised.get('clarification')):
        return revised
    return {**previous, 'error': 'Ergänzung ist nicht eindeutig. Bitte den vollständigen Auftrag mit allen Argumenten angeben.'}
