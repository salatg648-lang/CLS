"""
Conflict Detection — widersprüchliches Wissen wird erkannt und ERHALTEN, nie still überschrieben.

Erkennung ohne AI, bewusst einfach (Hinweise, keine Wahrheit):
  - Zwei kurze Einträge handeln vom selben Thema (hohe Wort-Überlappung), aber
    (a) nennen unterschiedliche Zahlen/Versionen, oder
    (b) einer verneint, der andere bestätigt.
Dokument-Chunks und lange Texte werden nicht geprüft (zu ungenau).

Ablauf: Beide Einträge werden CONFLICTING (ist einer CONFIRMED, bleibt er es — nur der andere
wird markiert). Der Nutzer löst den Widerspruch: keep_a / keep_b / both_valid.
"""

from config.knowledge import CONFLICT_CANDIDATES_LIMIT, CONFLICT_MAX_CHARS, CONFLICT_MIN_SIMILARITY
from infrastructure.database import Database, now
from infrastructure.logger import get_logger
from knowledge import trust as trust_mod
from knowledge.models import NEGATIONS, numbers, sig_words, words
from knowledge.search import KnowledgeSearch

logger = get_logger(__name__)

RESOLUTIONS = ("keep_a", "keep_b", "both_valid")


def compare_texts(a: str, b: str, min_similarity: float = CONFLICT_MIN_SIMILARITY) -> str | None:
    """Grund des Widerspruchs (Text) oder None."""
    wa, wb = sig_words(a), sig_words(b)
    if not wa or not wb:
        return None
    if len(wa & wb) / len(wa | wb) < min_similarity:
        return None

    na, nb = numbers(a), numbers(b)
    if na and nb and na != nb and not na <= nb and not nb <= na:
        return f"Unterschiedliche Zahlen/Versionen: {', '.join(sorted(na))} ↔ {', '.join(sorted(nb))}"

    neg_a = bool(set(words(a)) & NEGATIONS)
    neg_b = bool(set(words(b)) & NEGATIONS)
    if neg_a != neg_b:
        return "Eine Aussage verneint, die andere bestätigt"
    return None


def _text(entry: dict) -> str:
    return f"{entry.get('title', '')}. {entry['content']}"


def _checkable(entry: dict) -> bool:
    return (entry.get("kind") not in ("chunk", "strategy") and entry.get("trust") != "OUTDATED"
            and len(entry["content"]) <= CONFLICT_MAX_CHARS)


class ConflictDetector:
    def __init__(self, db: Database, search: KnowledgeSearch):
        self.db = db
        self.search = search

    # --- Erkennung ---

    def detect(self, entry: dict) -> list[dict]:
        """Sucht Widersprüche zu bestehenden Einträgen und legt Konflikte an."""
        if not _checkable(entry):
            return []
        found = []
        candidates = self.search.search(
            _text(entry), project_id=entry.get("project_id"), include_global=True,
            exclude_trust=("OUTDATED",), kinds=("fact", "answer"),
            limit=CONFLICT_CANDIDATES_LIMIT)
        for other in candidates:
            if other["id"] == entry["id"] or not _checkable(other):
                continue
            if self._pair(entry["id"], other["id"]):
                continue  # schon bekannt (offen oder vom Nutzer entschieden)
            first, second = (entry, other) if entry["id"] < other["id"] else (other, entry)
            reason = compare_texts(_text(first), _text(second))
            if reason:
                found.append(self._create(first["id"], second["id"], reason))
        return found

    def recheck(self, entry: dict) -> list[dict]:
        """Nach einer Inhaltsänderung: alte Konflikte prüfen, entschiedene zurücksetzen, neu suchen."""
        for c in self.list_conflicts(status="open", entry_id=entry["id"]):
            other = c["b"] if c["a"]["id"] == entry["id"] else c["a"]
            still = compare_texts(_text(entry), _text(other)) if _checkable(entry) and _checkable(other) else None
            if not still:
                self._close(c, "auto_resolved", restore=True)
        self.db.execute(
            "DELETE FROM knowledge_conflicts WHERE status != 'open' AND (entry_a = ? OR entry_b = ?)",
            (entry["id"], entry["id"]))
        return self.detect(entry)

    # --- Abfragen ---

    def list_conflicts(self, status: str | None = "open", entry_id: int | None = None) -> list[dict]:
        sql, params = "SELECT * FROM knowledge_conflicts WHERE 1=1", []
        if status:
            sql += " AND status = ?"
            params.append(status)
        if entry_id is not None:
            sql += " AND (entry_a = ? OR entry_b = ?)"
            params += [entry_id, entry_id]
        rows = self.db.query(sql + " ORDER BY id DESC", tuple(params))
        for r in rows:
            r["a"] = self._brief(r["entry_a"])
            r["b"] = self._brief(r["entry_b"])
        return rows

    def partner_ids(self, entry_id: int) -> list[int]:
        rows = self.db.query(
            "SELECT entry_a, entry_b FROM knowledge_conflicts "
            "WHERE status = 'open' AND (entry_a = ? OR entry_b = ?)", (entry_id, entry_id))
        return [r["entry_b"] if r["entry_a"] == entry_id else r["entry_a"] for r in rows]

    def open_count(self, entry_id: int | None = None) -> int:
        if entry_id is None:
            return self.db.query_one("SELECT COUNT(*) AS n FROM knowledge_conflicts WHERE status='open'")["n"]
        return len(self.partner_ids(entry_id))

    # --- Lösen ---

    def resolve(self, conflict_id: int, resolution: str) -> dict:
        if resolution not in RESOLUTIONS:
            raise ValueError(f"Unbekannte Lösung: {resolution} (erlaubt: {', '.join(RESOLUTIONS)})")
        conflict = self.db.query_one("SELECT * FROM knowledge_conflicts WHERE id = ?", (conflict_id,))
        if not conflict:
            raise ValueError("Widerspruch nicht gefunden.")
        if conflict["status"] != "open":
            raise ValueError("Dieser Widerspruch ist schon gelöst.")

        with self.db.transaction():
            a, b = conflict["entry_a"], conflict["entry_b"]
            if resolution == "keep_a":
                trust_mod.apply_trust(self.db, a, "CONFIRMED")
                trust_mod.apply_trust(self.db, b, "OUTDATED")
            elif resolution == "keep_b":
                trust_mod.apply_trust(self.db, b, "CONFIRMED")
                trust_mod.apply_trust(self.db, a, "OUTDATED")
            self._mark_resolved(conflict_id, resolution)
            if resolution == "both_valid":
                self._restore(a, conflict["trust_a_before"], conflict_id)
                self._restore(b, conflict["trust_b_before"], conflict_id)
        logger.info(f"Widerspruch {conflict_id} gelöst: {resolution}")
        return self.db.query_one("SELECT * FROM knowledge_conflicts WHERE id = ?", (conflict_id,))

    def release(self, entry_id: int) -> None:
        """Vor dem Löschen eines Eintrags: Partner aus dem Widerspruch entlassen."""
        for c in self.list_conflicts(status="open", entry_id=entry_id):
            partner = c["entry_b"] if c["entry_a"] == entry_id else c["entry_a"]
            before = c["trust_b_before"] if c["entry_a"] == entry_id else c["trust_a_before"]
            self._mark_resolved(c["id"], "entry_deleted")
            self._restore(partner, before, c["id"])

    # --- intern ---

    def _pair(self, x: int, y: int) -> dict | None:
        lo, hi = sorted((x, y))
        return self.db.query_one(
            "SELECT id, status, resolution FROM knowledge_conflicts WHERE entry_a = ? AND entry_b = ?", (lo, hi))

    def _brief(self, entry_id: int) -> dict:
        return self.db.query_one(
            "SELECT id, title, content, trust, project_id FROM knowledge_entries WHERE id = ?",
            (entry_id,)) or {"id": entry_id, "title": "(gelöscht)", "content": "", "trust": ""}

    def _create(self, x: int, y: int, reason: str) -> dict:
        lo, hi = sorted((x, y))
        a, b = self._brief(lo), self._brief(hi)
        before_a = "UNCERTAIN" if a["trust"] == "CONFLICTING" else a["trust"]
        before_b = "UNCERTAIN" if b["trust"] == "CONFLICTING" else b["trust"]
        with self.db.transaction():
            cur = self.db.execute(
                "INSERT INTO knowledge_conflicts(entry_a, entry_b, reason, status, trust_a_before, "
                "trust_b_before, created_at) VALUES (?,?,?,?,?,?,?)",
                (lo, hi, reason, "open", before_a, before_b, now()))
            confirmed = "CONFIRMED" in (a["trust"], b["trust"]) and a["trust"] != b["trust"]
            for e in (a, b):
                if not (confirmed and e["trust"] == "CONFIRMED"):
                    trust_mod.apply_trust(self.db, e["id"], "CONFLICTING")
        logger.info(f"Widerspruch erkannt: #{lo} ↔ #{hi} ({reason})")
        return self.db.query_one("SELECT * FROM knowledge_conflicts WHERE id = ?", (cur.lastrowid,))

    def _mark_resolved(self, conflict_id: int, resolution: str) -> None:
        self.db.execute(
            "UPDATE knowledge_conflicts SET status='resolved', resolution=?, resolved_at=? WHERE id=?",
            (resolution, now(), conflict_id))

    def _close(self, conflict: dict, resolution: str, restore: bool) -> None:
        self._mark_resolved(conflict["id"], resolution)
        if restore:
            self._restore(conflict["entry_a"], conflict["trust_a_before"], conflict["id"])
            self._restore(conflict["entry_b"], conflict["trust_b_before"], conflict["id"])

    def _restore(self, entry_id: int, before: str, ignore_conflict_id: int) -> None:
        """Ursprüngliches Trust zurück — nur wenn der Eintrag sonst in keinem offenen Widerspruch steckt."""
        row = self.db.query_one("SELECT trust FROM knowledge_entries WHERE id = ?", (entry_id,))
        if not row or row["trust"] != "CONFLICTING":
            return
        others = [c for c in self.list_conflicts(status="open", entry_id=entry_id) if c["id"] != ignore_conflict_id]
        if others:
            return
        trust_mod.apply_trust(self.db, entry_id, before if before and before != "CONFLICTING" else "UNCERTAIN")
