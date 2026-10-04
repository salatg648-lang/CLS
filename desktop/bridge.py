"""Local JSON-lines transport for the desktop. All operations use CLSCore.

No HTTP listener, eval, arbitrary getattr or tool-execution shortcut. The native
host owns file dialogs/clipboard. UI requests cannot choose Python call targets.
"""
import json
import threading
from concurrent.futures import ThreadPoolExecutor

# Explicit UI API surface. Private methods, tool execution and DB access are absent.
METHODS = frozenset('''chat get_settings get_providers get_routing_table configure_provider set_provider_priority
get_personal_memory add_memory propose_memory confirm_memory set_memory_privacy delete_memory update_memory
get_conversation clear_conversation get_knowledge_stats list_knowledge search_knowledge get_knowledge_entry
add_knowledge update_knowledge delete_knowledge confirm_knowledge mark_knowledge_outdated set_knowledge_trust
add_knowledge_source set_knowledge_privacy get_knowledge_privacy get_knowledge_history restore_knowledge_version
get_conflicts resolve_conflict ingest_document get_documents delete_document
get_projects get_project create_project update_project archive_project unarchive_project delete_project
set_active_project get_active_project get_tools get_commands get_task_policy_options create_task update_task_policy
get_tasks get_task run_task pause_task cancel_task set_project_memory_mode resolve_project_storage get_task_knowledge
get_activity get_experiences propose_strategy set_knowledge_reference set_experience_reference
save_workflow get_workflows create_schedule get_schedules enable_schedule set_path_privacy get_path_privacy'''.split())
MAX_MESSAGE = 2_000_000


class DesktopBridge:
    def __init__(self, core, *, demo=False):
        self.core, self.demo = core, demo
        self.methods = {name: getattr(core, name) for name in METHODS}

    def dispatch(self, method, params):
        if not isinstance(method, str) or not isinstance(params, dict):
            raise ValueError('Ungültige Desktop-Anfrage.')
        if method == 'snapshot':
            if params:
                raise ValueError('Snapshot akzeptiert keine Parameter.')
            return dict(settings=self.core.get_settings(), projects=self.core.get_projects(include_archived=True),
                        activeProject=self.core.get_active_project(), tasks=self.core.get_tasks(),
                        knowledge=self.core.list_knowledge(limit=500), memory=self.core.get_personal_memory(),
                        providers=self.core.get_providers(), activity=self.core.get_activity(),
                        experiences=[item for scope in [None, *(p['id'] for p in self.core.get_projects(include_archived=True))]
                                     for item in self.core.get_experiences(project_id=scope)], conversation=self.core.get_conversation(),
                        stats=self.core.get_knowledge_stats(), conflicts=self.core.get_conflicts(),
                        workflows=self.core.get_workflows(), schedules=self.core.get_schedules(),
                        routing=self.core.get_routing_table(), documents=self.core.get_documents(), demo=self.demo)
        if method not in self.methods:
            raise ValueError('Diese Desktop-Aktion ist nicht freigegeben.')
        if self.demo:
            if method in {'configure_provider', 'set_provider_priority', 'ingest_document', 'set_path_privacy'}:
                raise ValueError('Diese Systemaktion ist nur in der installierten Desktop-App verfügbar.')
            if method == 'create_task':
                params = {**params, 'allow_external': False, 'ai_policy': {'mode': 'NEVER', 'local_only': True}}
            if method == 'chat':
                params = {**params, 'local_only': True}
            if method in {'create_schedule', 'enable_schedule', 'update_task_policy'}:
                raise ValueError('Automationen und Provider-Policies werden in der Vorschau nicht aktiviert.')
        return self.methods[method](**params)


def seed_preview(core, root):
    """Explicit synthetic preview only. Successes come from real local workflows."""
    if core.get_projects(include_archived=True):
        return
    from config import paths
    paths.ALLOWED_ROOTS = [str(root)]
    paths.WORKSPACE_BASE = root
    definitions = [('CLS Workspace', 'Dein persönlicher Arbeitsraum für Ideen, Wissen und lokale Aufgaben.'),
                   ('Website Relaunch', 'Konzept, Inhalte und technische Entscheidungen an einem Ort.'),
                   ('Research Lab', 'Recherche sammeln, Erkenntnisse prüfen und Wissen verbinden.')]
    projects = []
    for name, description in definitions:
        folder = root / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'notizen.md').write_text('# Nächste Schritte\n\nEin klarer Workspace. Nachvollziehbare Ergebnisse.\n', encoding='utf-8')
        projects.append(core.create_project(name, description, path=str(folder)))
    core.set_active_project(projects[0]['id'])
    for goal in ('Lies notizen.md', 'Zeige Dateien im Projekt'):
        task = core.create_task(goal, ai_policy={'mode': 'NEVER'})
        core.run_task(task['id'])
    task = core.create_task('Erstelle Ordner Entwürfe', ai_policy={'mode': 'NEVER'})
    core.run_task(task['id'])
    for goal, project in [('Notizen für die nächste Recherche strukturieren', projects[2]),
                          ('Inhalte und Seitenstruktur planen', projects[1]),
                          ('Projektentscheidungen dokumentieren', projects[0])]:
        core.create_task(goal, project_id=project['id'], ai_policy={'mode': 'NEVER'})
    for title, content, topic in [
        ('Ein Workspace, klare Grenzen', 'Dateiaktionen bleiben im gewählten Projekt-Workspace.', 'Arbeitsweise'),
        ('Verifikation vor Erfolg', 'Nach schreibenden Aktionen wird der tatsächliche Zustand geprüft.', 'Sicherheit'),
        ('Wissen braucht Herkunft', 'Quellen, Projektbezug und Vertrauensstatus bleiben nachvollziehbar.', 'Wissen')]:
        core.add_knowledge(content, title=title, topic=topic, project_id=projects[0]['id'])
    core.propose_memory('Ich bevorzuge kurze, nachvollziehbare Antworten.', 'preference')
    core.propose_memory('Ich möchte lokale Modelle für private Projekte nutzen.', 'goals')


def serve(core, input_stream, output_stream, *, demo=False):
    bridge = DesktopBridge(core, demo=demo)
    output_lock = threading.Lock()
    stop = threading.Event()
    callbacks, callback_lock = {}, threading.Lock()
    slots = threading.BoundedSemaphore(32)
    executor = ThreadPoolExecutor(max_workers=4)

    def send(payload):
        encoded = json.dumps(payload, ensure_ascii=False)
        with output_lock:
            output_stream.write(encoded + '\n')
            output_stream.flush()

    def clipboard(operation, content):
        import uuid
        from tools.safety import ToolBlocked
        ident, event = uuid.uuid4().hex, threading.Event()
        holder = {}
        with callback_lock:
            callbacks[ident] = (event, holder)
        try:
            send({'event': 'clipboard', 'id': ident, 'operation': operation, 'content': content})
            if not event.wait(10) or holder.get('error'):
                raise ToolBlocked('Native Zwischenablage ist nicht verfügbar.')
            return holder.get('result')
        finally:
            with callback_lock:
                callbacks.pop(ident, None)
    core.tools.clipboard.dispatch = clipboard

    def execute(request):
        ident = request.get('id')
        try:
            result = bridge.dispatch(request.get('method'), request.get('params', {}))
            send({'id': ident, 'result': result})
        except (ValueError, OSError, TypeError) as exc:
            message = 'Provider-Einstellungen konnten nicht gespeichert werden.' if request.get('method') == 'configure_provider' else str(exc)
            send({'id': ident, 'error': message or 'Aktion konnte nicht ausgeführt werden.'})
        except Exception:
            send({'id': ident, 'error': 'Interner Fehler. Bitte den lokalen CLS-Status prüfen.'})
        finally:
            slots.release()

    def scheduler():
        while not stop.wait(1):
            try:
                core.tick_scheduler()
            except Exception:
                pass  # Core records task errors; transport must remain alive.
    ticker = threading.Thread(target=scheduler, daemon=True)
    if not demo:
        ticker.start()
    send({'event': 'ready'})
    try:
        while True:
            line = input_stream.readline(MAX_MESSAGE + 1)
            if not line:
                break
            if len(line) > MAX_MESSAGE:
                send({'id': None, 'error': 'Desktop-Anfrage ist zu groß.'})
                break
            try:
                request = json.loads(line)
                if not isinstance(request, dict):
                    raise ValueError()
            except ValueError:
                send({'id': None, 'error': 'Ungültiges Nachrichtenformat.'})
                continue
            if request.get('kind') == 'shutdown':
                break
            if request.get('kind') == 'clipboard_result':
                with callback_lock:
                    item = callbacks.get(request.get('id'))
                    if item:
                        item[1].update(result=request.get('result'), error=request.get('error'))
                        item[0].set()
                continue
            if not isinstance(request.get('id'), str) or not slots.acquire(blocking=False):
                send({'id': request.get('id'), 'error': 'Zu viele parallele Aktionen. Bitte warten.'})
                continue
            executor.submit(execute, request)
    finally:
        stop.set()
        for task in core.get_tasks(include_subtasks=True):
            if task['status'] == 'IN_PROGRESS':
                try:
                    core.pause_task(task['id'])
                except ValueError:
                    pass
        executor.shutdown(wait=True)
        if ticker.is_alive():
            ticker.join()
        core.close()


def main():
    import argparse
    import os
    import sys
    from pathlib import Path
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir')
    parser.add_argument('--demo', action='store_true')
    args = parser.parse_args()
    if args.data_dir:
        os.environ['CLS_DATA_DIR'] = str(Path(args.data_dir).resolve())
    # Existing console logging must not corrupt the JSON protocol.
    protocol = sys.stdout
    sys.stdout = sys.stderr
    from core.api import CLSCore
    from infrastructure.paths import DATA
    DATA.mkdir(parents=True, exist_ok=True)
    if args.demo:
        from config import paths
        from capabilities.registry import CapabilityRegistry
        root = DATA / 'workspaces'
        root.mkdir(exist_ok=True)
        paths.ALLOWED_ROOTS, paths.WORKSPACE_BASE = [str(root)], root
        from config.permissions import PERMISSIONS
        PERMISSIONS.update(execute='never', network='never')
        from capabilities.registry import create_provider
        from config.providers import ACTIVE_PROVIDERS
        registry = CapabilityRegistry()
        for name in ACTIVE_PROVIDERS:
            registry.register(create_provider(name, {'enabled': False}, ''))
        core = CLSCore(registry=registry, env_path=DATA / '.env')
        seed_preview(core, root)
    else:
        core = CLSCore(env_path=DATA / '.env' if args.data_dir else None)
    serve(core, sys.stdin, protocol, demo=args.demo)


if __name__ == '__main__':
    main()
