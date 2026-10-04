"""
Long-Term Memory — Strukturierte Fakten über Robin.

Zweck: Speichert dauerhafte Fakten über den Nutzer,
strukturiert mit Tags und Kategorien.
Reagiert auf Befehle wie "Merk dir, dass...".

Diese Fakten werden in den System-Prompt injiziert,
damit CLS immer weiß, wer Robin ist und was er macht.

Langfristig (Phase 5+) wird Episodic Memory (memory/episodic.py)
als separate Schicht ergänzt — für Erfahrungen aus Aufgaben.
Hier werden nur persönliche Fakten gespeichert.
"""

from datetime import datetime
from pathlib import Path
from infrastructure.paths import LONGTERM_MEMORY_FILE
from infrastructure.storage import load_json, save_json
from infrastructure.logger import get_logger

logger = get_logger(__name__)


class LongTermMemory:
    def __init__(self, filepath: Path = LONGTERM_MEMORY_FILE, db=None):
        self.db = db
        self.filepath = filepath
        self.facts: list[dict] = []
        self._load()

    def add_fact(self, content: str, tags: list[str] = None,
                 category: str = "general", *, trust="CONFIRMED", privacy="SAFE_FOR_EXTERNAL",
                 provenance=None) -> dict:
        """
        Speichert einen neuen Fakt.

        Args:
            content: Der Fakt, z.B. "Robin entwickelt CLS mit Python"
            tags: z.B. ["projekt", "technologie"]
            category: "personal", "project_decision", "preference", "skill"

        Returns:
            Der gespeicherte Fakt als dict
        """
        from config.permissions import PRIVACY_LEVELS
        if not isinstance(content, str) or not content.strip():
            raise ValueError('Fakt darf nicht leer sein.')
        if trust not in ('CONFIRMED', 'CANDIDATE') or privacy not in PRIVACY_LEVELS:
            raise ValueError('Ungültiger Memory-Trust oder Datenschutz.')
        fact = {
            "id": self._next_id(),
            "content": content.strip(),
            "trust": trust, "privacy": privacy,
            "provenance": provenance or {"source_type": "user", "reference": "explicit_memory"},
            "version": 1, "history": [],
            "tags": tags or [],
            "category": category,
            "created_at": datetime.now().isoformat(),
        }
        self.facts.append(fact)
        self._save()
        logger.info("Persönlicher Fakt %s gespeichert (%s)", fact["id"], trust)
        return fact

    def _next_id(self) -> int:
        """max+1 statt len+1 — sonst gibt es nach dem Löschen doppelte IDs."""
        return max((f["id"] for f in self.facts), default=0) + 1

    def has_fact(self, content: str) -> bool:
        """Gibt es diesen Fakt (ohne Groß/Klein und Randleerzeichen) schon?"""
        norm = content.strip().lower()
        return any(f["content"].strip().lower() == norm for f in self.facts)

    def search(self, query: str) -> list[dict]:
        """Sucht nach Fakten (einfache Textsuche)."""
        query_lower = query.lower()
        return [
            f for f in self.facts
            if query_lower in f["content"].lower()
            or any(query_lower in tag.lower() for tag in f["tags"])
        ]

    def get_by_category(self, category: str) -> list[dict]:
        """Gibt alle Fakten einer Kategorie zurück."""
        return [f for f in self.facts if f["category"] == category]

    def get_all(self) -> list[dict]:
        """Gibt alle Fakten zurück (für den System-Prompt)."""
        return self.facts

    def delete_fact(self, fact_id: int) -> bool:
        """Löscht einen Fakt."""
        before = len(self.facts)
        self.facts = [f for f in self.facts if f["id"] != fact_id]
        if len(self.facts) < before:
            self._save()
            logger.info(f"Fakt {fact_id} gelöscht")
            return True
        return False

    def _save(self):
        if self.db:
            from memory.sqlite_store import save
            save(self.db, 'personal', self.facts)
        else:
            save_json(self.filepath, self.facts)

    def _load(self):
        if self.db:
            from memory.sqlite_store import load_or_migrate
            data = load_or_migrate(self.db, 'personal', self.filepath)
        else:
            data = load_json(self.filepath)
        if isinstance(data, list):
            self.facts = data
            logger.debug(f"Long-Term Memory geladen: {len(self.facts)} Fakten")

    def update_fact(self, fact_id, content):
        if not content.strip():
            raise ValueError('Fakt darf nicht leer sein.')
        for fact in self.facts:
            if fact['id'] == fact_id:
                fact.setdefault('history', []).append({'content': fact['content'],
                    'version': fact.get('version', 1), 'trust': fact.get('trust', 'CONFIRMED')})
                fact['version'] = fact.get('version', 1) + 1
                fact['content'] = content.strip()
                self._save()
                return dict(fact)
        raise ValueError('Fakt nicht gefunden.')


    def usable(self, *, external=False):
        return [dict(f) for f in self.facts if f.get('trust', 'CONFIRMED') == 'CONFIRMED'
                and f.get('privacy', 'SAFE_FOR_EXTERNAL') != 'BLOCKED'
                and (not external or f.get('privacy', 'SAFE_FOR_EXTERNAL') == 'SAFE_FOR_EXTERNAL')]

    def confirm(self, fact_id):
        for fact in self.facts:
            if fact['id'] == fact_id:
                fact['trust'] = 'CONFIRMED'
                fact['confirmed_at'] = datetime.now().isoformat()
                self._save()
                return dict(fact)
        raise ValueError('Fakt nicht gefunden.')

    def set_privacy(self, fact_id, level):
        from config.permissions import PRIVACY_LEVELS
        if level not in PRIVACY_LEVELS:
            raise ValueError('Ungültiger Datenschutz.')
        for fact in self.facts:
            if fact['id'] == fact_id:
                fact['privacy'] = level
                self._save()
                return dict(fact)
        raise ValueError('Fakt nicht gefunden.')
