"""Additive Migration; vorhandenes Wissen bleibt erhalten."""
SCHEMA = '''
CREATE TABLE IF NOT EXISTS tasks (
 id TEXT PRIMARY KEY, data TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS actions (
 id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT REFERENCES tasks(id),
 kind TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_actions_task ON actions(task_id, id);
CREATE TABLE IF NOT EXISTS experiences (
 task_id TEXT PRIMARY KEY REFERENCES tasks(id), goal TEXT NOT NULL,
 project_id INTEGER, workflow_id TEXT, summary TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workflows (
 id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS schedules (
 id TEXT PRIMARY KEY, data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS privacy_rules (path TEXT PRIMARY KEY, level TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS knowledge_privacy (
 entry_id INTEGER PRIMARY KEY REFERENCES knowledge_entries(id) ON DELETE CASCADE,
 level TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS document_origins (
 document_id INTEGER REFERENCES knowledge_documents(id) ON DELETE CASCADE,
 path TEXT NOT NULL, PRIMARY KEY(document_id, path)
);
CREATE TABLE IF NOT EXISTS memory_store (key TEXT PRIMARY KEY, data TEXT NOT NULL);
'''
