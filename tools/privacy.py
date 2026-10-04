"""Datenschutz gilt unabhängig von Tool-Berechtigungen."""
from pathlib import Path
from config.permissions import PRIVACY_LEVELS
from tools.safety import sensitive, PermissionDenied


class PrivacyPolicy:
    def __init__(self, db):
        self.db = db

    def set(self, path, level):
        if level not in PRIVACY_LEVELS:
            raise ValueError('Unbekannte Datenschutzstufe.')
        self.db.execute('INSERT INTO privacy_rules(path,level) VALUES (?,?) '
                        'ON CONFLICT(path) DO UPDATE SET level=excluded.level',
                        (str(Path(path).expanduser().resolve()), level))

    def level(self, path):
        p = Path(path).resolve()
        if sensitive(p):
            return 'BLOCKED'
        for ancestor in [p, *p.parents]:
            row = self.db.query_one('SELECT level FROM privacy_rules WHERE path=?', (str(ancestor),))
            if row:
                return row['level']
        return 'USER_CONFIRMATION_REQUIRED'

    def check(self, path, *, external=False, consent=False):
        level = self.level(path)
        if level == 'BLOCKED':
            raise PermissionDenied('Datei ist durch die Datenschutzrichtlinie gesperrt.')
        if external and (level == 'LOCAL_ONLY' or
                         (level == 'USER_CONFIRMATION_REQUIRED' and not consent)):
            raise PermissionDenied('Datei darf nicht an einen externen Provider übermittelt werden.')
        return level

    def set_entry(self, entry_id, level):
        if level not in PRIVACY_LEVELS:
            raise ValueError('Unbekannte Datenschutzstufe.')
        if not self.db.query_one('SELECT id FROM knowledge_entries WHERE id=?', (entry_id,)):
            raise ValueError('Wissenseintrag nicht gefunden.')
        self.db.execute('INSERT INTO knowledge_privacy VALUES (?,?) '
                        'ON CONFLICT(entry_id) DO UPDATE SET level=excluded.level', (entry_id, level))

    def entry_level(self, entry_id):
        row = self.db.query_one('SELECT level FROM knowledge_privacy WHERE entry_id=?', (entry_id,))
        return row['level'] if row else 'SAFE_FOR_EXTERNAL'
