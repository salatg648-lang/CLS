"""
CLS Core API — die einzige öffentliche Schnittstelle zu CLS.

Die UI (Desktop, später Web/Mobile) ruft NUR diese Methoden auf.
Alles andere ist CLS-intern.

Fehler bei ungültigen Eingaben (Wissen/Projekte) kommen als ValueError mit verständlicher
deutscher Meldung — die UI zeigt sie an.
"""

import threading
from tasks.task_manager import TERMINAL

from capabilities.registry import build_default_registry
from core.assistant import Assistant
from core.context_manager import ContextManager
from core.router import Router
from knowledge.base import KnowledgeBase
from knowledge.ingestion import Ingestor
from memory.conversation import ConversationHistory
from memory.longterm import LongTermMemory
from projects.manager import ProjectManager
from config.knowledge import TRUST_LABELS, TRUST_LEVELS
from config.routing import MODES
from config import settings
from infrastructure.database import Database
from infrastructure.logger import get_logger
from infrastructure.paths import DB_FILE, KNOWLEDGE_DOCUMENTS

logger = get_logger(__name__)


class CLSCore:
    def __init__(self, registry=None, conversation=None, longterm=None, db=None,
                 documents_dir=KNOWLEDGE_DOCUMENTS, env_path=None):
        logger.info("CLS Core initialisiert...")
        self.db = db or Database(DB_FILE)
        self.longterm = longterm or LongTermMemory(db=self.db)
        self.conversation = conversation or ConversationHistory(db=self.db)
        self.registry = registry or build_default_registry(self.db, env_path)
        self.router = Router(self.registry)

        # Phase 3: SQLite, Wissen, Projekte
        self.knowledge = KnowledgeBase(self.db)
        self.ingestor = Ingestor(self.knowledge, documents_dir)
        self.projects = ProjectManager(self.db)

        self.context = ContextManager(self.conversation, self.longterm, self.knowledge, self.projects)
        self.assistant = Assistant(self.router, self.context, self.conversation, self.longterm,
                                   self.knowledge, self.projects)
        from core.agent import Agent
        from core.workflow_engine import WorkflowEngine
        from core.decision_engine import DecisionEngine
        from tools.registry import ToolRegistry
        from tools.privacy import PrivacyPolicy
        from tasks.action_trail import ActionTrail
        from tasks.task_manager import TaskManager
        from tasks.scheduler import Scheduler
        from memory.episodic import EpisodicMemory
        from infrastructure.events import EventBus
        self.privacy = PrivacyPolicy(self.db)
        self.context.privacy = self.privacy
        self.tools = ToolRegistry(self.privacy)
        self.trail = ActionTrail(self.db)
        self.tasks = TaskManager(self.db, self.trail)
        self.experience = EpisodicMemory(self.db, self.trail)
        self.workflows = WorkflowEngine(self.db, self.tools)
        self.decisions = DecisionEngine(self.workflows, self.experience)
        self.context.experience = self.experience
        self.agent = Agent(self.tasks, self.tools, self.registry, self.experience, self.knowledge,
                           self.context, self.decisions)
        self._group_lock = threading.Lock()
        self._group_pauses = set()
        self._group_cancels = set()
        self.scheduler = Scheduler(self.db, self.workflows, self._scheduled_task)
        self.events = EventBus()
        self.events.subscribe(self.scheduler.dispatch)
        logger.info("CLS Core bereit.")

    # --- Chat ---
    def chat(self, text: str, mode: str = "chat", *, provider=None, local_only=False) -> dict:
        """Sendet eine Nachricht. Rückgabe: {text, provider, capability, mode, fallback_used, error}"""
        from core.planner import local_plan
        project = self.projects.get_active()
        local = local_plan(text, (project or {}).get('path'))
        if local and local.get('session_action'):
            from core.assistant import Reply
            try:
                if local['session_action'] == 'switch_project':
                    target = self.projects.get_by_name(local['name'])
                    if not target:
                        raise ValueError('Projekt nicht gefunden. Bitte den eindeutigen Projektnamen angeben.')
                    if target.get('path'):
                        from tools.safety import Safety
                        Safety(target['path'])
                    project = self.set_active_project(target['id'])
                answer = (f"Projekt: {project['name']}\nWorkspace: {project.get('path') or 'nicht konfiguriert'}"
                          if project else 'Kein aktives Projekt.')
                return Reply(answer, provider='cls', capability='local_action').to_dict()
            except (ValueError, OSError) as exc:
                return Reply(str(exc), provider='cls', capability='local_action', error=True).to_dict()
        if local is not None:
            from core.assistant import Reply
            if not project or not project.get('path'):
                # A local file/clipboard request must not silently become an AI request.
                return Reply('Bitte ein aktives Projekt mit Arbeitsordner auswählen.',
                             provider='cls', capability='local_action', error=True).to_dict()
            try:
                task = self.create_task(text, ai_policy={'mode': 'NEVER', 'local_only': True})
                task = self.run_task(task['id'])
                from core.workflow_engine import WorkflowEngine
                answer = task['result'] or WorkflowEngine.response(task.get('tool_results', []))
                if task.get('blocking'):
                    answer += ('\n\n' if answer else '') + task['blocking']['reason']
                answer = answer or 'Aufgabe angelegt.'
                if task['status'] == 'NEEDS_CONFIRMATION':
                    answer += '\nBitte die konkrete Aktion im Aufgabenbereich prüfen und bestätigen.'
                response = Reply(answer, provider='cls', capability='local_action', mode=mode,
                                 error=task['status'] in ('FAILED', 'BLOCKED', 'NEEDS_PERMISSION')).to_dict()
                response['task_id'] = task['id']
                for role, content in (('user', text), ('assistant', answer)):
                    self.conversation.add(role, content, meta={'project_id': task['project_id'], 'local_only': True})
                return response
            except (ValueError, OSError) as exc:
                return Reply(str(exc), provider='cls', capability='local_action', error=True).to_dict()
        return self.assistant.handle_message(text, mode, provider=provider, local_only=local_only).to_dict()

    def send_message(self, text: str, mode: str = "chat") -> str:
        """Kurzform: nur der Antworttext."""
        return self.chat(text, mode)["text"]

    def get_modes(self) -> list[str]:
        return list(MODES)

    # --- Providers / Routing (Phase 2) ---
    def get_providers(self) -> list[dict]:
        return [
            {
                "name": p.name,
                "display_name": p.display_name,
                "available": self.registry.available(p),
                "enabled": p.enabled,
                "is_local": p.is_local,
                "capabilities": p.get_capabilities(),
                "tool_calls": p.supports_tool_calls(),
                "streaming": p.supports_streaming(),
                "default_model": p.model_for("default"),
            }
            for p in self.registry.all()
        ]

    def get_routing_table(self) -> dict[str, list[dict]]:
        return self.registry.routing_table()

    def configure_provider(self, name, **settings):
        from core.agent import AgentBusy
        if not self.agent._lock.acquire(blocking=False):
            raise AgentBusy('Während einer Task-Ausführung können Provider nicht geändert werden.')
        try:
            self.registry.configure(name, **settings)
        finally:
            self.agent._lock.release()

    def set_provider_priority(self, capability, names):
        self.registry.set_priority(capability, names)

    def preview_route(self, text: str, mode: str = "chat") -> dict | None:
        """Welcher Provider würde antworten? (ohne Anfrage zu senden)"""
        d = self.router.route(text, mode)
        if d is None:
            return None
        return {"capability": d.capability, "provider": d.provider.name, "reason": d.reason}

    # --- Memory ---
    def get_personal_memory(self) -> list[dict]:
        return self.longterm.get_all()

    def add_memory(self, content: str, category: str = "general",
                   tags: list[str] | None = None) -> dict:
        return self.longterm.add_fact(content, tags or [], category, privacy="LOCAL_ONLY")

    def propose_memory(self, content, category='user_profile'):
        return self.longterm.add_fact(content, category=category, trust='CANDIDATE', privacy='LOCAL_ONLY',
                                     provenance={'source_type': 'user', 'reference': 'explicit_learning_proposal'})

    def confirm_memory(self, fact_id):
        return self.longterm.confirm(fact_id)

    def set_memory_privacy(self, fact_id, level):
        return self.longterm.set_privacy(fact_id, level)

    def delete_memory(self, fact_id: int) -> bool:
        return self.longterm.delete_fact(fact_id)

    # --- Conversation ---
    def get_conversation(self) -> list[dict]:
        """Verlauf inkl. Timestamp und Meta (z.B. Provider)."""
        return self.conversation.get_all()

    def clear_conversation(self):
        self.conversation.clear()

    # --- Settings ---
    def get_settings(self) -> dict:
        providers = self.get_providers()
        return {
            "app_name": settings.APP_NAME,
            "app_version": settings.APP_VERSION,
            "user_name": settings.USER_NAME,
            "theme": settings.THEME,
            "active_project": (self.projects.get_active() or {}).get("name"),
            "providers": [{"name": p["display_name"], "available": p["available"]} for p in providers],
            "gemini_available": any(p["name"] == "gemini" and p["available"] for p in providers),
        }

    # --- Knowledge (Phase 3) ---
    def get_trust_levels(self) -> dict[str, str]:
        """Trust-Level → deutsche Bezeichnung (für die UI)."""
        return {t: TRUST_LABELS[t] for t in TRUST_LEVELS}

    def get_knowledge_stats(self) -> dict:
        return self.knowledge.stats()

    def list_knowledge(self, project_id: int | None = None, only_global: bool = False,
                       trust: str | None = None, kind: str | None = None, limit: int = 500) -> list[dict]:
        return self.knowledge.list_entries(project_id, only_global, trust, kind, limit)

    def search_knowledge(self, query: str, project_id: int | None = None,
                         all_projects: bool = True, limit: int = 30) -> list[dict]:
        """Suche in der Verwaltung: standardmäßig über alle Projekte, alle Trust-Level außer Veraltet."""
        return self.knowledge.search(query, project_id=project_id, all_projects=all_projects,
                                     exclude_trust=("OUTDATED",), limit=limit)

    def get_knowledge_entry(self, entry_id: int) -> dict | None:
        """Eintrag inkl. sources, versions, conflicts."""
        return self.knowledge.get_entry(entry_id, with_details=True)

    def add_knowledge(self, content: str, title: str = "", topic: str = "", tags: list[str] | None = None,
                      project_id: int | None = None, url: str = "") -> dict:
        """Vom Nutzer eingegebenes Wissen (Trust: CONFIRMED). Rückgabe: {entry, created, conflicts}."""
        return self.knowledge.add_entry(content, title=title, topic=topic, tags=tags,
                                        source_type="user", source_name="Robin", url=url,
                                        project_id=project_id)

    def update_knowledge(self, entry_id: int, content: str | None = None, title: str | None = None,
                         topic: str | None = None, tags: list[str] | None = None) -> dict:
        return self.knowledge.update_entry(entry_id, content=content, title=title, topic=topic, tags=tags)

    def delete_knowledge(self, entry_id: int) -> bool:
        return self.knowledge.delete_entry(entry_id)

    def confirm_knowledge(self, entry_id: int) -> dict:
        return self.knowledge.confirm(entry_id)

    def mark_knowledge_outdated(self, entry_id: int) -> dict:
        return self.knowledge.mark_outdated(entry_id)

    def set_knowledge_trust(self, entry_id: int, trust: str) -> dict:
        return self.knowledge.set_trust(entry_id, trust)

    def add_knowledge_source(self, entry_id: int, source_type: str, name: str = "",
                             url: str = "", reference: str = "") -> dict:
        return self.knowledge.add_source(entry_id, source_type, name, url, reference)

    def set_knowledge_privacy(self, entry_id, level):
        self.privacy.set_entry(entry_id, level)

    def get_knowledge_privacy(self, entry_id):
        return self.privacy.entry_level(entry_id)

    def get_knowledge_history(self, entry_id: int) -> list[dict]:
        return self.knowledge.get_history(entry_id)

    def restore_knowledge_version(self, entry_id: int, version: int) -> dict:
        return self.knowledge.restore_version(entry_id, version)

    def get_conflicts(self, status: str | None = "open") -> list[dict]:
        return self.knowledge.get_conflicts(status)

    def resolve_conflict(self, conflict_id: int, resolution: str) -> dict:
        """resolution: keep_a | keep_b | both_valid"""
        return self.knowledge.resolve_conflict(conflict_id, resolution)

    def ingest_document(self, path: str, project_id: int | None = None, topic: str = "") -> dict:
        """Datei → Wissen. Rückgabe: {document, chunks, skipped}. Kann bei großen PDFs dauern
        (in der UI in einem Hintergrund-Thread aufrufen)."""
        result = self.ingestor.ingest_file(path, project_id, topic)
        if not result['skipped']:
            self.events.emit('document.imported', project_id=project_id)
        return result

    def get_documents(self, project_id: int | None = None) -> list[dict]:
        return self.ingestor.list_documents(project_id)

    def delete_document(self, doc_id: int) -> bool:
        return self.ingestor.delete_document(doc_id)

    # --- Projects (Phase 3) ---
    def get_projects(self, include_archived: bool = False) -> list[dict]:
        return self.projects.list(include_archived)

    def get_project(self, project_id: int) -> dict | None:
        return self.projects.get(project_id)

    def create_project(self, name: str, description: str = "", instructions: str = "", path: str = "", *, auto_workspace=False) -> dict:
        return self.projects.create(name, description, instructions, path, auto_workspace=auto_workspace)

    def update_project(self, project_id: int, **fields) -> dict:
        """Felder: name, description, instructions, path"""
        return self.projects.update(project_id, **fields)

    def archive_project(self, project_id: int) -> dict:
        return self.projects.archive(project_id)

    def unarchive_project(self, project_id: int) -> dict:
        return self.projects.unarchive(project_id)

    def delete_project(self, project_id: int, delete_knowledge: bool = False) -> bool:
        return self.projects.delete(project_id, delete_knowledge)

    def set_active_project(self, project_id: int | None) -> dict | None:
        project = self.projects.set_active(project_id)
        if project:
            self.events.emit('project.activated', project_id=project_id)
        return project

    def get_active_project(self) -> dict | None:
        return self.projects.get_active()

    # --- Tools, Tasks & Automation (Phase 4–6) ---
    def get_tools(self):
        return self.tools.schemas()

    def get_commands(self):
        from config.permissions import COMMANDS
        return COMMANDS.copy()

    def set_path_privacy(self, path, level):
        self.privacy.set(path, level)

    def get_path_privacy(self, path):
        return self.privacy.level(path)

    def get_task_policy_options(self):
        from tasks.policy import MODES, SOURCE_LABELS
        from config.providers import PROVIDER_CONFIG
        providers = list(dict.fromkeys([*PROVIDER_CONFIG, *(p.name for p in self.registry.all())]))
        from capabilities.registry import CAPABILITIES
        return {'modes': list(MODES), 'providers': providers, 'knowledge_sources': SOURCE_LABELS.copy(),
                'capabilities': list(CAPABILITIES)}

    def create_task(self, goal, project_id=None, workflow_id=None, allow_external=False,
                    ai_policy=None, subtasks=None, reference_project_ids=None):
        from tools.safety import Safety
        from tasks.policy import normalize, source_allowed
        project = self.projects.get(project_id) if project_id is not None else self.projects.get_active()
        if not project or project['status'] != 'active' or not project['path']:
            raise ValueError('Ein aktives Projekt mit Arbeitsordner ist erforderlich.')
        root = str(Safety(project['path']).root)
        policy = normalize(ai_policy)
        references = [] if reference_project_ids is None else reference_project_ids
        if (not isinstance(references, list) or len(references) > 10 or
                any(type(i) is not int or not self.projects.get(i) or i == project['id'] for i in references)):
            raise ValueError('Referenzprojekte müssen bis zu zehn andere vorhandene Projekte sein.')
        references = list(dict.fromkeys(references))
        if subtasks is not None and (not isinstance(subtasks, list) or not 1 <= len(subtasks) <= 20):
            raise ValueError('Teilaufgaben müssen eine Liste mit 1–20 Einträgen sein.')
        definitions, seen = [], set()
        for subtask in subtasks or []:
            if not isinstance(subtask, dict) or set(subtask) - {'area', 'goal', 'workflow_id', 'path'}:
                raise ValueError('Ungültige Teilaufgabe.')
            area, subgoal = subtask.get('area'), subtask.get('goal')
            if not isinstance(area, str) or not area.strip() or not isinstance(subgoal, str) or not subgoal.strip():
                raise ValueError('Teilaufgaben benötigen Bereich und konkretes Teilziel.')
            area = area.strip().casefold()
            if area in seen:
                raise ValueError('Jeder Bereich darf nur einmal als Teilaufgabe vorkommen.')
            seen.add(area)
            subroot = root
            if subtask.get('path'):
                subroot = str(Safety(root).path(subtask['path'], directory=True))
            definitions.append((area, subgoal, subtask.get('workflow_id'), subroot))
        if definitions and policy is None:
            raise ValueError('Teilaufgaben benötigen eine explizite Task-Policy.')
        if policy and definitions and set(policy['areas']) - seen:
            raise ValueError('Für jeden geregelten Bereich muss eine konkrete Teilaufgabe vorliegen.')

        def select_workflow(target, workflow_id, area=None, workspace=None):
            if workflow_id:
                return self.workflows.get(workflow_id)
            scope = {'ai_policy': policy, 'policy_area': area}
            return self.decisions.decide(target, project['id'],
                use_experience=source_allowed(scope, 'EXPERIENCE'), root=workspace or root)['workflow']

        with self.db.transaction():
            task = self.tasks.create(goal, project, root,
                None if definitions else select_workflow(goal, workflow_id), allow_external, ai_policy=policy)
            task['reference_project_ids'] = references
            for area, subgoal, subworkflow_id, subroot in definitions:
                child = self.tasks.create(subgoal, project, subroot, select_workflow(subgoal, subworkflow_id, area, subroot),
                    allow_external, ai_policy=policy, policy_area=area, parent_task_id=task['id'])
                child['reference_project_ids'] = references
                self.tasks.save(child)
                task['subtask_ids'].append(child['id'])
            if definitions:
                self.tasks.set_plan(task, [f'{area}: {subgoal}' for area, subgoal, _, _ in definitions])
            elif policy and policy['areas']:
                task['needs_subtask_definition'] = True
                self.tasks.block(task, 'NEEDS_INFORMATION',
                    'Bereichsregeln benötigen konkrete Teilaufgaben. Bitte Aufgabe mit Teilzielen neu anlegen.')
            self.tasks.save(task)
        return self.get_task(task['id'])

    @staticmethod
    def _policy_editable(task):
        return (task['status'] in ('CREATED', 'BLOCKED', 'NEEDS_INFORMATION')
                and not any(task.get(k) for k in ('api_calls','tool_calls','steps','messages','pending','in_flight')))

    def update_task_policy(self, task_id, ai_policy, *, allow_external=None):
        """Atomar vor der ersten Ausführung ändern; alte Aktionen/Provider-Verläufe nie umetikettieren."""
        from core.agent import AgentBusy
        from tasks.policy import normalize
        policy = normalize(ai_policy)
        if policy is None:
            raise ValueError('Eine explizite Policy ist erforderlich.')
        if not self._group_lock.acquire(blocking=False):
            raise AgentBusy('Eine Aufgabe wird ausgeführt; Policy kann jetzt nicht geändert werden.')
        try:
            if not self.agent._lock.acquire(blocking=False):
                raise AgentBusy('Eine Aufgabe wird ausgeführt; Policy kann jetzt nicht geändert werden.')
            try:
                with self.db.transaction():
                    task = self.tasks.get(task_id)
                    if task.get('parent_task_id'):
                        raise ValueError('Bereichspolicies über die Gesamtaufgabe bearbeiten.')
                    children = [self.tasks.get(i) for i in task.get('subtask_ids', [])]
                    if not all(self._policy_editable(t) for t in [task, *children]):
                        raise ValueError('Policy nur vor der ersten Ausführung ändern; danach neue Vorlage verwenden.')
                    if set(policy['areas']) - {c['policy_area'] for c in children}:
                        raise ValueError('Bereichsregeln benötigen bestehende Teilaufgaben.')
                    for target in [task, *children]:
                        target['ai_policy'] = policy
                        if allow_external is not None:
                            target['external'] = bool(allow_external)
                        target['policy_revision'] = target.get('policy_revision', 0) + 1
                        target['local_assessment'] = None
                        target['knowledge_used'] = []
                        for key in ('policy_blocked_ai','policy_blocked_required','needs_subtask_definition','knowledge_gap','last_context'):
                            target.pop(key, None)
                        self.tasks.status(target, 'CREATED')
                        self.trail.add(target['id'], 'policy_updated', {'revision':target['policy_revision']})
                return self.get_task(task_id)
            finally:
                self.agent._lock.release()
        finally:
            self._group_lock.release()

    def get_tasks(self, include_subtasks=False):
        return [self.get_task(t['id']) for t in self.tasks.list()
                if include_subtasks or not t.get('parent_task_id')]

    def get_task(self, task_id):
        from tasks.policy import effective
        task = self.tasks.get(task_id)
        task['effective_policy'] = effective(task)
        task['subtasks'] = [self.tasks.get(i) for i in task.get('subtask_ids', [])]
        task['policy_editable'] = not task.get('parent_task_id') and all(self._policy_editable(t) for t in [task, *task['subtasks']])
        return task

    def run_task(self, task_id, *, approve=None, confirmation_id=None, information=''):
        task = self.tasks.get(task_id)
        if task.get('needs_subtask_definition'):
            return self.get_task(task_id)
        if task.get('subtask_ids'):
            return self._run_subtasks(task_id, approve, confirmation_id, information)
        result = self.agent.run(task_id, approve=approve, confirmation_id=confirmation_id, information=information)
        if result['status'] == 'COMPLETED' and not result.get('parent_task_id'):
            self._prepare_project_storage(result)
            self.events.emit('task.completed', project_id=result['project_id'],
                             origin_schedule=result.get('schedule_id'))
        return result

    def _run_subtasks(self, task_id, approve, confirmation_id, information):
        from core.agent import AgentBusy
        if not self._group_lock.acquire(blocking=False):
            raise AgentBusy('Eine zusammengesetzte Aufgabe wird bereits ausgeführt.')
        try:
            task = self.tasks.get(task_id)
            if task['status'] in TERMINAL:
                raise ValueError('Task ist bereits abgeschlossen.')
            self._group_pauses.discard(task_id)
            previous_status, previous_blocking = task['status'], task['blocking']
            self.tasks.status(task, 'IN_PROGRESS')
            children = [self.tasks.get(i) for i in task['subtask_ids']]
            for child in children:
                if task_id in self._group_pauses or task_id in self._group_cancels:
                    self._stop_group(task)
                    return self.get_task(task_id)
                if child['status'] == 'COMPLETED':
                    continue
                task['active_subtask_id'] = child['id']
                self.tasks.save(task)
                if child['status'] in TERMINAL:
                    result = child
                else:
                    try:
                        result = self.agent.run(child['id'], approve=approve, confirmation_id=confirmation_id,
                                                information=information)
                    except (AgentBusy, ValueError):
                        self.tasks.status(task, previous_status)
                        task['blocking'] = previous_blocking
                        self.tasks.save(task)
                        raise
                    except Exception as exc:
                        self.tasks.block(task, 'BLOCKED', f'Teilaufgabe unterbrochen: {type(exc).__name__}', 'inspect')
                        raise
                approve, confirmation_id, information = None, None, ''
                children = [self.tasks.get(i) for i in task['subtask_ids']]
                task['progress'] = {'percent': int(100 * sum(c['status'] == 'COMPLETED' for c in children) / len(children)),
                    'current_step': child['policy_area'], 'total_steps': len(children),
                    'completed_steps': [c['policy_area'] for c in children if c['status'] == 'COMPLETED']}
                for field in ('api_calls', 'tool_calls', 'steps', 'cost_reserved'):
                    task[field] = sum(c[field] for c in children)
                task['pending'] = result['pending']
                self.tasks.save(task)
                if task_id in self._group_pauses or task_id in self._group_cancels:
                    self._stop_group(task)
                    return self.get_task(task_id)
                if result['status'] != 'COMPLETED':
                    reason = (result.get('blocking') or {}).get('reason') or result['status']
                    self.tasks.block(task, result['status'], f"{child['policy_area']}: {reason}",
                                     (result.get('blocking') or {}).get('action_needed', 'provide_information'))
                    return self.get_task(task_id)
                self.tasks.trail.add(task_id, 'subtask_completed', {'task_id': child['id'], 'area': child['policy_area']})
            if task_id in self._group_pauses or task_id in self._group_cancels:
                self._stop_group(task)
                return self.get_task(task_id)
            task['verified'] = all(c['verified'] and not c['dirty'] for c in children)
            if not task['verified']:
                self.tasks.block(task, 'BLOCKED', 'Nicht alle Teilaufgaben sind verifiziert.')
            else:
                task['result'] = '\n'.join(f"{c['policy_area']}: {c['result']}" for c in children)
                task['tools_used'] = list(dict.fromkeys(t for c in children for t in c.get('tools_used', [])))
                task['knowledge_used'] = [ref for c in children for ref in c.get('knowledge_used', [])]
                task['local_only'] = any(c.get('local_only') for c in children)
                task['read_paths'] = list(dict.fromkeys(p for c in children for p in c.get('read_paths', [])))
                task['progress']['percent'] = 100
                with self.db.transaction():
                    if task_id in self._group_pauses or task_id in self._group_cancels:
                        self._stop_group(task)
                        return self.get_task(task_id)
                    self.tasks.status(task, 'COMPLETED')
                    self.experience.record(task)
                self._prepare_project_storage(task)
                self.events.emit('task.completed', project_id=task['project_id'])
            return self.get_task(task_id)
        finally:
            self._group_lock.release()

    def _stop_group(self, task):
        if task['id'] in self._group_cancels:
            children = [self.tasks.get(i) for i in task['subtask_ids']]
            task['pending'] = None
            task['result'] = '\n'.join(c['result'] for c in children if c['result'])
            task['result'] += '\nAufgabengruppe abgebrochen; bereits ausgeführte Änderungen bleiben erhalten.'
            self.tasks.status(task, 'CANCELLED')
            self._group_cancels.discard(task['id'])
            self._group_pauses.discard(task['id'])
        else:
            self.tasks.status(task, 'PAUSED')

    def cancel_task(self, task_id):
        task = self.tasks.get(task_id)
        if not task.get('subtask_ids'):
            return self.agent.cancel(task_id)
        idle = self._group_lock.acquire(blocking=False)
        try:
            task = self.tasks.get(task_id)
            if task['status'] in TERMINAL:
                raise ValueError('Task ist bereits abgeschlossen.')
            self._group_cancels.add(task_id)
            for child_id in task['subtask_ids']:
                if self.tasks.get(child_id)['status'] not in TERMINAL:
                    try:
                        self.agent.cancel(child_id)
                    except ValueError:
                        if self.tasks.get(child_id)['status'] not in TERMINAL:
                            raise
            if idle:
                self._stop_group(task)
            return self.get_task(task_id)
        finally:
            if idle:
                self._group_lock.release()

    def pause_task(self, task_id):
        with self.db.transaction():
            task = self.tasks.get(task_id)
            if task.get('subtask_ids'):
                if task['status'] in TERMINAL:
                    raise ValueError('Task ist bereits abgeschlossen.')
                self._group_pauses.add(task_id)
                # The runner owns final cancellation and clears its request under the group lock.
                if task_id not in self._group_cancels:
                    self.tasks.status(task, 'PAUSED')
                for child_id in task['subtask_ids']:
                    if self.tasks.get(child_id)['status'] == 'IN_PROGRESS':
                        self.agent.pause(child_id)
                return self.get_task(task_id)
            return self.agent.pause(task_id)


    def set_project_memory_mode(self, project_id, mode):
        return self.projects.set_memory_mode(project_id, mode)

    def find_reference_projects(self, query, project_id=None):
        from tools.safety import ToolBlocked
        result = []
        for project in self.projects.relevant(query, exclude_id=project_id):
            try:
                if project['path']:
                    self.privacy.check(project['path'])
            except ToolBlocked:
                continue
            result.append({'id': project['id'], 'name': project['name'], 'status': project['status']})
        return result

    def set_knowledge_reference(self, entry_id, allowed):
        return self.knowledge.set_reference_allowed(entry_id, allowed)

    def set_experience_reference(self, task_id, allowed):
        return self.experience.set_reference_allowed(task_id, allowed)

    def _prepare_project_storage(self, task):
        """Deterministischer Kandidat aus belegtem Task; keine AI-Ableitung oder globale Regel."""
        if task.get('project_storage'):
            return
        project = self.projects.get(task['project_id'])
        mode = (project or {}).get('memory_mode', 'NEVER')
        relevant = (task['status'] == 'COMPLETED' and task['verified'] and not task['dirty']
                    and bool(task['result'].strip()) and
                    bool(set(task.get('tools_used', [])) & {'write_file', 'edit_file', 'run_build', 'run_tests'}))
        task['project_storage'] = {'status': 'NOT_SELECTED', 'mode': mode}
        if mode != 'NEVER' and relevant and self.context._experience_safe(task['id']):
            task['project_storage'] = {'status': 'PENDING', 'mode': mode,
                'content': f"Task: {task['goal']}\nBeobachtetes Ergebnis: {task['result'][:3000]}\n"
                           'Historische Task-Beobachtung; keine allgemeine Vorgehensregel.',
                'fingerprint': self.experience.fingerprint(self.experience.get(task['id']))}
        self.tasks.save(task)
        if mode == 'AUTO' and task['project_storage']['status'] == 'PENDING':
            self.resolve_project_storage(task['id'], 'save')
            task.update(self.tasks.get(task['id']))

    def resolve_project_storage(self, task_id, decision):
        if decision not in ('save', 'discard', 'experience_only'):
            raise ValueError('Unbekannte Speicherentscheidung.')
        with self.db.transaction():
            task = self.tasks.get(task_id)
            proposal = task.get('project_storage') or {}
            if task['status'] != 'COMPLETED' or proposal.get('status') != 'PENDING':
                raise ValueError('Kein offener Projektspeichervorschlag.')
            if decision == 'save':
                item = self.experience.get(task_id)
                if (not self.projects.get(task['project_id']) or not item or
                        self.experience.fingerprint(item) != proposal['fingerprint'] or
                        not self.context._experience_safe(task_id)):
                    raise ValueError('Projektbelege sind nicht mehr aktuell oder freigegeben.')
                entry = self.knowledge.add_entry(proposal['content'], project_id=task['project_id'],
                    kind='answer', trust='CANDIDATE', source_type='experience', source_name=task_id,
                    reference='derived:experience:' + task_id + '@' + proposal['fingerprint'],
                    check_conflicts=False)['entry']
                self.privacy.set_entry(entry['id'], 'LOCAL_ONLY')
                proposal['entry_id'] = entry['id']
            proposal['status'] = {'save': 'SAVED', 'discard': 'DISCARDED', 'experience_only': 'EXPERIENCE_ONLY'}[decision]
            self.trail.add(task_id, 'project_storage', {'decision': decision, 'entry_id': proposal.get('entry_id')})
            self.tasks.save(task)
        return self.get_task(task_id)

    def get_task_knowledge(self, task_id, *, external=False):
        return self.context.task_sources(self.tasks.get(task_id), external=external)

    def get_activity(self, filter=None):
        return self.trail.list(**(filter or {}))

    def get_experiences(self, query='', project_id=None):
        return self.experience.list(query, project_id)

    def propose_strategy(self, content, experience_ids, *, applicability, rationale, title=''):
        """Speichert einen expliziten Reflexionsvorschlag im bestehenden Knowledge-System."""
        return self.knowledge.add_strategy_candidate(content, experience_ids,
            applicability=applicability, rationale=rationale, title=title)

    def update_memory(self, fact_id, content):
        return self.longterm.update_fact(fact_id, content)

    def save_workflow(self, name, goal, steps, workflow_id=None):
        return self.workflows.save(name, goal, steps, workflow_id)

    def get_workflows(self):
        return self.workflows.list()

    def preview_decision(self, goal, project_id=None):
        return self.decisions.decide(goal, project_id)

    def create_schedule(self, workflow_id, project_id, *, interval=None, event=None):
        project = self.projects.get(project_id)
        if not project or project['status'] != 'active' or not project['path']:
            raise ValueError('Zeitplan benötigt ein aktives Projekt mit Arbeitsordner.')
        return self.scheduler.create(workflow_id, project_id, interval=interval, event=event)

    def get_schedules(self):
        return self.scheduler.list()

    def enable_schedule(self, schedule_id, enabled):
        return self.scheduler.enable(schedule_id, enabled)

    def _scheduled_task(self, workflow_id, project_id, schedule_id):
        workflow = self.workflows.get(workflow_id)
        task = self.create_task(workflow['goal'], project_id, workflow_id)
        task = self.tasks.get(task['id'])
        task['schedule_id'] = schedule_id
        self.tasks.save(task)
        return self.get_task(task['id'])

    def tick_scheduler(self):
        from core.agent import AgentBusy
        self.scheduler.dispatch()
        results = []
        for task in self.tasks.list():
            if task.get('schedule_id') and task['status'] == 'CREATED':
                try:
                    results.append(self.run_task(task['id']))
                except AgentBusy:
                    break  # Agent beschäftigt; nächster Tick übernimmt den Task.
                except Exception as exc:
                    current = self.tasks.get(task['id'])
                    if current['status'] not in TERMINAL:
                        self.tasks.block(current, 'BLOCKED',
                            f'Geplante Ausführung fehlgeschlagen: {type(exc).__name__}: {exc}', 'inspect')
                    # Ein kaputter Task hält unabhängige Zeitpläne nicht auf.
                    continue
        return results

    def close(self):
        self.db.close()
