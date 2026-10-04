"""Nutzerdefinierte, versionierte Abläufe ohne AI; gleiche Tool-/Safety-Grenzen."""
import json
import uuid
import sqlite3
from config.agent import MAX_TOOL_CALLS


class WorkflowEngine:
    def __init__(self, db, tools):
        self.db, self.tools = db, tools

    def save(self, name, goal, steps, workflow_id=None):
        if not name.strip() or not goal.strip() or not isinstance(steps, list) or not 1 <= len(steps) <= MAX_TOOL_CALLS:
            raise ValueError('Workflow benötigt Name, Ziel und 1–15 Schritte.')
        for index, step in enumerate(steps):
            if not isinstance(step, dict) or set(step) != {'tool', 'args'}:
                raise ValueError('Schritt benötigt tool und args.')
            self.validate_step(step, index)
            if step['tool'] == 'ask_ai':
                raise ValueError('Workflows werden ohne AI ausgeführt.')
        previous = self.get(workflow_id) if workflow_id else None
        workflow = dict(id=workflow_id or uuid.uuid4().hex, name=name.strip(), goal=goal.strip(),
                        steps=steps, verification='effects', version=(previous or {}).get('version', 0) + 1)
        try:
            self.db.execute('INSERT INTO workflows VALUES (?,?,?) ON CONFLICT(id) DO UPDATE '
                            'SET name=excluded.name,data=excluded.data',
                            (workflow['id'], workflow['name'], json.dumps(workflow, ensure_ascii=False)))
        except sqlite3.IntegrityError as exc:
            raise ValueError('Ein Workflow mit diesem Namen existiert bereits.') from exc
        return workflow

    def get(self, workflow_id):
        row = self.db.query_one('SELECT data FROM workflows WHERE id=?', (workflow_id,))
        if not row:
            raise ValueError('Workflow nicht gefunden.')
        return json.loads(row['data'])

    def list(self):
        return [json.loads(r['data']) for r in self.db.query('SELECT data FROM workflows ORDER BY name')]

    def validate_step(self, step, index):
        if not isinstance(step['args'], dict):
            raise ValueError('Workflow-Argumente müssen ein Objekt sein.')
        args = {}
        for key, value in step['args'].items():
            if isinstance(value, dict):
                if (set(value) != {'step', 'field'} or type(value['step']) is not int
                        or not 0 <= value['step'] < index or not isinstance(value['field'], str)):
                    raise ValueError('Ergebnisreferenz benötigt einen vorherigen Schritt und ein Feld.')
                args[key] = ''
            else:
                args[key] = value
        self.tools.validate(step['tool'], args)

    @staticmethod
    def arguments(step, results):
        args = {}
        for key, value in step['args'].items():
            if isinstance(value, dict):
                record = next((r for r in reversed(results) if r.get('step') == value['step']), None)
                if not record or not record['result'].get('ok'):
                    raise ValueError('Vorheriger Schritt hat kein erfolgreiches Ergebnis.')
                result = record['result']
                if result.get('truncated'):
                    raise ValueError('Gekürzte Ergebnisse können nicht vollständig weiterverwendet werden.')
                value = result.get(value['field'])
                if isinstance(value, list):
                    if len(value) != 1:
                        raise ValueError('Suchergebnis ist nicht eindeutig; bitte genau einen Dateipfad angeben.')
                    value = value[0]
                if not isinstance(value, str):
                    raise ValueError('Das referenzierte Ergebnis enthält keinen Text/Pfad.')
            args[key] = value
        return args

    @staticmethod
    def response(results):
        """Deterministic presentation of observations, never model-authored claims."""
        sections = []
        for record in results:
            result = record['result']
            lines = [record['tool'] + (': erfolgreich' if result.get('ok') else ': fehlgeschlagen')]
            if result.get('message'):
                lines.append(result['message'])
            if 'matches' in result:
                lines.append('\n'.join(result['matches']) if result['matches'] else 'Keine passende Datei gefunden.')
            if 'entries' in result:
                lines.extend(f"{e['kind']}: {e['relative_path']}" for e in result['entries'])
                if not result['entries']:
                    lines.append('Keine sichtbaren Einträge.')
            if 'details' in result:
                lines.extend(f'{key}: {value}' for key, value in result['details'].items())
            for key in ('path', 'source', 'root', 'cwd', 'command', 'exit_code', 'exists', 'kind', 'size', 'error'):
                if key in result:
                    lines.append(f'{key}: {result[key]}')
            for key in ('content', 'output', 'answer'):
                if key in result:
                    lines.append(str(result[key]))
            if result.get('truncated'):
                lines.append('[Ausgabe gekürzt]')
            sections.append('\n'.join(lines))
        return '\n\n'.join(sections)
