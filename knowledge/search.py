"""
Knowledge Search — Textsuche (Phase 3), später RAG.

Mit FTS5 (BM25, Präfix-Suche, Umlaute egal) — ohne FTS5 ein einfacher Fallback
mit Wort-Zählung. Ergebnisse sind nach Relevanz + kleinem Trust-Bonus sortiert.

Scope: Ein Projekt sieht sein eigenes + globales Wissen. Ohne Projekt gibt es nur
globales Wissen. `all_projects=True` hebt das auf (Knowledge-Verwaltung).
"""

from config.knowledge import TRUST_SEARCH_BONUS
from infrastructure.database import Database
from knowledge.models import entry_from_row, query_tokens


class KnowledgeSearch:
    def __init__(self, db: Database):
        self.db = db

    def search(self, query: str, project_id: int | None = None, include_global: bool = True,
               all_projects: bool = False, trust_levels=None, exclude_trust=None,
               kinds=None, limit: int = 10) -> list[dict]:
        tokens = query_tokens(query)
        if not tokens:
            return []

        where, params = self._filters(project_id, include_global, all_projects,
                                      trust_levels, exclude_trust, kinds)
        if where is None:
            return []
        fetch = max(limit * 3, 30)

        if self.db.fts_available:
            expr = " OR ".join(f'"{t}"*' for t in tokens)
            rows = self.db.query(
                "SELECT e.*, bm25(knowledge_fts, 3.0, 1.0, 2.0, 2.0) AS rank "
                "FROM knowledge_fts JOIN knowledge_entries e ON e.id = knowledge_fts.rowid "
                f"WHERE knowledge_fts MATCH ? {where} ORDER BY rank LIMIT ?",
                (expr, *params, fetch),
            )
            for r in rows:
                r["score"] = -r["rank"]
        else:
            rows = self._fallback(tokens, where, params)

        for r in rows:
            r["score"] += TRUST_SEARCH_BONUS.get(r["trust"], 0.0)
        rows.sort(key=lambda r: (-r["score"], -r["id"]))
        results = []
        for r in rows[:limit]:
            score = r.pop("score")
            e = entry_from_row(r)
            e["score"] = round(score, 4)
            results.append(e)
        return results

    def counts(self, query, project_id=None, trust_levels=None, kinds=None):
        """Exakte Zahlen im zulässigen Projektscope, unabhängig vom Retrieval-Limit."""
        where, params = self._filters(project_id, True, False, trust_levels, None, kinds)
        total = self.db.query_one(f'SELECT COUNT(*) AS n FROM knowledge_entries e WHERE 1=1 {where}', params)['n']
        tokens = query_tokens(query)
        if not tokens:
            matching = 0
        elif self.db.fts_available:
            expr = ' OR '.join(f'"{t}"*' for t in tokens)
            matching = self.db.query_one('SELECT COUNT(*) AS n FROM knowledge_fts JOIN knowledge_entries e '
                f'ON e.id=knowledge_fts.rowid WHERE knowledge_fts MATCH ? {where}', (expr, *params))['n']
        else:
            matching = len(self._fallback(tokens, where, params))
        return {'eligible_entries': total, 'matching_entries': matching, 'unrelated_entries': total - matching}

    # --- intern ---

    def _fallback(self, tokens: list[str], where: str, params: list) -> list[dict]:
        rows = self.db.query(f"SELECT e.* FROM knowledge_entries e WHERE 1=1 {where}", tuple(params))
        scored = []
        for r in rows:
            title = r["title"].lower()
            meta = f"{r['topic']} {r['tags']}".lower()
            content = r["content"].lower()
            score = sum(3 * (t in title) + 2 * (t in meta) + (t in content) for t in tokens)
            if score:
                r["score"] = float(score)
                scored.append(r)
        return scored

    @staticmethod
    def _filters(project_id, include_global, all_projects, trust_levels, exclude_trust, kinds):
        parts: list[str] = []
        params: list = []

        if not all_projects:
            if project_id is not None and include_global:
                parts.append("(e.project_id = ? OR e.project_id IS NULL)")
                params.append(project_id)
            elif project_id is not None:
                parts.append("e.project_id = ?")
                params.append(project_id)
            elif include_global:
                parts.append("e.project_id IS NULL")
            else:
                return None, []

        if trust_levels:
            parts.append(f"e.trust IN ({','.join('?' * len(trust_levels))})")
            params.extend(trust_levels)
        if exclude_trust:
            parts.append(f"e.trust NOT IN ({','.join('?' * len(exclude_trust))})")
            params.extend(exclude_trust)
        if kinds:
            parts.append(f"e.kind IN ({','.join('?' * len(kinds))})")
            params.extend(kinds)

        return ("".join(f" AND {p}" for p in parts), params)
