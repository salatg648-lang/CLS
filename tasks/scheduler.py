"""Persistente Intervalle und Events. Keine nachträglichen Task-Fluten nach Neustart."""
import json
import math
import time
import uuid
from tasks.task_manager import TERMINAL


class Scheduler:
    def __init__(self, db, workflows, create_task):
        self.db, self.workflows, self.create_task = db, workflows, create_task

    def create(self, workflow_id, project_id, *, interval=None, event=None, clock=None):
        self.workflows.get(workflow_id)
        if (interval is None) == (event is None):
            raise ValueError('Genau ein Intervall oder Ereignis angeben.')
        if interval is not None and (isinstance(interval, bool) or not isinstance(interval, (int, float))
                                     or not math.isfinite(interval) or interval < 60):
            raise ValueError('Intervall muss mindestens 60 Sekunden betragen.')
        if event is not None and event not in ('project.activated', 'document.imported', 'task.completed'):
            raise ValueError('Unbekanntes Ereignis.')
        schedule = dict(id=uuid.uuid4().hex, workflow_id=workflow_id, project_id=project_id,
                        interval=interval, event=event, enabled=True, last_task_id=None,
                        next_run=(time.time() if clock is None else clock) + interval if interval else None)
        self._save(schedule)
        return schedule

    def _save(self, schedule):
        self.db.execute('INSERT INTO schedules VALUES (?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data',
                        (schedule['id'], json.dumps(schedule)))

    def list(self):
        return [json.loads(r['data']) for r in self.db.query('SELECT data FROM schedules ORDER BY id')]

    def enable(self, schedule_id, enabled):
        for item in self.list():
            if item['id'] == schedule_id:
                item['enabled'] = bool(enabled)
                if enabled and item['interval']:
                    item['next_run'] = time.time() + item['interval']
                self._save(item)
                return item
        raise ValueError('Zeitplan nicht gefunden.')

    def dispatch(self, *, event=None, project_id=None, origin_schedule=None, clock=None):
        current = time.time() if clock is None else clock
        created = []
        with self.db.transaction():
            for item in self.list():
                if not item['enabled']:
                    continue
                if event is None:
                    due = item['interval'] and current >= item['next_run']
                else:
                    # Keine rekursiven Event-Ketten aus Automationen.
                    due = not origin_schedule and item['event'] == event and item['project_id'] == project_id
                if not due:
                    continue
                if item['last_task_id']:
                    previous = self.db.query_one('SELECT data FROM tasks WHERE id=?', (item['last_task_id'],))
                    if previous and json.loads(previous['data'])['status'] not in TERMINAL:
                        continue
                try:
                    task = self.create_task(item['workflow_id'], item['project_id'], item['id'])
                except (ValueError, OSError):
                    item['enabled'] = False  # gelöschtes/archiviertes Projekt o.ä.
                    self._save(item)
                    continue
                item['last_task_id'] = task['id']
                if item['interval']:
                    item['next_run'] = current + item['interval']
                self._save(item)
                created.append(task)
        return created
