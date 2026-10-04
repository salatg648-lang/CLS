"""Task-Bedienung über die Core API; Arbeit läuft außerhalb des Tk-Threads."""
import json
import queue
import threading
from tasks.task_manager import TERMINAL
import customtkinter as ctk
from desktop.components.dialogs import _Dialog, show_error
from desktop.components.task_policy import TaskDialog


class TasksView(ctk.CTkFrame):
    def __init__(self, master, cls_core, **kwargs):
        super().__init__(master, **kwargs)
        self.cls, self.results = cls_core, queue.Queue()
        self._tasks_snapshot = None
        top = ctk.CTkFrame(self)
        top.pack(fill='x', padx=12, pady=12)
        ctk.CTkButton(top, text='Aufgabe erstellen', command=self._create).pack(side='left', padx=8, pady=8)
        ctk.CTkButton(top, text='Workflow / Automation', command=lambda: WorkflowDialog(self, self.cls)).pack(side='left')
        ctk.CTkButton(top, text='Aktualisieren', command=self.refresh).pack(side='right', padx=8)
        self.body = ctk.CTkScrollableFrame(self)
        self.body.pack(fill='both', expand=True, padx=12, pady=8)
        self.refresh()
        self._poll_id = self.after(250, self._poll)

    def _create(self):
        return TaskDialog(self, self.cls, self.refresh)

    def _run(self, task_id, **kwargs):
        def worker():
            try:
                self.cls.run_task(task_id, **kwargs)
                self.results.put(None)
            except Exception as exc:
                self.results.put(str(exc))
        threading.Thread(target=worker, daemon=True).start()

    def _confirm(self, task_id):
        task = self.cls.get_task(task_id)
        pending = task['pending']
        if task.get('active_subtask_id'):
            task = self.cls.get_task(task['active_subtask_id'])
        if not pending:
            return
        detail = json.dumps(pending['arguments'], ensure_ascii=False, indent=2)
        if pending['name'].startswith('run_'):
            command = self.cls.get_commands().get(pending['arguments'].get('command'), {})
            detail += '\nBefehl: ' + ' '.join(command.get('argv', []))
            detail += '\nDieser Befehl führt Projektcode mit deinen Benutzerrechten aus.'
        dialog = _Dialog(self, 'Aktion prüfen', '700x520')
        ctk.CTkLabel(dialog, text=f"{pending['name']} in {task['root']}", wraplength=640).pack(pady=10)
        box = ctk.CTkTextbox(dialog, wrap='word')
        box.pack(fill='both', expand=True, padx=12, pady=8)
        box.insert('1.0', detail)
        box.configure(state='disabled')
        def decide(approved):
            dialog.destroy()
            self._run(task_id, approve=approved, confirmation_id=pending['confirmation_id'])
        ctk.CTkButton(dialog, text='Diese Aktion bestätigen', command=lambda: decide(True)).pack(pady=6)
        ctk.CTkButton(dialog, text='Ablehnen', command=lambda: decide(False)).pack(pady=6)

    def _information(self, task_id):
        value = ctk.CTkInputDialog(text='Information / Hilfe für den Task:', title='CLS').get_input()
        if value:
            self._run(task_id, information=value)

    def refresh(self):
        tasks = self.cls.get_tasks()
        if tasks == self._tasks_snapshot:
            return
        self._tasks_snapshot = tasks
        for widget in self.body.winfo_children():
            widget.destroy()
        if not tasks:
            ctk.CTkLabel(self.body, text='Noch keine Tasks. Zuerst ein Projekt mit Arbeitsordner aktivieren.').pack(pady=20)
        for task in tasks:
            card = ctk.CTkFrame(self.body)
            card.pack(fill='x', pady=6)
            ctk.CTkLabel(card, text=f"{task['goal']}\n{task['status']} · {task['progress']['percent']} %",
                         anchor='w', justify='left', wraplength=650).pack(fill='x', padx=10, pady=8)
            progress = ctk.CTkProgressBar(card)
            progress.pack(fill='x', padx=10)
            progress.set(task['progress']['percent'] / 100)
            text = '\n'.join(task['plan'])
            if task['blocking']:
                text += '\n' + task['blocking']['reason']
            if task['result']:
                text += '\n' + task['result']
            ctk.CTkLabel(card, text=text, anchor='w', justify='left', wraplength=650).pack(fill='x', padx=10)
            row = ctk.CTkFrame(card, fg_color='transparent')
            row.pack(fill='x', padx=10, pady=8)
            tid = task['id']
            if (task.get('project_storage') or {}).get('status') == 'PENDING':
                ctk.CTkLabel(card, text='Relevante Task-Beobachtung als Projektwissen speichern?').pack(anchor='w', padx=10)
                for decision, label in [('save', 'Ja, als Kandidat'), ('discard', 'Nein'), ('experience_only', 'Nur Erfahrungen speichern')]:
                    ctk.CTkButton(card, text=label, command=lambda d=decision, i=tid: self._store(i, d)).pack(anchor='w', padx=10, pady=3)
            if task.get('policy_editable'):
                ctk.CTkButton(row, text='Policy ändern', command=lambda i=tid:
                    TaskDialog(self, self.cls, self.refresh, self.cls.get_task(i), edit=True)).pack(side='left', padx=4)
            ctk.CTkButton(row, text='Policy / Vorlage', command=lambda i=tid:
                TaskDialog(self, self.cls, self.refresh, self.cls.get_task(i))).pack(side='left', padx=4)
            if task['status'] not in TERMINAL:
                ctk.CTkButton(row, text='Abbrechen', command=lambda i=tid: self._cancel(i)).pack(side='right', padx=4)
            if task['pending'] and task['status'] not in TERMINAL:
                ctk.CTkButton(row, text='Aktion prüfen', command=lambda i=tid: self._confirm(i)).pack(side='left')
            elif task['status'] not in TERMINAL | {'IN_PROGRESS'}:
                ctk.CTkButton(row, text='Start / Fortsetzen', command=lambda i=tid: self._run(i)).pack(side='left')
                ctk.CTkButton(row, text='Information geben', command=lambda i=tid: self._information(i)).pack(side='left', padx=6)
            if task['status'] not in TERMINAL | {'PAUSED'}:
                ctk.CTkButton(row, text='Pausieren', command=lambda i=tid: self._pause(i)).pack(side='right')

    def _cancel(self, task_id):
        try:
            self.cls.cancel_task(task_id)
            self.refresh()
        except ValueError as exc:
            show_error(exc)

    def _store(self, task_id, decision):
        try:
            self.cls.resolve_project_storage(task_id, decision)
            self.refresh()
        except ValueError as exc:
            show_error(exc)

    def _pause(self, task_id):
        try:
            self.cls.pause_task(task_id)
            self.refresh()
        except ValueError as exc:
            show_error(exc)

    def _poll(self):
        try:
            while True:
                error = self.results.get_nowait()
                if error:
                    show_error(error)
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.refresh()
            self._poll_id = self.after(1500, self._poll)

    def destroy(self):
        if self._poll_id:
            self.after_cancel(self._poll_id)
        super().destroy()


class WorkflowDialog(_Dialog):
    def __init__(self, master, cls_core):
        super().__init__(master, 'Workflows und Zeitpläne', '760x730')
        self.cls = cls_core
        self.name = self._field('Workflow-Name')
        self.goal = self._field('Ziel (exakte Übereinstimmung für automatische Auswahl)')
        self.steps = self._field('Schritte (JSON: tool + args)',
            '[{"tool": "search_files", "args": {"pattern": "*.py"}}]', height=140)
        ctk.CTkButton(self, text='Workflow speichern', command=self._save).pack(pady=8)
        self.workflow = ctk.CTkOptionMenu(self, values=['Workflow wählen'])
        self.workflow.pack(fill='x', padx=20)
        self.trigger = self._field('Intervall in Sekunden (mind. 60) oder Eventname', '3600')
        ctk.CTkLabel(self, text='Events: project.activated · document.imported · task.completed').pack()
        ctk.CTkButton(self, text='Zeitplan für aktives Projekt anlegen', command=self._schedule).pack(pady=8)
        self.body = ctk.CTkScrollableFrame(self, height=130)
        self.body.pack(fill='both', expand=True, padx=12, pady=8)
        self._refresh()

    def _refresh(self):
        workflows = self.cls.get_workflows()
        self.choices = {w['name']: w['id'] for w in workflows}
        values = list(self.choices) or ['Workflow wählen']
        self.workflow.configure(values=values)
        self.workflow.set(values[0])
        for widget in self.body.winfo_children():
            widget.destroy()
        for schedule in self.cls.get_schedules():
            label = f"{schedule['event'] or str(schedule['interval']) + ' s'} · {'aktiv' if schedule['enabled'] else 'pausiert'}"
            ctk.CTkButton(self.body, text=label,
                command=lambda s=schedule: self._toggle(s)).pack(fill='x', pady=3)

    def _save(self):
        try:
            self.cls.save_workflow(self.name.get(), self.goal.get(), json.loads(self.steps.get('1.0', 'end')))
            self._refresh()
        except (ValueError, TypeError) as exc:
            show_error(exc)

    def _schedule(self):
        try:
            project = self.cls.get_active_project()
            if not project:
                raise ValueError('Kein aktives Projekt.')
            workflow = self.choices.get(self.workflow.get())
            if not workflow:
                raise ValueError('Workflow wählen.')
            value = self.trigger.get().strip()
            trigger = {'interval': int(value)} if value.isdigit() else {'event': value}
            self.cls.create_schedule(workflow, project['id'], **trigger)
            self._refresh()
        except ValueError as exc:
            show_error(exc)

    def _toggle(self, schedule):
        self.cls.enable_schedule(schedule['id'], not schedule['enabled'])
        self._refresh()
