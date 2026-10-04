"""Persistente Zustandsmaschine. Bestätigungen sind an genau einen Aufruf gebunden."""
import json
import uuid
from infrastructure.database import now
from config.agent import MAX_STEPS
from tasks.policy import normalize

STATUSES = ('CREATED', 'IN_PROGRESS', 'COMPLETED', 'WAITING_FOR_USER', 'NEEDS_CONFIRMATION',
            'NEEDS_PERMISSION', 'BLOCKED', 'NEEDS_INFORMATION', 'PAUSED', 'FAILED', 'CANCELLED')
TERMINAL = {'COMPLETED', 'FAILED', 'CANCELLED'}


class TaskManager:
    def __init__(self, db, trail):
        self.db, self.trail = db, trail
        # Nach Prozessabbruch niemals eine möglicherweise schon ausgeführte Aktion wiederholen.
        for task in self.list():
            if task['status'] == 'IN_PROGRESS':
                self.block(task, 'BLOCKED', 'Ausführung unterbrochen. Ergebnis vor Fortsetzung prüfen.', 'resume')

    def create(self, goal, project=None, root='', workflow=None, external=False,
               ai_policy=None, policy_area=None, parent_task_id=None):
        goal = goal.strip()
        if not goal or len(goal) > 10000:
            raise ValueError('Ziel fehlt oder ist zu lang.')
        policy = normalize(ai_policy)
        ts = now()
        task = dict(id=uuid.uuid4().hex, goal=goal, project_id=(project or {}).get('id'),
                    project=project, root=root, status='CREATED', plan=[], cursor=0,
                    progress={'percent': 0, 'current_step': '', 'completed_steps': [], 'total_steps': 0},
                    blocking=None, pending=None, messages=[], workflow_id=(workflow or {}).get('id'),
                    workflow=workflow, external=bool(external), ai_providers_used=[], tools_used=[], sources=[],
                    api_calls=0, tool_calls=0, steps=0, cost_reserved=0.0, retries=0,
                    ai_policy=policy, policy_area=policy_area, parent_task_id=parent_task_id,
                    subtask_ids=[], knowledge_used=[], local_assessment=None,
                    tool_results=[], local_only=False, verified=False, dirty=False, result='', created_at=ts, updated_at=ts)
        with self.db.transaction():
            self.save(task)
            self.trail.add(task['id'], 'created', {'goal': goal})
        return task

    def save(self, task):
        task['updated_at'] = now()
        self.db.execute('INSERT INTO tasks(id,data,updated_at) VALUES (?,?,?) '
                        'ON CONFLICT(id) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at',
                        (task['id'], json.dumps(task, ensure_ascii=False), task['updated_at']))

    def get(self, task_id):
        row = self.db.query_one('SELECT data FROM tasks WHERE id=?', (task_id,))
        if not row:
            raise ValueError('Task nicht gefunden.')
        return json.loads(row['data'])

    def list(self):
        return [json.loads(r['data']) for r in self.db.query('SELECT data FROM tasks ORDER BY updated_at DESC')]

    def status(self, task, status):
        if status not in STATUSES:
            raise ValueError('Unbekannter Task-Status.')
        if task['status'] in TERMINAL:
            raise ValueError('Abgeschlossene Tasks können nicht fortgesetzt werden.')
        task['status'], task['blocking'] = status, None
        self.save(task)
        self.trail.add(task['id'], 'status', {'status': status})

    def block(self, task, status, reason, action='provide_information'):
        self.status(task, status)
        task['blocking'] = {'reason': reason, 'detail': reason, 'action_needed': action,
                            'options': ['Bestätigen', 'Ablehnen'] if action == 'confirm' else [action]}
        self.save(task)

    def set_plan(self, task, steps):
        if not steps or len(steps) > MAX_STEPS or any(not isinstance(s, str) or not s.strip() for s in steps):
            raise ValueError('Plan benötigt 1–20 benannte Schritte.')
        task['plan'] = steps
        task['progress']['total_steps'] = len(steps)
        self.save(task)
        self.trail.add(task['id'], 'plan', {'steps': steps})

    def progress(self, task, step):
        p = task['progress']
        p['completed_steps'].append(step)
        p['current_step'] = step
        p['percent'] = min(95, int(100 * len(p['completed_steps']) / max(1, p['total_steps'])))
        self.save(task)
