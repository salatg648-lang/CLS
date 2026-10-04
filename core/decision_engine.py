"""Deterministische Wiederverwendung: nur passende, vom Nutzer gespeicherte Workflows."""


class DecisionEngine:
    def __init__(self, workflows, experience):
        self.workflows, self.experience = workflows, experience

    def decide(self, goal, project_id=None, *, use_experience=True, root=None):
        normal = ' '.join(goal.casefold().split())
        for item in (self.experience.list(project_id=project_id) if use_experience else []):
            if (' '.join(item['goal'].casefold().split()) == normal and item['summary']['verified']
                    and item['summary']['status'] == 'COMPLETED' and item['workflow_id']):
                try:
                    workflow = self.workflows.get(item['workflow_id'])
                except ValueError:
                    continue
                if ' '.join(workflow['goal'].casefold().split()) == normal:
                    return {'kind': 'workflow', 'workflow': workflow, 'reason': 'Verifizierte Erfahrung'}
        for workflow in self.workflows.list():
            if ' '.join(workflow['goal'].casefold().split()) == normal:
                return {'kind': 'workflow', 'workflow': workflow, 'reason': 'Gespeicherter Workflow'}
        from core.planner import local_plan
        if root is None and project_id is not None:
            project = self.workflows.db.query_one('SELECT path FROM projects WHERE id=?', (project_id,))
            root = (project or {}).get('path')
        local = local_plan(goal, root)
        if local and local.get('session_action'):
            local = {'id': None, 'steps': [], 'error': 'Projektwechsel und Sitzungsabfragen bitte im Chat ausführen; Task-Workspaces bleiben fest.'}
        if local is not None:
            return {'kind': 'local', 'workflow': local, 'reason': 'Strukturierte lokale Aktion'}
        return {'kind': 'ai', 'workflow': None, 'reason': 'Kein passender lokaler Ablauf bekannt'}
