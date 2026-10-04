"""
Project Manager (Phase 3) — Projekt-Kontexte.

Ein Projekt hat Name, Beschreibung, eigene Anweisungen für die AI und optional einen
absoluten Arbeitsordner als feste Grenze für Tasks und Tools.
Ein Projekt kann "aktiv" sein: dann fließen sein Kontext und sein Wissen in jede Anfrage.
Wissen ohne Projekt ist global und gilt überall.
"""

from infrastructure.database import Database, now
import json
from pathlib import Path
from tools.safety import Safety
from infrastructure.logger import get_logger

logger = get_logger(__name__)

_ACTIVE_KEY = "active_project_id"
_FIELDS = ("name", "description", "instructions", "path")


def _clean_name(name: str) -> str:
    name = " ".join((name or "").split())
    if not name:
        raise ValueError("Der Projektname darf nicht leer sein.")
    if len(name) > 80:
        raise ValueError("Der Projektname ist zu lang (max. 80 Zeichen).")
    return name


class ProjectManager:
    def __init__(self, db: Database):
        self.db = db

    @staticmethod
    def _workspace(path, name='', auto=False):
        if path.strip():
            # Resolve once at configuration time; never reinterpret relative to main.py.
            raw = Path(path.strip()).expanduser()
            if not raw.is_absolute():
                raise ValueError('Bitte einen absoluten Projekt-Arbeitsordner angeben.')
            return str(Safety(str(raw)).root)
        if not auto:
            return ''
        from config.paths import WORKSPACE_BASE, ALLOWED_ROOTS
        base = Path(WORKSPACE_BASE).expanduser()
        if not base.is_absolute():
            raise ValueError('Workspace-Basis muss absolut sein.')
        resolved_base = base.resolve()
        if ALLOWED_ROOTS and not any(resolved_base.is_relative_to(Path(p).expanduser().resolve()) for p in ALLOWED_ROOTS):
            raise ValueError('Workspace-Basis liegt außerhalb der freigegebenen Ordner.')
        base.mkdir(parents=True, exist_ok=True)
        safe = ''.join('_' if ord(c) < 32 or c in '<>:"/\\|?*' else c for c in name).strip(' .')
        if not safe:
            raise ValueError('Projektname ergibt keinen gültigen Ordnernamen.')
        if safe.split('.')[0].upper() in {'CON','PRN','AUX','NUL', *(f'COM{i}' for i in range(1,10)), *(f'LPT{i}' for i in range(1,10))}:
            safe = '_' + safe
        target = Safety(str(base)).path(safe)
        # Never attach an existing workspace silently after name sanitization.
        target.mkdir(exist_ok=False)
        return str(target)

    # --- CRUD ---

    def create(self, name: str, description: str = "", instructions: str = "", path: str = "", *, auto_workspace=False) -> dict:
        name = _clean_name(name)
        if self.get_by_name(name):
            raise ValueError(f"Ein Projekt mit dem Namen '{name}' gibt es schon.")
        created_workspace = auto_workspace and not path.strip()
        path = self._workspace(path, name, auto_workspace)
        ts = now()
        try:
            cur = self.db.execute(
                "INSERT INTO projects(name, description, instructions, path, status, created_at, updated_at) "
                "VALUES (?,?,?,?, 'active', ?, ?)",
                (name, description.strip(), instructions.strip(), path.strip(), ts, ts))
        except Exception:
            if created_workspace:
                try:
                    Path(path).rmdir()  # Only our newly created, still empty directory.
                except OSError:
                    pass  # Preserve files added meanwhile and the original DB error.
            raise
        logger.info(f"Projekt angelegt: {name}")
        return self.get(cur.lastrowid)

    def get(self, project_id: int) -> dict | None:
        row = self.db.query_one("SELECT * FROM projects WHERE id = ?", (project_id,))
        return self._with_counts(row) if row else None

    def get_by_name(self, name: str) -> dict | None:
        return self.db.query_one("SELECT * FROM projects WHERE name = ?", (" ".join(name.split()),))

    def list(self, include_archived: bool = False) -> list[dict]:
        sql = "SELECT * FROM projects"
        if not include_archived:
            sql += " WHERE status = 'active'"
        rows = self.db.query(sql + " ORDER BY name COLLATE NOCASE")
        return [self._with_counts(r) for r in rows]

    def update(self, project_id: int, **fields) -> dict:
        project = self.get(project_id)
        if not project:
            raise ValueError("Projekt nicht gefunden.")
        unknown = set(fields) - set(_FIELDS)
        if unknown:
            raise ValueError(f"Unbekannte Felder: {', '.join(sorted(unknown))}")
        values = {k: (v or "").strip() for k, v in fields.items()}
        if "name" in values:
            values["name"] = _clean_name(values["name"])
            other = self.get_by_name(values["name"])
            if other and other["id"] != project_id:
                raise ValueError(f"Ein Projekt mit dem Namen '{values['name']}' gibt es schon.")
        if 'path' in values:
            values['path'] = self._workspace(values['path'])
        if values:
            sets = ", ".join(f"{k} = ?" for k in values)
            self.db.execute(f"UPDATE projects SET {sets}, updated_at = ? WHERE id = ?",
                            (*values.values(), now(), project_id))
        return self.get(project_id)

    def archive(self, project_id: int) -> dict:
        if not self.get(project_id):
            raise ValueError("Projekt nicht gefunden.")
        self.db.execute("UPDATE projects SET status='archived', updated_at=? WHERE id=?", (now(), project_id))
        if self._active_id() == project_id:
            self.set_active(None)
        return self.get(project_id)

    def unarchive(self, project_id: int) -> dict:
        if not self.get(project_id):
            raise ValueError("Projekt nicht gefunden.")
        self.db.execute("UPDATE projects SET status='active', updated_at=? WHERE id=?", (now(), project_id))
        return self.get(project_id)

    def delete(self, project_id: int, delete_knowledge: bool = False) -> bool:
        """Löscht das Projekt. Erhaltenes Wissen wird stillgelegt, niemals global gültig."""
        if not self.get(project_id):
            return False
        with self.db.transaction():
            if delete_knowledge:
                self.db.execute("DELETE FROM knowledge_entries WHERE project_id = ?", (project_id,))
            else:
                self.db.execute("UPDATE knowledge_entries SET origin_project_id=project_id, trust='OUTDATED', "
                                "reference_allowed=0, updated_at=? WHERE project_id=?", (now(), project_id))
                # Die FK wird NULL; der ursprüngliche Strategiescope bleibt in den
                # Metadaten erhalten und der Kandidat wird dauerhaft stillgelegt.
                for entry in self.db.query("SELECT id, strategy FROM knowledge_entries WHERE project_id=? AND kind='strategy'",
                                           (project_id,)):
                    strategy = json.loads(entry['strategy'])
                    strategy['status'] = 'RETIRED'
                    self.db.execute("UPDATE knowledge_entries SET trust='OUTDATED', strategy=?, updated_at=? WHERE id=?",
                                    (json.dumps(strategy, ensure_ascii=False), now(), entry['id']))
            if self._active_id() == project_id:
                self.set_active(None)
            self.db.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        logger.info(f"Projekt {project_id} gelöscht (Wissen {'gelöscht' if delete_knowledge else 'behalten'})")
        return True

    def set_memory_mode(self, project_id, mode):
        if not self.get(project_id) or mode not in ('NEVER', 'ASK', 'AUTO'):
            raise ValueError('Projekt oder Speichermodus ungültig.')
        self.db.execute('UPDATE projects SET memory_mode=?, updated_at=? WHERE id=?', (mode, now(), project_id))
        return self.get(project_id)

    def relevant(self, query, *, exclude_id=None, limit=5):
        """Nur Metadaten und explizit freigegebene Belege durchsuchen; keine Dateikopien."""
        from knowledge.models import query_tokens
        tokens = set(query_tokens(query))
        ranked = []
        for project in self.list(include_archived=True):
            if project['id'] == exclude_id:
                continue
            texts = [project['name'], project['description']]
            texts.extend(r['content'] for r in self.db.query(
                "SELECT content FROM knowledge_entries WHERE project_id=? AND reference_allowed=1 "
                "AND kind!='strategy' AND trust IN ('CONFIRMED','SUPPORTED')", (project['id'],)))
            for row in self.db.query('SELECT goal,summary FROM experiences WHERE project_id=?', (project['id'],)):
                if json.loads(row['summary']).get('reference_allowed'):
                    texts.append(row['goal'])
            score = len(tokens & set(query_tokens(' '.join(texts))))
            if score:
                ranked.append((score, project))
        ranked.sort(key=lambda item: (-item[0], item[1]['id']))
        return [p for _, p in ranked[:limit]]

    # --- aktives Projekt ---

    def set_active(self, project_id: int | None) -> dict | None:
        if project_id is None:
            self.db.execute("DELETE FROM app_state WHERE key = ?", (_ACTIVE_KEY,))
            return None
        project = self.get(project_id)
        if not project:
            raise ValueError("Projekt nicht gefunden.")
        if project["status"] != "active":
            raise ValueError("Archivierte Projekte können nicht aktiv sein.")
        self.db.execute("INSERT INTO app_state(key, value) VALUES (?, ?) "
                        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                        (_ACTIVE_KEY, str(project_id)))
        logger.info(f"Aktives Projekt: {project['name']}")
        return project

    def get_active(self) -> dict | None:
        pid = self._active_id()
        project = self.get(pid) if pid else None
        return project if project and project["status"] == "active" else None

    # --- intern ---

    def _active_id(self) -> int | None:
        row = self.db.query_one("SELECT value FROM app_state WHERE key = ?", (_ACTIVE_KEY,))
        try:
            return int(row["value"]) if row else None
        except (TypeError, ValueError):
            return None

    def _with_counts(self, row: dict) -> dict:
        p = dict(row)
        p["knowledge_count"] = self.db.query_one(
            "SELECT COUNT(*) AS n FROM knowledge_entries WHERE project_id = ?", (p["id"],))["n"]
        p["is_active"] = self._active_id() == p["id"]
        return p
