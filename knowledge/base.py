"""
Knowledge Base (Phase 3) — Wissen mit Provenance, Trust, Versioning und Conflicts.

Jeder Eintrag hat: Inhalt, Trust-Level, Quellen (woher?), Versionen (was war vorher?)
und ggf. Widersprüche zu anderen Einträgen.

Fehler bei ungültigen Eingaben: ValueError mit verständlicher (deutscher) Meldung.

Controlled Learning: AI-Antworten landen NUR als CANDIDATE (add_ai_candidate) — sie fließen
erst in den Kontext, wenn der Nutzer sie bestätigt oder sie unabhängig gestützt werden.
"""

import re
import json

from config import knowledge as cfg
from infrastructure.database import Database, now
from infrastructure.logger import get_logger
from knowledge import trust as trust_mod
from knowledge import versions
from knowledge.conflicts import ConflictDetector
from knowledge.models import (
    content_hash, domain_of, entry_from_row, tags_to_text,
)
from knowledge.search import KnowledgeSearch

logger = get_logger(__name__)

# "chunk" setzt nur der Dokument-Import explizit; ein kurzer Fakt mit Dokument-Quelle bleibt ein Fakt.
_KIND_BY_SOURCE = {"ai_provider": "answer", "web": "answer"}
_SOURCE_LINE = re.compile(r"^\[\d+\]\s+(https?://\S+)\s*$", re.MULTILINE)


def _default_title(content: str) -> str:
    first = content.strip().splitlines()[0].strip()
    return first if len(first) <= 60 else first[:59].rstrip() + "…"


def split_sources_block(text: str) -> tuple[str, list[str]]:
    """Trennt den 'Quellen:'-Block (Perplexity) vom Antworttext. Rückgabe: (Text, [URLs])."""
    marker = "\n\nQuellen:\n"
    if marker in text:
        body, _, block = text.partition(marker)
        return body.strip(), _SOURCE_LINE.findall(block)
    return text.strip(), []


class KnowledgeBase:
    def __init__(self, db: Database):
        self.db = db
        self.search_engine = KnowledgeSearch(db)
        self.conflicts = ConflictDetector(db, self.search_engine)

    # ---------------------------------------------------------------- Erstellen

    def add_entry(self, content: str, title: str = "", topic: str = "", tags: list[str] | None = None,
                  source_type: str = "user", source_name: str = "", url: str = "",
                  reference: str = "", trust: str | None = None, project_id: int | None = None,
                  kind: str | None = None, document_id: int | None = None,
                  changed_by: str | None = None, check_conflicts: bool = True,
                  extra_sources: list[dict] | None = None) -> dict:
        """
        Legt einen Eintrag an.
        Rückgabe: {"entry": {...}, "created": bool, "conflicts": [...]}
        Gibt es den Inhalt schon (gleiches Projekt), wird nichts doppelt angelegt: die neue
        Quelle wird dem bestehenden Eintrag als zusätzlicher Beleg hinzugefügt.
        """
        content = (content or "").strip()
        if not content:
            raise ValueError("Der Inhalt darf nicht leer sein.")
        if source_type not in cfg.SOURCE_TYPES:
            raise ValueError(f"Unbekannter Quellen-Typ: {source_type}")
        trust = trust_mod.validate(trust or trust_mod.initial_trust(source_type))
        kind = kind or _KIND_BY_SOURCE.get(source_type, "fact")
        if kind not in cfg.KINDS:
            raise ValueError(f"Unbekannte Art: {kind}")
        if kind == 'strategy':
            raise ValueError('Strategien benötigen Episoden und Reflexion: add_strategy_candidate verwenden.')
        self._check_project(project_id)

        sources = [{"source_type": source_type, "name": source_name, "url": url, "reference": reference}]
        sources += extra_sources or []

        with self.db.transaction():
            digest = content_hash(content)
            dup = self.db.query_one(
                "SELECT id, kind FROM knowledge_entries WHERE content_hash = ? AND project_id IS ?",
                (digest, project_id))
            if dup:
                if dup['kind'] == 'strategy':
                    raise ValueError('Dieser Inhalt gehört zu einem Strategiekandidaten.')
                for s in sources:
                    self._add_source_if_new(dup["id"], **s)
                self._reevaluate_trust(dup["id"])
                return {"entry": self.get_entry(dup["id"]), "created": False, "conflicts": []}

            ts = now()
            title = (title or "").strip() or _default_title(content)
            cur = self.db.execute(
                "INSERT INTO knowledge_entries(title, content, topic, tags, trust, kind, project_id, "
                "document_id, current_version, content_hash, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,1,?,?,?)",
                (title, content, (topic or "").strip(), tags_to_text(tags), trust, kind,
                 project_id, document_id, digest, ts, ts))
            entry_id = cur.lastrowid
            versions.record(self.db, entry_id, 1, title, content, trust,
                            changed_by or source_type, "Erstellt")
            for s in sources:
                self._add_source_if_new(entry_id, **s)

            entry = self.get_entry(entry_id)
            found = self.conflicts.detect(entry) if check_conflicts else []
            if found:
                entry = self.get_entry(entry_id)

        logger.info(f"Wissen #{entry_id} angelegt ({trust}, {kind}): {title[:50]}")
        return {"entry": entry, "created": True, "conflicts": found}

    def add_strategy_candidate(self, content, experience_ids, *, applicability, rationale, title=''):
        """Expliziter Reflexionsvorschlag; keine Mustererkennung oder Freigabe.

        Scope wird ausschließlich aus den Episoden abgeleitet. Auch viele erfolgreiche
        Episoden sind hier noch keine verifizierte Strategie.
        """
        from memory.episodic import EpisodicMemory
        if any(not isinstance(value, str) for value in (content, applicability, rationale, title)):
            raise ValueError('Strategie, Anwendungsbedingungen, Begründung und Titel müssen Texte sein.')
        content, applicability, rationale = content.strip(), applicability.strip(), rationale.strip()
        if not content or not applicability or not rationale:
            raise ValueError('Strategie, Anwendungsbedingungen und Begründung sind erforderlich.')
        if not isinstance(experience_ids, (list, tuple)) or not experience_ids:
            raise ValueError('Mindestens eine Experience-Referenz ist erforderlich.')
        if any(not isinstance(task_id, str) or not task_id for task_id in experience_ids):
            raise ValueError('Ungültige Experience-Referenz.')
        with self.db.transaction():
            memory = EpisodicMemory(self.db, None)
            episodes = [memory.get(task_id) for task_id in dict.fromkeys(experience_ids)]
            if any(item is None for item in episodes):
                raise ValueError('Experience nicht gefunden.')
            scopes = {item['project_id'] for item in episodes}
            if len(scopes) != 1:
                raise ValueError('Projektübergreifende Generalisierung benötigt eine eigene Verifikation.')
            project_id = scopes.pop()
            self._check_project(project_id)
            digest = content_hash(content)
            if self.db.query_one('SELECT id FROM knowledge_entries WHERE content_hash=? AND project_id IS ?',
                                 (digest, project_id)):
                raise ValueError('Dieser Inhalt existiert bereits in diesem Geltungsbereich.')
            evidence = [{'task_id': item['task_id'], 'fingerprint': memory.fingerprint(item),
                         'project_id': item['project_id'], 'workflow_id': item['workflow_id'],
                         'verified': item['summary'].get('verified', False),
                         'status': item['summary'].get('status'),
                         'timeline_complete': item['summary'].get('timeline_complete', False)}
                        for item in episodes]
            strategy = {'schema_version': 1, 'status': 'CANDIDATE', 'confidence': None,
                        'scope': {'kind': 'project' if project_id is not None else 'global',
                                  'project_id': project_id},
                        'applicability': applicability, 'rationale': rationale,
                        'evidence': evidence, 'verification': None}
            ts = now()
            title = title.strip() or _default_title(content)
            cur = self.db.execute(
                "INSERT INTO knowledge_entries(title,content,trust,kind,project_id,content_hash,created_at,updated_at,strategy) "
                "VALUES (?,?,'CANDIDATE','strategy',?,?,?,?,?)",
                (title, content, project_id, digest, ts, ts, json.dumps(strategy, ensure_ascii=False)))
            entry_id = cur.lastrowid
            versions.record(self.db, entry_id, 1, title, content, 'CANDIDATE', 'reflection',
                            'Expliziter Strategiekandidat; nicht verifiziert')
            for item in evidence:
                self._add_source_if_new(entry_id, 'experience', name=item['task_id'],
                    reference='derived:experience:' + item['task_id'] + '@' + item['fingerprint'])
            return self.get_entry(entry_id, with_details=True)

    def add_ai_candidate(self, question: str, answer: str, provider: str,
                         project_id: int | None = None, *, references=None) -> dict | None:
        """Controlled Learning: AI-Antwort als CANDIDATE speichern (None, wenn zu kurz/lang)."""
        body, urls = split_sources_block(answer)
        if not (cfg.AUTO_CANDIDATE_MIN_CHARS <= len(body)):
            return None
        if len(body) > cfg.AUTO_CANDIDATE_MAX_CHARS:
            body = body[:cfg.AUTO_CANDIDATE_MAX_CHARS].rstrip() + "…"
        # Eine wiederholte Antwort ist kein unabhängiger Beleg. Bestehende
        # Einträge unverändert lassen, insbesondere keine Selbstreferenz ableiten.
        duplicate = self.db.query_one(
            'SELECT id FROM knowledge_entries WHERE content_hash=? AND project_id IS ?',
            (content_hash(body), project_id))
        if duplicate:
            return {'entry': self.get_entry(duplicate['id']), 'created': False, 'conflicts': []}
        title = " ".join(question.split())
        title = title if len(title) <= 80 else title[:79].rstrip() + "…"
        cited = [{"source_type": "web", "name": domain_of(u), "url": u, "reference": "zitiert"}
                 for u in urls[:8]]
        return self.add_entry(
            body, title=title, tags=["ai_answer"], source_type="ai_provider", source_name=provider,
            reference="Antwort auf Nutzerfrage", trust="CANDIDATE", project_id=project_id,
            kind="answer", extra_sources=cited + (references or []))

    def assess_task_answer(self, question, answer, provider, project_id, references):
        """Begrenzter Vergleich mit tatsächlich ausgewählten Belegen; keine Wahrheitsprüfung.

        Bestehende bestätigte Einträge werden bei identischen Antworten nicht verändert.
        Neue Antworten bleiben Kandidaten bzw. werden über das bestehende Konfliktsystem markiert.
        """
        from knowledge.conflicts import compare_texts
        body, urls = split_sources_block(answer)
        body = body[:cfg.AUTO_CANDIDATE_MAX_CHARS].strip()
        if not body:
            return {'status':'empty', 'candidate_id':None, 'conflict_ids':[]}
        matches, contradictions = [], []
        for ref in references:
            if not ref['reference'].startswith('knowledge:'):
                continue
            entry = self.get_entry(int(ref['reference'].split(':', 1)[1]))
            if (not entry or entry['project_id'] not in (None, project_id)
                    or entry['current_version'] != ref.get('version', entry['current_version'])):
                continue
            if content_hash(body) == content_hash(ref['content']):
                matches.append(entry['id'])
                continue
            for statement in re.split(r'(?<=[.!?])\s+|\n+', body):
                statement = statement.strip()
                if 0 < len(statement) <= cfg.CONFLICT_MAX_CHARS:
                    reason = compare_texts(statement, ref['content'])
                    if reason:
                        contradictions.append((entry['id'], reason))
                        break
        with self.db.transaction():
            duplicate = self.db.query_one('SELECT id FROM knowledge_entries WHERE content_hash=? AND project_id IS ?',
                                          (content_hash(body), project_id))
            candidate, created = None, False
            if cfg.AUTO_CANDIDATES and not duplicate:
                candidate = self.add_entry(body, title=question[:80], source_type='ai_provider', source_name=provider,
                    reference='Gezielte Task-Anfrage; ungeprüfte AI-Antwort', trust='CANDIDATE', kind='answer',
                    project_id=project_id, check_conflicts=False,
                    extra_sources=([{'source_type':'web','name':domain_of(u),'url':u,'reference':'zitiert'} for u in urls[:8]] +
                        [{'source_type':'ai_provider','name':provider,'url':'',
                          'reference':'derived:'+ref['reference']+(f"@{ref['version']}" if 'version' in ref else '')}
                         for ref in references]))['entry']
                created = True
            elif duplicate:
                candidate = self.get_entry(duplicate['id'])
            conflict_ids = []
            unresolved, reviewed = len(contradictions), 0
            if candidate:
                for other_id, reason in contradictions:
                    if other_id == candidate['id']:
                        unresolved -= 1
                        continue
                    existing = self.conflicts._pair(candidate['id'], other_id)
                    # Bereits manuell entschiedene Konflikte werden nicht automatisch neu geöffnet.
                    if existing and existing['status'] == 'resolved' and existing['resolution'] == 'both_valid':
                        unresolved -= 1
                        reviewed += 1
                        continue
                    conflict = existing or self.conflicts._create(candidate['id'], other_id, reason)
                    if conflict['status'] == 'open':
                        conflict_ids.append(conflict['id'])
        return {'status':'conflict' if unresolved else 'reviewed_conflict' if reviewed else 'matching_evidence' if matches else 'unverified',
                'candidate_id':candidate['id'] if candidate else None, 'created':created,
                'conflict_ids':conflict_ids, 'compared':len(references), 'matching_ids':matches[:8]}

    # ---------------------------------------------------------------- Lesen

    def get_entry(self, entry_id: int, with_details: bool = False) -> dict | None:
        row = self.db.query_one("SELECT * FROM knowledge_entries WHERE id = ?", (entry_id,))
        if not row:
            return None
        entry = entry_from_row(row)
        if with_details:
            entry["sources"] = self.get_sources(entry_id)
            entry["versions"] = versions.list_versions(self.db, entry_id)
            entry["conflicts"] = self.conflicts.list_conflicts(status="open", entry_id=entry_id)
        return entry

    def list_entries(self, project_id: int | None = None, only_global: bool = False,
                     trust: str | None = None, kind: str | None = None,
                     limit: int = 500, offset: int = 0) -> list[dict]:
        sql, params = "SELECT * FROM knowledge_entries WHERE 1=1", []
        if project_id is not None:
            sql += " AND project_id = ?"
            params.append(project_id)
        elif only_global:
            sql += " AND project_id IS NULL"
        if trust:
            sql += " AND trust = ?"
            params.append(trust)
        if kind:
            sql += " AND kind = ?"
            params.append(kind)
        sql += " ORDER BY updated_at DESC, id DESC LIMIT ? OFFSET ?"
        rows = self.db.query(sql, (*params, limit, offset))
        return [entry_from_row(r) for r in rows]

    def search(self, query: str, **kwargs) -> list[dict]:
        return self.search_engine.search(query, **kwargs)

    def get_sources(self, entry_id: int) -> list[dict]:
        return self.db.query("SELECT * FROM knowledge_sources WHERE entry_id = ? ORDER BY id", (entry_id,))

    def sources_for(self, entry_ids: list[int]) -> dict[int, list[dict]]:
        if not entry_ids:
            return {}
        rows = self.db.query(
            f"SELECT * FROM knowledge_sources WHERE entry_id IN ({','.join('?' * len(entry_ids))}) ORDER BY id",
            tuple(entry_ids))
        out: dict[int, list[dict]] = {i: [] for i in entry_ids}
        for r in rows:
            out[r["entry_id"]].append(r)
        return out

    def get_history(self, entry_id: int) -> list[dict]:
        return versions.list_versions(self.db, entry_id)

    def stats(self) -> dict:
        by_trust = {t: 0 for t in cfg.TRUST_LEVELS}
        for r in self.db.query("SELECT trust, COUNT(*) AS n FROM knowledge_entries GROUP BY trust"):
            by_trust[r["trust"]] = r["n"]
        return {
            "total": sum(by_trust.values()),
            "by_trust": by_trust,
            "open_conflicts": self.conflicts.open_count(),
            "documents": self.db.query_one("SELECT COUNT(*) AS n FROM knowledge_documents")["n"],
            "fts": self.db.fts_available,
        }

    # ---------------------------------------------------------------- Ändern

    def update_entry(self, entry_id: int, content: str | None = None, title: str | None = None,
                     topic: str | None = None, tags: list[str] | None = None,
                     changed_by: str = "user", note: str = "") -> dict:
        """Ändert einen Eintrag. Bei neuem Inhalt/Titel entsteht eine neue Version (alte bleibt erhalten)."""
        with self.db.transaction():
            old = self.get_entry(entry_id)
            if not old:
                raise ValueError("Eintrag nicht gefunden.")
            if old['kind'] == 'strategy':
                raise ValueError('Strategiekandidaten sind unveränderlich; einen neuen Vorschlag mit Belegen erstellen.')
            new_content = old["content"] if content is None else content.strip()
            if not new_content:
                raise ValueError("Der Inhalt darf nicht leer sein.")
            new_title = old["title"] if title is None else (title.strip() or _default_title(new_content))
            new_topic = old["topic"] if topic is None else topic.strip()
            new_tags = old["tags"] if tags is None else tags

            content_changed = (new_content != old["content"]) or (new_title != old["title"])
            version = old["current_version"] + (1 if content_changed else 0)

            self.db.execute(
                "UPDATE knowledge_entries SET title=?, content=?, topic=?, tags=?, current_version=?, "
                "content_hash=?, updated_at=? WHERE id=?",
                (new_title, new_content, new_topic, tags_to_text(new_tags), version,
                 content_hash(new_content), now(), entry_id))
            if content_changed:
                versions.record(self.db, entry_id, version, new_title, new_content, old["trust"],
                                changed_by, note or "Bearbeitet")
                self.conflicts.recheck(self.get_entry(entry_id))
            return self.get_entry(entry_id)

    def restore_version(self, entry_id: int, version: int, changed_by: str = "user") -> dict:
        """Alte Version wiederherstellen — als NEUE Version (der Verlauf bleibt vollständig)."""
        old = versions.get_version(self.db, entry_id, version)
        if not old:
            raise ValueError("Version nicht gefunden.")
        return self.update_entry(entry_id, content=old["content"], title=old["title"],
                                 changed_by=changed_by, note=f"Wiederhergestellt aus Version {version}")

    def set_trust(self, entry_id: int, trust: str) -> dict:
        trust_mod.validate(trust)
        entry = self.get_entry(entry_id)
        if not entry:
            raise ValueError("Eintrag nicht gefunden.")
        if entry.get('origin_project_id') is not None and trust != 'OUTDATED':
            raise ValueError('Wissen eines gelöschten Projekts darf nicht global freigegeben werden.')
        if entry['kind'] == 'strategy' and trust not in ('CANDIDATE', 'OUTDATED'):
            raise ValueError('Strategie-Freigabe benötigt eine eigene Verifikation; noch nicht implementiert.')
        if entry['kind'] == 'strategy' and entry['strategy']['status'] == 'RETIRED' and trust != 'OUTDATED':
            raise ValueError('Stillgelegte Strategien können nicht reaktiviert werden.')
        if trust == "CONFLICTING":
            raise ValueError("CONFLICTING wird automatisch bei einem Widerspruch gesetzt.")
        if self.conflicts.open_count(entry_id):
            raise ValueError("Dieser Eintrag hat einen offenen Widerspruch — bitte zuerst den Widerspruch lösen.")
        with self.db.transaction():
            trust_mod.apply_trust(self.db, entry_id, trust)
            if entry['kind'] == 'strategy' and trust == 'OUTDATED':
                strategy = {**entry['strategy'], 'status': 'RETIRED'}
                self.db.execute('UPDATE knowledge_entries SET strategy=? WHERE id=?',
                                (json.dumps(strategy, ensure_ascii=False), entry_id))
        logger.info(f"Wissen #{entry_id}: Trust {entry['trust']} → {trust}")
        return self.get_entry(entry_id)

    def confirm(self, entry_id: int) -> dict:
        return self.set_trust(entry_id, "CONFIRMED")

    def mark_outdated(self, entry_id: int) -> dict:
        return self.set_trust(entry_id, "OUTDATED")

    def add_source(self, entry_id: int, source_type: str, name: str = "", url: str = "",
                   reference: str = "") -> dict:
        """Weiteren Beleg hinzufügen (kann CANDIDATE → SUPPORTED heben, siehe knowledge/trust.py)."""
        if not self.get_entry(entry_id):
            raise ValueError("Eintrag nicht gefunden.")
        if source_type not in cfg.SOURCE_TYPES:
            raise ValueError(f"Unbekannter Quellen-Typ: {source_type}")
        with self.db.transaction():
            self._add_source_if_new(entry_id, source_type, name, url, reference)
            self._reevaluate_trust(entry_id)
        return self.get_entry(entry_id, with_details=True)

    def set_reference_allowed(self, entry_id, allowed):
        entry = self.get_entry(entry_id)
        if (not isinstance(allowed, bool) or not entry or entry['kind'] == 'strategy'
                or entry['project_id'] is None or entry.get('origin_project_id') is not None):
            raise ValueError('Nur vorhandenes Projektwissen kann als Referenz freigegeben werden.')
        self.db.execute('UPDATE knowledge_entries SET reference_allowed=?, updated_at=? WHERE id=?',
                        (int(allowed), now(), entry_id))
        return self.get_entry(entry_id)

    def delete_entry(self, entry_id: int) -> bool:
        with self.db.transaction():
            if not self.get_entry(entry_id):
                return False
            self.conflicts.release(entry_id)
            self.db.execute("DELETE FROM knowledge_entries WHERE id = ?", (entry_id,))
        logger.info(f"Wissen #{entry_id} gelöscht")
        return True

    # ---------------------------------------------------------------- Widersprüche

    def get_conflicts(self, status: str | None = "open") -> list[dict]:
        return self.conflicts.list_conflicts(status=status)

    def resolve_conflict(self, conflict_id: int, resolution: str) -> dict:
        return self.conflicts.resolve(conflict_id, resolution)

    # ---------------------------------------------------------------- intern

    def _check_project(self, project_id: int | None) -> None:
        if project_id is not None and not self.db.query_one(
                "SELECT 1 AS x FROM projects WHERE id = ?", (project_id,)):
            raise ValueError("Projekt nicht gefunden.")

    def _add_source_if_new(self, entry_id: int, source_type: str, name: str = "",
                           url: str = "", reference: str = "") -> None:
        exists = self.db.query_one(
            "SELECT 1 AS x FROM knowledge_sources WHERE entry_id=? AND source_type=? AND name=? "
            "AND url=? AND reference=?", (entry_id, source_type, name or "", url or "", reference or ""))
        if not exists:
            self.db.execute(
                "INSERT INTO knowledge_sources(entry_id, source_type, name, url, reference, added_at) "
                "VALUES (?,?,?,?,?,?)",
                (entry_id, source_type, name or "", url or "", reference or "", now()))

    def _reevaluate_trust(self, entry_id: int) -> None:
        row = self.db.query_one("SELECT trust, kind FROM knowledge_entries WHERE id = ?", (entry_id,))
        if row['kind'] == 'strategy':
            return  # Quellenanzahl ist keine Verifikation einer Vorgehensweise.
        new = trust_mod.evaluate(row["trust"], self.get_sources(entry_id))
        if new != row["trust"]:
            trust_mod.apply_trust(self.db, entry_id, new)
            logger.info(f"Wissen #{entry_id}: durch weitere Quellen {row['trust']} → {new}")
