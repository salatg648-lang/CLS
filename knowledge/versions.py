"""Versioning — Wissen wird nie überschrieben, jede Änderung ist eine neue Version."""

from infrastructure.database import Database, now


def record(db: Database, entry_id: int, version: int, title: str, content: str,
           trust: str, changed_by: str = "", note: str = "") -> None:
    db.execute(
        "INSERT INTO knowledge_versions(entry_id, version, title, content, trust, changed_by, "
        "change_note, created_at) VALUES (?,?,?,?,?,?,?,?)",
        (entry_id, version, title, content, trust, changed_by, note, now()),
    )


def list_versions(db: Database, entry_id: int) -> list[dict]:
    """Neueste zuerst."""
    return db.query("SELECT * FROM knowledge_versions WHERE entry_id = ? ORDER BY version DESC",
                    (entry_id,))


def get_version(db: Database, entry_id: int, version: int) -> dict | None:
    return db.query_one("SELECT * FROM knowledge_versions WHERE entry_id = ? AND version = ?",
                        (entry_id, version))
