"""Einmalige, transaktionale JSON-Migration; Quelldateien bleiben als Backup erhalten."""
import json
from copy import deepcopy
from infrastructure.storage import load_json


def load_or_migrate(db, key, path):
    with db.transaction():
        row = db.query_one('SELECT data FROM memory_store WHERE key=?', (key,))
        if row:
            return json.loads(row['data'])
        data = load_json(path)
        data = data if isinstance(data, list) else []
        save(db, key, data)
        return deepcopy(data)


def save(db, key, data):
    db.execute('INSERT INTO memory_store VALUES (?,?) ON CONFLICT(key) DO UPDATE SET data=excluded.data',
                (key, json.dumps(data, ensure_ascii=False)))
