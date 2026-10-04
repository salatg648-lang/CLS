"""
Context Manager (Phase 3, projektbewusst) — baut den Kontext für eine AI-Anfrage.

System-Prompt (+ Fakten, + Modus, + aktives Projekt, + relevantes Wissen) + Verlauf + neue Nachricht.

Wissen im Kontext: nur CONFIRMED / SUPPORTED / UNCERTAIN / CONFLICTING. Kandidaten und Veraltetes
bleiben draußen. Bei Widersprüchen kommt der Gegenpart mit hinein, damit die AI beide Seiten kennt.
Ein Fehler in der Wissenssuche darf den Chat nie blockieren.
"""

from dataclasses import dataclass, field

from config.knowledge import CONTEXT_KINDS, CONTEXT_TRUST_LEVELS, MAX_KNOWLEDGE_IN_CONTEXT
from core.system_prompt import build_system_prompt
from infrastructure.logger import get_logger
from memory.conversation import ConversationHistory
from memory.longterm import LongTermMemory

logger = get_logger(__name__)


@dataclass
class ContextResult:
    messages: list[dict]
    knowledge_ids: list[int] = field(default_factory=list)
    project: dict | None = None
    memory_ids: list[int] = field(default_factory=list)
    memory_versions: dict = field(default_factory=dict)
    knowledge_versions: dict = field(default_factory=dict)


class ContextManager:
    def __init__(self, conversation: ConversationHistory, longterm: LongTermMemory,
                 knowledge=None, projects=None, privacy=None):
        self.privacy = privacy
        self.conversation = conversation
        self.longterm = longterm
        self.knowledge = knowledge
        self.projects = projects

    def check_chat_provider(self, provider):
        from tools.safety import Safety, PermissionDenied
        from infrastructure.paths import ROOT
        if not provider.enabled or not provider.is_available():
            raise PermissionDenied('Provider nicht verfügbar.')
        if not provider.is_local:
            Safety(ROOT).permission('network', approved=True)
        project = self._active_project()
        if self.privacy and project and project.get('path'):
            self.privacy.check(project['path'], external=not provider.is_local)

    def build(self, user_input: str, capability: str | None = None, *, external=False) -> ContextResult:
        project = self._active_project()
        entries = self.find_knowledge(user_input, project, external=external)
        from core.context_minimizer import minimize, excerpt
        minimized = minimize([{'reference': f"knowledge:{e['id']}", 'category': 'knowledge',
            'content': e['content'], 'trust': e['trust'], 'conflicts_with': e.get('conflicts_with', [])}
            for e in entries], user_input)
        excerpts = {r['reference']: r['content'] for r in minimized.records}
        entries = [{**e, 'content': excerpts[f"knowledge:{e['id']}"]} for e in entries
                   if f"knowledge:{e['id']}" in excerpts]
        facts = self.longterm.usable(external=external)
        if external:
            facts = [{**f, 'content': value} for f in facts[:100]
                     if (value := excerpt(f['content'], user_input, limit=300))][:5]
        prompt_project = project
        if external and project:
            prompt_project = {'name':project['name'], 'description':excerpt(project.get('description', ''), user_input, limit=500),
                              'instructions':excerpt(project.get('instructions', ''), user_input, limit=700)}
        system_prompt = build_system_prompt(facts, capability, prompt_project, entries)

        messages = [{"role": "system", "content": system_prompt}]
        history = [m for m in self.conversation.get_all()
                   if m.get('meta', {}).get('project_id') == (project or {}).get('id')]
        # Eine lokale Antwort kann vertraulichen Inhalt enthalten. Extern nur einen
        # neuen Kontext senden, bis der Nutzer den Verlauf explizit zurücksetzt.
        if not external or not any(self._private_history(m) for m in history):
            history_messages = [{'role': m['role'], 'content': m['content']} for m in history]
            if external:
                history_messages = [{**m, 'content':excerpt(m['content'], user_input, limit=1200, fallback=True)}
                                    for m in history_messages[-6:]]
            messages.extend(history_messages)
        messages.append({"role": "user", "content": user_input})
        return ContextResult(messages, [e["id"] for e in entries], project, [f["id"] for f in facts],
                             {str(f['id']): f.get('version', 1) for f in facts},
                             {str(e['id']): e['current_version'] for e in entries})

    def build_messages(self, user_input: str, capability: str | None = None) -> list[dict]:
        return self.build(user_input, capability).messages

    def find_knowledge(self, user_input: str, project: dict | None, *, external=False) -> list[dict]:
        if not self.knowledge:
            return []
        try:
            kb = self.knowledge
            hits = kb.search(user_input, project_id=project["id"] if project else None,
                             include_global=True, trust_levels=CONTEXT_TRUST_LEVELS,
                             kinds=CONTEXT_KINDS,
                             limit=MAX_KNOWLEDGE_IN_CONTEXT)
            entries = list(hits)
            seen = {e["id"] for e in entries}
            for hit in hits:                       # Widerspruchs-Partner immer mitliefern
                for pid in kb.conflicts.partner_ids(hit["id"]):
                    if (pid not in seen and (partner := kb.get_entry(pid))
                            and partner['project_id'] in (None, (project or {}).get('id'))
                            and partner['trust'] in CONTEXT_TRUST_LEVELS):
                        if partner['kind'] not in CONTEXT_KINDS:
                            continue
                        entries.append(partner)
                        seen.add(pid)
            if self.privacy:
                entries = [e for e in entries if self._may_use(e, external)]
            sources = kb.sources_for([e["id"] for e in entries])
            for e in entries:
                e["sources"] = sources.get(e["id"], [])
                e["conflicts_with"] = kb.conflicts.partner_ids(e["id"])
            return entries
        except Exception as e:  # Wissenssuche ist Zusatz — der Chat läuft weiter
            logger.warning(f"Wissenssuche fehlgeschlagen: {e}")
            return []

    def _active_project(self) -> dict | None:
        if not self.projects:
            return None
        try:
            return self.projects.get_active()
        except Exception as e:
            logger.warning(f"Aktives Projekt nicht lesbar: {e}")
            return None

    def _may_use(self, entry, external, seen=None):
        from tools.safety import ToolBlocked
        if entry['kind'] not in CONTEXT_KINDS or entry.get('origin_project_id') is not None:
            return False
        if entry['project_id'] is not None:
            project = self.knowledge.db.query_one('SELECT path FROM projects WHERE id=?', (entry['project_id'],))
            if not project:
                return False
            if project['path']:
                try:
                    # Die Eintragsfreigabe entscheidet über Knowledge-Export;
                    # harte Projektverbote bleiben übergeordnet. Dokumentquellen
                    # werden darunter separat mit ihrer eigenen Privacy geprüft.
                    self.privacy.check(project['path'], external=external, consent=True)
                except ToolBlocked:
                    return False
        seen = set() if seen is None else set(seen)
        key = 'knowledge:'+str(entry['id'])
        if key in seen:
            return False
        seen.add(key)
        level = self.privacy.entry_level(entry['id'])
        if level == 'BLOCKED' or (external and level != 'SAFE_FOR_EXTERNAL'):
            return False
        # Auch deduplizierte Inhalte können mehrere Dokumentquellen haben.
        sources = self.knowledge.get_sources(entry['id'])
        # AI-Kandidaten behalten die Herkunft ihrer Belege, auch nach Bestätigung/Privacy-Änderung.
        for source in sources:
            ref = source.get('reference', '')
            if not ref.startswith('derived:'):
                continue
            ref = ref[len('derived:'):]
            try:
                if ref.startswith('knowledge:'):
                    identity, version = ref[len('knowledge:'):].split('@', 1)
                    parent = self.knowledge.get_entry(int(identity))
                    if (not parent or parent['project_id'] not in (None, entry['project_id'])
                            or parent['current_version'] != int(version) or not self._may_use(parent, external, seen)):
                        return False
                elif ref.startswith('file:'):
                    self.privacy.check(ref[len('file:'):], external=external)
                elif ref.startswith('project:'):
                    project = self.projects.get(int(ref[len('project:'):])) if self.projects else None
                    if not project or project['id'] != entry['project_id']:
                        return False
                    self.privacy.check(project['path'], external=external)
                elif ref.startswith('experience:'):
                    if not self._experience_safe(ref[len('experience:'):], external=external, seen=seen):
                        return False
                elif ref.startswith('memory:'):
                    identity, version = ref[len('memory:'):].split('@', 1)
                    if not any(f['id'] == int(identity) and f.get('version', 1) == int(version)
                               for f in self.longterm.usable(external=external)):
                        return False
            except (ToolBlocked, ValueError):
                return False
        primary = self.knowledge.db.query_one(
            'SELECT * FROM knowledge_documents WHERE id=?', (entry.get('document_id'),))
        docs = [primary] if primary else []
        for source in sources:
            if (source['source_type'] == 'document'
                    and (not primary or source['name'] != primary['filename'])):
                docs.extend(self.knowledge.db.query(
                    'SELECT * FROM knowledge_documents WHERE filename=? AND project_id IS ?',
                    (source['name'], entry.get('project_id'))))
        try:
            for doc in docs:
                origins = self.knowledge.db.query('SELECT path FROM document_origins WHERE document_id=?', (doc['id'],))
                for path in origins or [{'path': doc['stored_path']}]:
                    self.privacy.check(path['path'], external=external)
        except ToolBlocked:
            return False
        return True

    def _memory_safe(self, identity, external):
        return any(f['id'] == identity for f in self.longterm.usable(external=external))

    def _private_history(self, message):
        meta = message.get('meta', {})
        if any(not self._memory_safe(identity, True) for identity in meta.get('memory', [])):
            return True
        current = {str(f['id']): f.get('version', 1) for f in self.longterm.usable(external=True)}
        if any(current.get(identity) != version for identity, version in meta.get('memory_versions', {}).items()):
            return True
        if meta.get('local_only'):
            return True
        if self.privacy and self.knowledge:
            for entry_id in meta.get('knowledge', []):
                entry = self.knowledge.get_entry(entry_id)
                if not entry or not self._may_use(entry, True):
                    return True
        return False

    def task_sources(self, task, query=None, *, external=False):
        return self.retrieve_task(task, query, external=external).records

    def retrieve_task(self, task, query=None, *, external=False):
        """Relevante Task-Quellen; ALL_AVAILABLE hebt weder Trust noch Privacy/Scope auf.

        Diese Auswahl ist getrennt vom persönlichen Chatverlauf. Jeder Treffer trägt
        Kategorie, Referenz und Herkunft; vor jedem Provider-Aufruf wird neu geprüft.
        """
        from tasks.policy import source_allowed
        from knowledge.models import query_tokens
        from tools.safety import Safety, ToolBlocked
        from tools.file_tools import read_file
        from config.knowledge import CONTEXT_RETRIEVAL_LIMIT
        from core.context_minimizer import minimize
        query = query or task['goal']
        tokens = query_tokens(query)
        records = []
        stats = self.knowledge.search_engine.counts(query, task['project_id'], CONTEXT_TRUST_LEVELS,
                                                   kinds=CONTEXT_KINDS)
        stats.update(privacy_excluded=0, policy_excluded=0)
        safety = Safety(task['root'])
        safety.permission('read')
        self.privacy.check(task['root'], external=False)

        def add(category, reference, content, **meta):
            if not source_allowed(task, category):
                stats['policy_excluded'] += 1
            elif content:
                records.append(dict(category=category, reference=reference, content=content, **meta))

        entries = self.knowledge.search(query, project_id=task['project_id'], include_global=True,
                                        trust_levels=CONTEXT_TRUST_LEVELS, kinds=CONTEXT_KINDS,
                                        limit=CONTEXT_RETRIEVAL_LIMIT)
        stats['not_retrieved'] = max(0, stats['matching_entries'] - len(entries))
        seen = {e['id'] for e in entries}
        for entry in list(entries):
            for partner_id in self.knowledge.conflicts.partner_ids(entry['id']):
                partner = self.knowledge.get_entry(partner_id)
                if (partner and partner_id not in seen and partner['trust'] in CONTEXT_TRUST_LEVELS
                        and partner['kind'] in CONTEXT_KINDS
                        and partner['project_id'] in (None, task['project_id'])):
                    entries.append(partner)
                    seen.add(partner_id)
        for project_id in task.get('reference_project_ids', []):
            if project_id == task['project_id'] or not self.projects.get(project_id):
                continue
            for entry in self.knowledge.search(query, project_id=project_id, include_global=False,
                    trust_levels=('CONFIRMED', 'SUPPORTED'), kinds=CONTEXT_KINDS, limit=10):
                if entry['reference_allowed'] and entry['id'] not in seen and not self.knowledge.conflicts.open_count(entry['id']):
                    entries.append(entry)
                    seen.add(entry['id'])
        for entry in entries:
            sources = self.knowledge.get_sources(entry['id'])
            category = ('DOCUMENTATION' if entry.get('document_id') or any(s['source_type'] == 'document' for s in sources)
                        else 'EXTERNAL_RESEARCH' if any(s['source_type'] == 'web' for s in sources)
                        else 'PROJECT_KNOWLEDGE' if entry['project_id'] is not None else 'CLS_KNOWLEDGE')
            if self._may_use(entry, external):
                add(category, f"knowledge:{entry['id']}", entry['content'], trust=entry['trust'],
                    version=entry['current_version'], updated_at=entry['updated_at'], provenance=sources,
                    conflicts_with=self.knowledge.conflicts.partner_ids(entry['id']),
                    origin_project_id=entry['project_id'],
                    reference_only=entry['project_id'] not in (None, task['project_id']))
            else:
                stats['privacy_excluded'] += 1

        # Projektanweisungen sind Kontext, keine zusätzliche Berechtigung.
        project = task.get('project') or {}
        try:
            self.privacy.check(task['root'], external=external, consent=bool(task.get('external')))
        except ToolBlocked:
            pass
        else:
            add('PROJECT_KNOWLEDGE', f"project:{task['project_id']}",
                '\n'.join(v for v in (project.get('description'), project.get('instructions')) if v),
                trust='CONFIRMED')

        # Bereits vorhandene, relevante Dokumentation innerhalb des gewählten Arbeitsordners.
        # Keine Netzwerkabfrage und kein ungefragter Import; gleicher Safety-/Privacy-Pfad wie Tools.
        if source_allowed(task, 'DOCUMENTATION'):
            import os
            from pathlib import Path
            visited = 0
            for directory, dirs, files in os.walk(safety.root, followlinks=False):
                safe_dirs = []
                for name in dirs:
                    try:
                        path = safety.path(str(Path(directory) / name))
                        self.privacy.check(path, external=external, consent=bool(task.get('external')))
                        safe_dirs.append(name)
                    except ToolBlocked:
                        pass
                dirs[:] = safe_dirs
                visited += len(dirs) + len(files) + 1
                if visited > 300:
                    break
                for name in files:
                    if Path(name).suffix.casefold() not in ('.md', '.txt', '.rst', '.markdown'):
                        continue
                    try:
                        path = safety.path(str(Path(directory) / name))
                        self.privacy.check(path, external=external, consent=bool(task.get('external')))
                        text = read_file(path)
                    except ToolBlocked:
                        stats['privacy_excluded'] += 1
                        continue
                    except OSError:
                        continue
                    if any(t in text.casefold() or t in name.casefold() for t in tokens):
                        add('DOCUMENTATION', 'file:' + str(path), text, trust='SUPPORTED', path=str(path))

        experience = getattr(self, 'experience', None)
        if experience and source_allowed(task, 'EXPERIENCE'):
            items = experience.list(project_id=task['project_id'])
            for project_id in task.get('reference_project_ids', []):
                if self.projects.get(project_id):
                    items.extend(e for e in experience.list(project_id=project_id) if e['summary'].get('reference_allowed'))
            for item in items:
                if not item['summary'].get('verified') or item['summary'].get('status') != 'COMPLETED':
                    continue
                if not any(t in item['goal'].casefold() for t in tokens):
                    continue
                if not self._experience_safe(item['task_id'], external=external):
                    continue
                add('EXPERIENCE', 'experience:' + item['task_id'],
                    item['goal'] + '\n' + item['summary']['result'], trust='VERIFIED',
                    origin_project_id=item['project_id'], reference_only=item['project_id'] != task['project_id'],
                    evidence_kind='historical_experience', fingerprint=experience.fingerprint(item))

        for fact in self.longterm.usable(external=external):
            if any(t in fact['content'].casefold() for t in tokens):
                add('OTHER_RELEVANT_KNOWLEDGE', f"memory:{fact['id']}", fact['content'], trust='CONFIRMED', version=fact.get('version', 1))

        return minimize(records, query, stats)

    def record_allowed(self, task, record, *, external=False, seen=None):
        """Bereits verwendete Referenzen vor jedem Provider-Aufruf erneut prüfen."""
        from tasks.policy import source_allowed
        from tools.safety import ToolBlocked
        if not source_allowed(task, record['category']):
            return False
        ref = record['reference']
        if ref.startswith('knowledge:'):
            entry = self.knowledge.get_entry(int(ref.split(':', 1)[1]))
            if not entry or entry['trust'] not in CONTEXT_TRUST_LEVELS:
                return False
            if entry['current_version'] != record.get('version', entry['current_version']):
                return False
            if entry['project_id'] not in (None, task['project_id']):
                if (entry['project_id'] not in task.get('reference_project_ids', []) or not entry['reference_allowed']
                        or entry['trust'] not in ('CONFIRMED', 'SUPPORTED')
                        or self.knowledge.conflicts.open_count(entry['id'])):
                    return False
            return self._may_use(entry, external, seen)
        if ref.startswith('experience:'):
            experience = getattr(self, 'experience', None)
            item = experience.get(ref.split(':', 1)[1]) if experience else None
            if not item:
                return False
            if record.get('fingerprint') and experience.fingerprint(item) != record['fingerprint']:
                return False
            if item['project_id'] != task['project_id'] and (item['project_id'] not in task.get('reference_project_ids', [])
                    or not item['summary'].get('reference_allowed')):
                return False
            return self._experience_safe(item['task_id'], external=external, seen=seen)
        if ref.startswith('memory:'):
            identity = int(ref.split(':', 1)[1])
            return any(f['id'] == identity and f.get('version', 1) == record.get('version', f.get('version', 1))
                       for f in self.longterm.usable(external=external))
        if ref.startswith('project:'):
            if ref != 'project:' + str(task['project_id']) or not self.projects.get(task['project_id']):
                return False
            path = task['root']
        elif ref.startswith('file:'):
            path = ref[5:]
        else:
            return False
        try:
            self.privacy.check(path, external=external, consent=bool(task.get('external')))
        except ToolBlocked:
            return False
        return True

    def provider_messages(self, task, knowledge, query):
        """Ein gemeinsamer Ausgang für native Requests: nur aktuelle Tool-Runde + knapper Zustand.

        Native Calls/Signaturen bleiben vollständig. Große signierte Antworten werden
        durch das Request-Budget abgelehnt statt durch Abschneiden ungültig gemacht.
        """
        from copy import deepcopy
        from core.context_minimizer import excerpt
        from config.knowledge import TOOL_CONTEXT_CHARS
        history = task.get('messages', [])
        system = history[0] if history and history[0]['role'] == 'system' else {'role':'system','content':''}
        initial = next((m for m in history if m['role'] == 'user'), {'role':'user','content':task['goal']})
        last_turn = next((i for i in range(len(history)-1, -1, -1) if history[i]['role'] == 'assistant'), len(history))
        latest_user_index = next((i for i in range(len(history)-1, -1, -1) if history[i]['role'] == 'user'), -1)
        latest_user = history[latest_user_index] if latest_user_index >= 0 else initial
        messages = [deepcopy(system), knowledge, deepcopy(initial)]
        if latest_user is not initial and latest_user_index < last_turn:
            messages.append(deepcopy(latest_user))
        state = {'plan': task['plan'], 'completed': task['progress']['completed_steps'][-10:],
                 'verified': task['verified'], 'dirty': task['dirty'], 'checks': task.get('checks', [])}
        import json
        messages.append({'role':'system','content':'Ausführungszustand von CLS: '+json.dumps(state, ensure_ascii=False)})
        seen = set()
        for index, original in enumerate(history[last_turn:], start=last_turn):
            if original['role'] == 'user' and index != latest_user_index:
                continue
            message = deepcopy(original)
            if message['role'] == 'tool':
                result = message['result']
                focus = message.pop('context_query', '') or query
                for field in ('content', 'output', 'answer'):
                    value = result.get(field)
                    if not isinstance(value, str):
                        continue
                    snippet = value
                    if len(value) > TOOL_CONTEXT_CHARS:
                        snippet = excerpt(value, focus, limit=TOOL_CONTEXT_CHARS, fallback=True)
                        if snippet in seen:
                            snippet = ''
                        else:
                            seen.add(snippet)
                    result[field] = snippet
                    result['context_minimized'] = True
                    result.setdefault('source_chars', len(value))
                if isinstance(result.get('matches'), list):
                    result['matches'] = result['matches'][:20]
            messages.append(message)
        return messages

    def _experience_external_safe(self, task_id):
        return self._experience_safe(task_id, external=True)

    def _experience_safe(self, task_id, *, external=False, seen=None):
        """Eine Zusammenfassung lokaler Arbeit darf vertrauliche Quelldaten nicht exportieren."""
        import json
        from tools.safety import ToolBlocked
        seen = set() if seen is None else set(seen)
        if '@' in task_id:
            task_id, fingerprint = task_id.rsplit('@', 1)
            from memory.episodic import EpisodicMemory
            item = EpisodicMemory(self.knowledge.db, None).get(task_id)
            if not item or EpisodicMemory.fingerprint(item) != fingerprint:
                return False
        key = 'experience:'+task_id
        if key in seen:
            return False
        seen.add(key)
        row = self.knowledge.db.query_one('SELECT data FROM tasks WHERE id=?', (task_id,))
        if not row:
            return False
        origin = json.loads(row['data'])
        # Legacy-Erfahrung ohne Egress-Freigabe hat keine hinreichende Export-Provenance.
        if not self.knowledge.db.query_one('SELECT id FROM projects WHERE id=?', (origin.get('project_id'),)):
            return False
        if external and (not origin.get('external') or origin.get('local_only')):
            return False
        try:
            for path in [origin['root'], *origin.get('read_paths', [])]:
                self.privacy.check(path, external=external, consent=bool(origin.get("external")))
            for record in origin.get('knowledge_used', []):
                if not self.record_allowed(origin, record, external=external, seen=seen):
                    return False
        except ToolBlocked:
            return False
        return True
