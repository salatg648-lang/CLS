"""Dauerhafter Action Trail als gemeinsame Quelle für UI und Erfahrung."""
import json
from infrastructure.database import now
from infrastructure.logger import get_logger

logger = get_logger(__name__)


class ActionTrail:
    def __init__(self, db):
        self.db = db

    def add(self, task_id, kind, detail):
        self.db.execute('INSERT INTO actions(task_id,kind,detail,created_at) VALUES (?,?,?,?)',
                        (task_id, kind, json.dumps(detail, ensure_ascii=False), now()))
        # Keine Dateiinhalte, Argumente oder Provider-Antworten in technischen Logs.
        logger.info('Task %s: %s', task_id, kind)

    def list(self, task_id=None, kind=None, limit=200):
        clauses, args = [], []
        for field, value in [('task_id', task_id), ('kind', kind)]:
            if value is not None:
                clauses.append(f'{field}=?')
                args.append(value)
        sql = 'SELECT * FROM actions' + (' WHERE ' + ' AND '.join(clauses) if clauses else '')
        rows = self.db.query(sql + ' ORDER BY id DESC LIMIT ?', (*args, max(1, min(int(limit), 5000))))
        return [{**r, 'detail': json.loads(r['detail'])} for r in rows]
