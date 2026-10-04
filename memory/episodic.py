"""Erfahrung wird aus dem Action Trail erzeugt, nicht aus AI-Behauptungen."""
import json
import hashlib
from infrastructure.database import now


class EpisodicMemory:
    def __init__(self, db, trail):
        self.db, self.trail = db, trail

    def record(self, task):
        actions = list(reversed(self.trail.list(task['id'], limit=5000)))
        summary = {'result': task['result'], 'steps': [a['detail'] for a in actions if a['kind'] == 'tool'],
                   'errors': [a['detail'] for a in actions if a['kind'] == 'error'],
                   'solutions': [a['detail'] for a in actions if a['kind'] == 'replan'],
                   'verified': task['verified'], 'status': task['status']}
        # Reihenfolge und stabile Action-IDs erhalten: ein späterer Reflector darf
        # Fehler und Erfolg nicht aus voneinander getrennten Listen erraten.
        count = self.db.query_one('SELECT COUNT(*) AS n FROM actions WHERE task_id=?', (task['id'],))['n']
        summary.update(schema_version=2, timeline=actions, timeline_complete=count == len(actions),
                       verification={'verified': bool(task['verified']), 'dirty': bool(task.get('dirty', False)),
                                     'checks': list(task.get('checks', []))},
                       provenance={'task_id': task['id'], 'project_id': task['project_id'],
                                   'workflow_id': task['workflow_id'],
                                   'knowledge_used': task.get('knowledge_used', [])})
        self.db.execute('INSERT OR REPLACE INTO experiences VALUES (?,?,?,?,?,?)',
                        (task['id'], task['goal'], task['project_id'], task['workflow_id'],
                         json.dumps(summary, ensure_ascii=False), now()))

    def get(self, task_id):
        row = self.db.query_one('SELECT * FROM experiences WHERE task_id=?', (task_id,))
        return {**row, 'summary': json.loads(row['summary'])} if row else None

    def set_reference_allowed(self, task_id, allowed):
        item = self.get(task_id)
        if not item or not isinstance(allowed, bool):
            raise ValueError('Experience oder Freigabe ungültig.')
        summary = {**item['summary'], 'reference_allowed': allowed}
        self.db.execute('UPDATE experiences SET summary=? WHERE task_id=?',
                        (json.dumps(summary, ensure_ascii=False), task_id))
        return self.get(task_id)

    @staticmethod
    def fingerprint(item):
        """Exakte Episode einschließlich Scope; Wiederaufzeichnung entwertet alte Belege."""
        data = {key: item[key] for key in ('task_id', 'goal', 'project_id', 'workflow_id', 'summary')}
        return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def list(self, query='', project_id=None):
        rows = self.db.query('SELECT * FROM experiences WHERE project_id IS ? ORDER BY created_at DESC',
                             (project_id,))
        return [{**r, 'summary': json.loads(r['summary'])} for r in rows
                if query.casefold() in r['goal'].casefold()]
