"""
SQLite-Datenbank (Phase 3) — strukturierte Daten: Knowledge, Versionen, Konflikte, Projekte.

- Thread-sicher (Chat läuft im Hintergrund-Thread, die UI im Haupt-Thread): eine Verbindung + RLock.
- Autocommit; für mehrere Schritte `with db.transaction():` (verschachtelbar, Rollback bei Fehler).
- Schema-Versionen über PRAGMA user_version (Migrationen sind idempotent).
- Volltextsuche über FTS5, falls die SQLite-Version es kann; sonst läuft die Suche über einen Fallback.
"""

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from infrastructure.logger import get_logger

logger = get_logger(__name__)


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS app_state (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS projects (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL UNIQUE COLLATE NOCASE,
    description  TEXT NOT NULL DEFAULT '',
    instructions TEXT NOT NULL DEFAULT '',
    path         TEXT NOT NULL DEFAULT '',
    status       TEXT NOT NULL DEFAULT 'active',
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS knowledge_documents (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER REFERENCES projects(id) ON DELETE SET NULL,
    filename    TEXT NOT NULL,
    stored_path TEXT NOT NULL DEFAULT '',
    sha256      TEXT NOT NULL,
    size_bytes  INTEGER NOT NULL DEFAULT 0,
    chunk_count INTEGER NOT NULL DEFAULT 0,
    ingested_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS knowledge_entries (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    title           TEXT NOT NULL DEFAULT '',
    content         TEXT NOT NULL,
    topic           TEXT NOT NULL DEFAULT '',
    tags            TEXT NOT NULL DEFAULT '',
    trust           TEXT NOT NULL,
    kind            TEXT NOT NULL DEFAULT 'fact',
    project_id      INTEGER REFERENCES projects(id) ON DELETE SET NULL,
    document_id     INTEGER REFERENCES knowledge_documents(id) ON DELETE CASCADE,
    current_version INTEGER NOT NULL DEFAULT 1,
    content_hash    TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_entries_hash    ON knowledge_entries(content_hash);
CREATE INDEX IF NOT EXISTS idx_entries_project ON knowledge_entries(project_id);
CREATE INDEX IF NOT EXISTS idx_entries_trust   ON knowledge_entries(trust);
CREATE INDEX IF NOT EXISTS idx_entries_doc     ON knowledge_entries(document_id);

CREATE TABLE IF NOT EXISTS knowledge_versions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id    INTEGER NOT NULL REFERENCES knowledge_entries(id) ON DELETE CASCADE,
    version     INTEGER NOT NULL,
    title       TEXT NOT NULL DEFAULT '',
    content     TEXT NOT NULL,
    trust       TEXT NOT NULL,
    changed_by  TEXT NOT NULL DEFAULT '',
    change_note TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    UNIQUE(entry_id, version)
);

CREATE TABLE IF NOT EXISTS knowledge_sources (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id    INTEGER NOT NULL REFERENCES knowledge_entries(id) ON DELETE CASCADE,
    source_type TEXT NOT NULL,
    name        TEXT NOT NULL DEFAULT '',
    url         TEXT NOT NULL DEFAULT '',
    reference   TEXT NOT NULL DEFAULT '',
    added_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sources_entry ON knowledge_sources(entry_id);

CREATE TABLE IF NOT EXISTS knowledge_conflicts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_a         INTEGER NOT NULL REFERENCES knowledge_entries(id) ON DELETE CASCADE,
    entry_b         INTEGER NOT NULL REFERENCES knowledge_entries(id) ON DELETE CASCADE,
    reason          TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'open',
    resolution      TEXT NOT NULL DEFAULT '',
    trust_a_before  TEXT NOT NULL DEFAULT '',
    trust_b_before  TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL,
    resolved_at     TEXT NOT NULL DEFAULT '',
    UNIQUE(entry_a, entry_b)
);
"""

_SCHEMA_V2_FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
    title, content, topic, tags,
    content='knowledge_entries', content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);
CREATE TRIGGER IF NOT EXISTS knowledge_fts_ai AFTER INSERT ON knowledge_entries BEGIN
    INSERT INTO knowledge_fts(rowid, title, content, topic, tags)
    VALUES (new.id, new.title, new.content, new.topic, new.tags);
END;
CREATE TRIGGER IF NOT EXISTS knowledge_fts_ad AFTER DELETE ON knowledge_entries BEGIN
    INSERT INTO knowledge_fts(knowledge_fts, rowid, title, content, topic, tags)
    VALUES ('delete', old.id, old.title, old.content, old.topic, old.tags);
END;
CREATE TRIGGER IF NOT EXISTS knowledge_fts_au AFTER UPDATE ON knowledge_entries BEGIN
    INSERT INTO knowledge_fts(knowledge_fts, rowid, title, content, topic, tags)
    VALUES ('delete', old.id, old.title, old.content, old.topic, old.tags);
    INSERT INTO knowledge_fts(rowid, title, content, topic, tags)
    VALUES (new.id, new.title, new.content, new.topic, new.tags);
END;
"""


class Database:
    def __init__(self, path: Path | str):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._depth = 0
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        if self.path != ":memory:":
            self._conn.execute("PRAGMA journal_mode = WAL")
        self.fts_available = False
        self._migrate()

    # --- Zugriff ---

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.execute(sql, params)

    def query(self, sql: str, params: tuple = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    def query_one(self, sql: str, params: tuple = ()) -> dict | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    @contextmanager
    def transaction(self):
        """Mehrere Schritte atomar. Verschachtelbar; nur die äußerste Ebene committet."""
        with self._lock:
            outer = self._depth == 0
            if outer:
                self._conn.execute("BEGIN")
            self._depth += 1
            try:
                yield
            except BaseException:
                self._depth -= 1
                if outer:
                    self._conn.execute("ROLLBACK")
                raise
            else:
                self._depth -= 1
                if outer:
                    self._conn.execute("COMMIT")

    def close(self):
        with self._lock:
            self._conn.close()

    # --- Migration ---

    def _migrate(self):
        with self._lock:
            version = self._conn.execute("PRAGMA user_version").fetchone()[0]
            if version < 1:
                self._conn.executescript(_SCHEMA_V1)
                self._conn.execute("PRAGMA user_version = 1")
                logger.info("Datenbank: Schema v1 angelegt")
            self.fts_available = self._ensure_fts()
            from infrastructure.automation_schema import SCHEMA
            self._conn.executescript(SCHEMA)
            columns = {r['name'] for r in self._conn.execute('PRAGMA table_info(knowledge_entries)')}
            if 'strategy' not in columns:
                self._conn.execute("ALTER TABLE knowledge_entries ADD COLUMN strategy TEXT NOT NULL DEFAULT '{}'")
            for name, declaration in [('reference_allowed', 'INTEGER NOT NULL DEFAULT 0'),
                                      ('origin_project_id', 'INTEGER')]:
                if name not in columns:
                    self._conn.execute(f'ALTER TABLE knowledge_entries ADD COLUMN {name} {declaration}')
            project_columns = {r['name'] for r in self._conn.execute('PRAGMA table_info(projects)')}
            if 'memory_mode' not in project_columns:
                self._conn.execute("ALTER TABLE projects ADD COLUMN memory_mode TEXT NOT NULL DEFAULT 'ASK'")
            self._conn.execute("PRAGMA user_version = 5")

    def _ensure_fts(self) -> bool:
        exists = self._conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name = 'knowledge_fts'").fetchone()
        try:
            self._conn.executescript(_SCHEMA_V2_FTS)
        except sqlite3.OperationalError as e:
            logger.warning(f"FTS5 nicht verfügbar ({e}) — Suche nutzt den Fallback.")
            return False
        if not exists:
            self._conn.execute("INSERT INTO knowledge_fts(knowledge_fts) VALUES('rebuild')")
            self._conn.execute("PRAGMA user_version = 2")
            logger.info("Datenbank: Volltextsuche (FTS5) eingerichtet")
        return True

    def rebuild_fts(self):
        if self.fts_available:
            self.execute("INSERT INTO knowledge_fts(knowledge_fts) VALUES('rebuild')")
