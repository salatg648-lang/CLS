"""Persönliche Fakten bearbeiten; Task-Erfahrungen separat anzeigen."""
import customtkinter as ctk
from tkinter import messagebox
from desktop.components.dialogs import show_error


class MemoryView(ctk.CTkFrame):
    def __init__(self, master, cls_core, **kwargs):
        super().__init__(master, **kwargs)
        self.cls = cls_core
        self.search = ctk.CTkEntry(self, placeholder_text='Memory durchsuchen')
        self.search.pack(fill='x', padx=14, pady=8)
        ctk.CTkButton(self, text='Suchen / Aktualisieren', command=self.refresh).pack(pady=4)
        ctk.CTkButton(self, text='Fakt hinzufügen', command=self._add).pack(pady=4)
        ctk.CTkButton(self, text='Kennenlernen: Information vorschlagen', command=self._propose).pack(pady=4)
        self.body = ctk.CTkScrollableFrame(self)
        self.body.pack(fill='both', expand=True, padx=14, pady=8)
        self.refresh()

    def _add(self):
        text = ctk.CTkInputDialog(text='Neuer persönlicher Fakt:', title='Memory').get_input()
        if text and text.strip():
            self.cls.add_memory(text.strip())
            self.refresh()

    def _propose(self):
        text = ctk.CTkInputDialog(text='Interessen, Arbeitsweise, Kenntnisse, Ziele oder bevorzugte Tools:', title='Kennenlernen').get_input()
        if text and text.strip():
            self.cls.propose_memory(text.strip())
            self.refresh()

    def _confirm(self, fact):
        self.cls.confirm_memory(fact['id'])
        self.refresh()

    def _reference(self, item):
        self.cls.set_experience_reference(item['task_id'], not item['summary'].get('reference_allowed', False))
        self.refresh()

    def _edit(self, fact):
        text = ctk.CTkInputDialog(text='Neuer Inhalt für: ' + fact['content'], title='Memory').get_input()
        if text:
            try:
                self.cls.update_memory(fact['id'], text)
                self.refresh()
            except ValueError as exc:
                show_error(exc)

    def _delete(self, fact):
        if messagebox.askyesno('CLS', 'Diesen Fakt löschen?\n' + fact['content']):
            self.cls.delete_memory(fact['id'])
            self.refresh()

    def refresh(self):
        for widget in self.body.winfo_children():
            widget.destroy()
        query = self.search.get().casefold()
        ctk.CTkLabel(self.body, text='Persönliche Fakten', font=('Arial', 16, 'bold')).pack(anchor='w')
        for fact in self.cls.get_personal_memory():
            if query not in fact['content'].casefold():
                continue
            row = ctk.CTkFrame(self.body)
            row.pack(fill='x', pady=5)
            ctk.CTkLabel(row, text=fact['content'], wraplength=500, justify='left').pack(anchor='w', padx=8)
            ctk.CTkLabel(row, text=f"{fact.get('trust', 'CONFIRMED')} · {fact.get('category', '')}").pack(anchor='w', padx=8)
            if fact.get('trust') == 'CANDIDATE':
                ctk.CTkButton(row, text='Bestätigen', command=lambda f=fact: self._confirm(f)).pack(anchor='w', padx=8)
            privacy = ctk.CTkOptionMenu(row, values=['LOCAL_ONLY', 'SAFE_FOR_EXTERNAL', 'USER_CONFIRMATION_REQUIRED', 'BLOCKED'],
                command=lambda level, i=fact['id']: self.cls.set_memory_privacy(i, level))
            privacy.set(fact.get('privacy', 'SAFE_FOR_EXTERNAL'))
            privacy.pack(anchor='w', padx=8, pady=4)
            ctk.CTkButton(row, text='Bearbeiten', command=lambda f=fact: self._edit(f)).pack(side='left', padx=8, pady=5)
            ctk.CTkButton(row, text='Löschen', command=lambda f=fact: self._delete(f)).pack(side='right', padx=8)
        ctk.CTkLabel(self.body, text='Erfahrungen im aktiven Projekt', font=('Arial', 16, 'bold')).pack(anchor='w', pady=12)
        project = self.cls.get_active_project()
        for item in self.cls.get_experiences(query, project['id'] if project else None):
            ctk.CTkLabel(self.body, text=f"{item['goal']}\n{item['summary']['result']}",
                         wraplength=650, justify='left').pack(anchor='w', pady=6)

            ctk.CTkButton(self.body, text='Referenzfreigabe widerrufen' if item['summary'].get('reference_allowed') else 'Als historische Referenz freigeben',
                command=lambda e=item: self._reference(e)).pack(anchor='w', pady=4)
