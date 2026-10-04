"""
Trust-Levels und Verification.

CONFIRMED    vom Nutzer bestätigt (oder vom Nutzer selbst eingegeben)
SUPPORTED    aus einem Dokument/System oder von mehreren Seiten gestützt
UNCERTAIN    unsicher, nur mit Vorbehalt nutzen
CONFLICTING  widerspricht einem anderen Eintrag (wird automatisch gesetzt)
OUTDATED     überholt, wird nicht mehr als Wissen genutzt
CANDIDATE    ungeprüft (z.B. AI-Antwort) — nie automatisch Wissen

Auto-Upgrade CANDIDATE → SUPPORTED: nur wenn mindestens zwei *unabhängige* Quellen
den Eintrag stützen (verschiedene Provider/Dokumente/Nutzer). Web-Links, die eine
AI-Antwort nennt, zählen nicht: sie zeigen die Herkunft, sie belegen nichts.
"""

from config.knowledge import DEFAULT_TRUST_BY_SOURCE, TRUST_LABELS, TRUST_LEVELS
from infrastructure.database import Database, now


def validate(trust: str) -> str:
    if trust not in TRUST_LEVELS:
        raise ValueError(f"Unbekanntes Trust-Level: {trust}")
    return trust


def label(trust: str) -> str:
    return TRUST_LABELS.get(trust, trust)


def initial_trust(source_type: str) -> str:
    return DEFAULT_TRUST_BY_SOURCE.get(source_type, "CANDIDATE")


def corroborating_sources(sources: list[dict]) -> set[tuple[str, str]]:
    return {(s["source_type"], (s.get("name") or "").lower())
            for s in sources if s["source_type"] not in ("web", "experience")}


def evaluate(current: str, sources: list[dict]) -> str:
    """Neues Trust-Level nach Quellenlage. Ändert nur CANDIDATE → SUPPORTED."""
    if current == "CANDIDATE" and len(corroborating_sources(sources)) >= 2:
        return "SUPPORTED"
    return current


def apply_trust(db: Database, entry_id: int, trust: str) -> None:
    validate(trust)
    db.execute("UPDATE knowledge_entries SET trust = ?, updated_at = ? WHERE id = ?",
               (trust, now(), entry_id))
