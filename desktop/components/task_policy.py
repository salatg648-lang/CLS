"""Task-Dialog: Policy-Daten gehen ausschließlich über die bestehende Core API."""
import customtkinter as ctk
from desktop.components.dialogs import _Dialog, show_error

MODE_LABELS = {'NEVER': 'Keine KI', 'FALLBACK': 'KI nur wenn nötig', 'ALLOWED': 'KI erlaubt'}


class PolicyEditor(ctk.CTkFrame):
    def __init__(self, master, options, policy=None, *, area=False):
        super().__init__(master)
        policy = policy or {}
        self.area = area
        self.mode = ctk.StringVar(value=policy.get('mode', 'INHERIT' if area else 'FALLBACK'))
        ctk.CTkLabel(self, text='KI-Nutzung').pack(anchor='w', padx=10)
        modes = {'INHERIT': 'Task-Einstellung übernehmen', **MODE_LABELS} if area else MODE_LABELS
        for mode, label in modes.items():
            ctk.CTkRadioButton(self, text=label, variable=self.mode, value=mode).pack(anchor='w', padx=12, pady=3)
        self.provider_override = ctk.BooleanVar(value=not area or 'allowed_providers' in policy)
        if area:
            ctk.CTkCheckBox(self, text='Eigene Provider-Auswahl (sonst Task-Einstellung)',
                variable=self.provider_override, command=self._providers_visibility).pack(anchor='w', padx=10, pady=6)
        self.provider_frame = ctk.CTkFrame(self, fg_color='transparent')
        ctk.CTkLabel(self.provider_frame, text='Provider (optional; keine Auswahl = alle verfügbaren und erlaubten)').pack(anchor='w')
        selected = policy.get('allowed_providers')
        self.deny_providers = ctk.BooleanVar(value=selected == [])
        ctk.CTkCheckBox(self.provider_frame, text='Alle Provider sperren', variable=self.deny_providers).pack(anchor='w', pady=2)
        self.providers = {}
        for provider in list(dict.fromkeys([*options['providers'], *(selected or [])])):
            variable = ctk.BooleanVar(value=selected is not None and provider in selected)
            ctk.CTkCheckBox(self.provider_frame, text=provider.capitalize(), variable=variable).pack(anchor='w', pady=2)
            self.providers[provider] = variable
        self.routing_override = ctk.BooleanVar(value=not area or any(k in policy for k in
            ('preferred_providers', 'selected_provider', 'required_capability', 'local_only', 'allow_external')))
        if area:
            ctk.CTkCheckBox(self, text='Eigene Routing-Regeln (sonst Task-Regeln)', variable=self.routing_override).pack(anchor='w', padx=10)
        routing = ctk.CTkFrame(self)
        routing.pack(fill='x', padx=10, pady=6)
        ctk.CTkLabel(routing, text='Provider: Automatic oder feste manuelle Auswahl').pack(anchor='w')
        self.selected_provider = ctk.CTkOptionMenu(routing, values=['Automatic'] + options['providers'])
        self.selected_provider.set(policy.get('selected_provider') or 'Automatic')
        self.selected_provider.pack(fill='x', pady=4)
        self.preferred = field(routing, 'Bevorzugte Provider (Reihenfolge, durch Komma getrennt)',
                               ', '.join(policy.get('preferred_providers', [])))
        self.capability = ctk.CTkOptionMenu(routing, values=['Automatic'] + options.get('capabilities', []))
        self.capability.set(policy.get('required_capability') or 'Automatic')
        self.capability.pack(fill='x', pady=4)
        self.local_only = ctk.BooleanVar(value=policy.get('local_only', False))
        self.allow_external = ctk.BooleanVar(value=policy.get('allow_external', True))
        ctk.CTkCheckBox(routing, text='Nur lokale Provider', variable=self.local_only).pack(anchor='w', pady=4)
        ctk.CTkCheckBox(routing, text='Externe Provider erlaubt (Privacy gilt zusätzlich)', variable=self.allow_external).pack(anchor='w', pady=4)
        self.knowledge_frame = ctk.CTkFrame(self, fg_color='transparent')
        self.knowledge_frame.pack(fill='x', padx=10, pady=8)
        selection = policy.get('knowledge_sources', 'ALL_AVAILABLE')
        self.knowledge_mode = ctk.StringVar(value='ALL_AVAILABLE' if selection == 'ALL_AVAILABLE' else 'RESTRICTED')
        for value, text in [('ALL_AVAILABLE', 'Alle verfügbaren Wissensquellen'), ('RESTRICTED', 'Wissensquellen einschränken')]:
            ctk.CTkRadioButton(self.knowledge_frame, text=text, variable=self.knowledge_mode,
                value=value, command=self._knowledge_visibility).pack(anchor='w', pady=3)
        self.sources_frame = ctk.CTkFrame(self.knowledge_frame, fg_color='transparent')
        self.sources = {}
        for source, label in options['knowledge_sources'].items():
            variable = ctk.BooleanVar(value=selection == 'ALL_AVAILABLE' or source in selection)
            ctk.CTkCheckBox(self.sources_frame, text=label, variable=variable).pack(anchor='w', pady=2)
            self.sources[source] = variable
        self._providers_visibility()
        self._knowledge_visibility()

    def _providers_visibility(self):
        self.provider_frame.pack_forget()
        if self.provider_override.get():
            self.provider_frame.pack(fill='x', padx=10, pady=6, before=self.knowledge_frame)

    def _knowledge_visibility(self):
        self.sources_frame.pack_forget()
        if self.knowledge_mode.get() == 'RESTRICTED':
            self.sources_frame.pack(fill='x', padx=18, pady=4)

    def value(self):
        rule = {}
        if self.mode.get() != 'INHERIT':
            rule['mode'] = self.mode.get()
        if self.provider_override.get():
            rule['allowed_providers'] = ([] if self.deny_providers.get() else
                ([p for p, var in self.providers.items() if var.get()] or None))
        if self.routing_override.get():
            rule.update(selected_provider=None if self.selected_provider.get() == 'Automatic' else self.selected_provider.get(),
                preferred_providers=[p.strip() for p in self.preferred.get().split(',') if p.strip()],
                required_capability=None if self.capability.get() == 'Automatic' else self.capability.get(),
                local_only=bool(self.local_only.get()), allow_external=bool(self.allow_external.get()))
        rule['knowledge_sources'] = ('ALL_AVAILABLE' if self.knowledge_mode.get() == 'ALL_AVAILABLE'
            else [s for s, var in self.sources.items() if var.get()])
        return rule


def field(parent, label, value=''):
    ctk.CTkLabel(parent, text=label).pack(anchor='w', padx=10)
    entry = ctk.CTkEntry(parent)
    entry.pack(fill='x', padx=10, pady=(0, 6))
    entry.insert(0, value)
    return entry


class AreaEditor(ctk.CTkFrame):
    def __init__(self, master, options, remove, *, name='', policy=None, subtask=None):
        super().__init__(master)
        subtask = subtask or {}
        self.name = field(self, 'Bereich (z. B. Backend)', name)
        self.goal = field(self, 'Konkretes Teilziel', subtask.get('goal', ''))
        self.path = field(self, 'Optional: Arbeitsordner relativ zum Projekt', subtask.get('path', ''))
        self.policy = PolicyEditor(self, options, policy, area=True)
        self.policy.pack(fill='x', padx=6, pady=6)
        self.remove_button = ctk.CTkButton(self, text='Bereich entfernen', command=lambda: remove(self))
        self.remove_button.pack(pady=6)


class TaskDialog(_Dialog):
    def __init__(self, master, cls_core, on_done=lambda: None, task=None, *, edit=False):
        super().__init__(master, 'Policy bearbeiten' if edit else 'Aufgabe erstellen' if task is None else 'Gespeicherte Policy / neue Vorlage', '820x850')
        self.edit_id = task['id'] if edit and task else None
        self.cls, self.on_done = cls_core, on_done
        self.options = self.cls.get_task_policy_options()
        self.areas = []
        task = task or {}
        body = ctk.CTkScrollableFrame(self)
        body.pack(fill='both', expand=True, padx=12, pady=12)
        self.goal = field(body, 'Ziel im aktiven Projekt', task.get('goal', ''))
        if task:
            ctk.CTkLabel(body, text='Regeln der bestehenden Aufgabe bearbeiten.' if edit else
                'Gespeicherte Regeln geladen. Speichern erstellt eine neue Aufgabe.', wraplength=720).pack()
        if edit:
            self.goal.configure(state='disabled')
        self.references = {}
        self.reference_body = ctk.CTkFrame(body, height=1, fg_color='transparent')
        self.reference_body.pack(fill='x', pady=6)
        if not edit:
            ctk.CTkButton(body, text='Relevante Referenzprojekte suchen', command=self._find_references).pack(pady=4)
        for identity in task.get('reference_project_ids', []):
            project = self.cls.get_project(identity)
            if project:
                self._add_reference(project)
        self.policy = PolicyEditor(body, self.options, task.get('ai_policy') or task.get('effective_policy') or {})
        self.policy.pack(fill='x', pady=8)
        self.external = ctk.BooleanVar(value=bool(task.get('external')))
        ctk.CTkCheckBox(body, variable=self.external,
            text='Bestätigungspflichtige Projektinhalte für externe KI freigeben').pack(anchor='w', pady=8)
        ctk.CTkLabel(body, text='LOCAL_ONLY und BLOCKED bleiben gesperrt. „Keine KI“ sperrt auch lokale Modelle.',
                     wraplength=720, justify='left').pack(anchor='w')
        ctk.CTkLabel(body, text='Bereiche sind eigene Teilaufgaben. Ohne Ordnerangabe gilt der Projektordner.\n'
            'Ohne eigene KI-/Provider-Regel gilt der Task-Default; Wissen bleibt standardmäßig vollständig verfügbar.',
            wraplength=720, justify='left').pack(anchor='w', pady=8)
        self.area_body = ctk.CTkFrame(body, fg_color='transparent')
        self.area_body.pack(fill='x')
        if not edit:
            ctk.CTkButton(body, text='+ Bereich / Subtask hinzufügen', command=self.add_area).pack(pady=8)
        ctk.CTkButton(self, text='Policy speichern' if edit else 'Aufgabe erstellen', command=self._save).pack(pady=12)
        from pathlib import Path
        for child in task.get('subtasks', []):
            data = dict(child)
            try:
                data['path'] = str(Path(child['root']).relative_to(task['root']))
            except ValueError:
                data['path'] = ''
            name = child['policy_area']
            self.add_area(name=name, policy=(task.get('ai_policy') or task.get('effective_policy') or {}).get('areas', {}).get(name), subtask=data)

    def _add_reference(self, project, selected=True):
        if project['id'] in self.references:
            return
        var = ctk.BooleanVar(value=selected)
        ctk.CTkCheckBox(self.reference_body, text=f"{project['name']} (nur freigegebene Referenzen)", variable=var,
                       state='disabled' if self.edit_id else 'normal').pack(anchor='w', pady=3)
        self.references[project['id']] = var

    def _find_references(self):
        project = self.cls.get_active_project()
        for candidate in self.cls.find_reference_projects(self.goal.get(), (project or {}).get('id')):
            self._add_reference(candidate, selected=False)

    def add_area(self, *, name='', policy=None, subtask=None):
        if len(self.areas) >= 20:
            show_error('Höchstens 20 Bereiche pro Aufgabe.')
            return
        area = AreaEditor(self.area_body, self.options, self.remove_area, name=name, policy=policy, subtask=subtask)
        if self.edit_id:
            for entry in (area.name, area.goal, area.path):
                entry.configure(state='disabled')
            area.remove_button.configure(state='disabled')
        area.pack(fill='x', pady=8)
        self.areas.append(area)
        return area

    def remove_area(self, area):
        self.areas.remove(area)
        area.destroy()

    def _save(self):
        try:
            policy, subtasks = self.policy.value(), []
            policy['areas'] = {}
            for area in self.areas:
                name = area.name.get().strip().casefold()
                if not name or name in policy['areas']:
                    raise ValueError('Jeder Bereich braucht einen eindeutigen Namen.')
                policy['areas'][name] = area.policy.value()
                subtasks.append({'area': name, 'goal': area.goal.get(), 'path': area.path.get().strip()})
            if self.edit_id:
                task = self.cls.update_task_policy(self.edit_id, policy, allow_external=self.external.get())
            else:
                task = self.cls.create_task(self.goal.get(), ai_policy=policy,
                    allow_external=self.external.get(), subtasks=subtasks or None,
                    reference_project_ids=[i for i, var in self.references.items() if var.get()])
            self.on_done()
            self.destroy()
            return task
        except (ValueError, OSError) as exc:
            show_error(exc)
