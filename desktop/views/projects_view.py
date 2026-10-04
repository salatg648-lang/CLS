"""Projects View (Phase 3) — Projekte verwalten und das aktive Projekt wählen."""

from tkinter import messagebox

import customtkinter as ctk

from desktop.components.dialogs import ProjectDialog, show_error, snippet


class ProjectsView(ctk.CTkFrame):
    def __init__(self, master, cls_core, **kwargs):
        super().__init__(master, **kwargs)
        self.cls = cls_core
        self._show_archived = False
        self._build()

    def _build(self):
        for w in self.winfo_children():
            w.destroy()

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(10, 4))
        ctk.CTkLabel(header, text="Projects", font=("Arial", 16, "bold")).pack(side="left")
        ctk.CTkButton(header, text="Neues Projekt", width=120,
                      command=lambda: ProjectDialog(self, self.cls, self._build)).pack(side="right")
        switch = ctk.CTkSwitch(header, text="Archivierte zeigen", command=self._toggle_archived)
        if self._show_archived:
            switch.select()
        switch.pack(side="right", padx=16)

        active = self.cls.get_active_project()
        info = (f"Aktives Projekt: {active['name']} — sein Kontext und Wissen fließen in jede Anfrage."
                if active else "Kein aktives Projekt — CLS nutzt nur globales Wissen.")
        ctk.CTkLabel(self, text=info, text_color="gray60", anchor="w").pack(fill="x", padx=20, pady=(0, 6))

        body = ctk.CTkScrollableFrame(self)
        body.pack(fill="both", expand=True, padx=14, pady=(0, 10))
        projects = self.cls.get_projects(include_archived=self._show_archived)
        if not projects:
            ctk.CTkLabel(body, text="Noch keine Projekte.", text_color="gray60").pack(pady=30)
        for p in projects:
            self._card(body, p)

    def _card(self, parent, p: dict):
        archived = p["status"] != "active"
        card = ctk.CTkFrame(parent)
        card.pack(fill="x", pady=5, padx=4)

        top = ctk.CTkFrame(card, fg_color="transparent")
        top.pack(fill="x", padx=12, pady=(10, 2))
        ctk.CTkLabel(top, text=p["name"], font=("Arial", 14, "bold")).pack(side="left")
        if p["is_active"]:
            ctk.CTkLabel(top, text=" AKTIV ", corner_radius=6, fg_color="#2fa35b", text_color="white",
                         font=("Arial", 11, "bold")).pack(side="left", padx=8)
        if archived:
            ctk.CTkLabel(top, text=" archiviert ", corner_radius=6, fg_color="gray40",
                         text_color="white").pack(side="left", padx=8)
        ctk.CTkLabel(top, text=f"{p['knowledge_count']} Wissenseinträge", text_color="gray60").pack(side="right")

        if p["description"]:
            ctk.CTkLabel(card, text=snippet(p["description"], 200), anchor="w", justify="left",
                         wraplength=620, text_color="gray70").pack(fill="x", padx=12)

        modes = {'Nie': 'NEVER', 'Nachfragen': 'ASK', 'Automatisch (Kandidaten)': 'AUTO'}
        storage = ctk.CTkOptionMenu(card, values=list(modes),
            command=lambda value, i=p['id']: self._act(self.cls.set_project_memory_mode, i, modes[value]))
        storage.set(next(label for label, value in modes.items() if value == p.get('memory_mode', 'ASK')))
        storage.pack(anchor='w', padx=12, pady=5)
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=(8, 10))
        if not archived:
            if p["is_active"]:
                ctk.CTkButton(row, text="Deaktivieren", width=110, fg_color="gray40",
                              command=lambda: self._act(self.cls.set_active_project, None)).pack(side="left")
            else:
                ctk.CTkButton(row, text="Aktivieren", width=110,
                              command=lambda i=p["id"]: self._act(self.cls.set_active_project, i)).pack(side="left")
        ctk.CTkButton(row, text="Bearbeiten", width=100, fg_color="gray40",
                      command=lambda proj=p: ProjectDialog(self, self.cls, self._build, project=proj)).pack(side="left", padx=6)
        if archived:
            ctk.CTkButton(row, text="Wiederherstellen", width=130, fg_color="gray40",
                          command=lambda i=p["id"]: self._act(self.cls.unarchive_project, i)).pack(side="left")
        else:
            ctk.CTkButton(row, text="Archivieren", width=100, fg_color="gray40",
                          command=lambda i=p["id"]: self._act(self.cls.archive_project, i)).pack(side="left")
        ctk.CTkButton(row, text="Löschen", width=90, fg_color="#a83232",
                      command=lambda proj=p: self._delete(proj)).pack(side="right")

    def _toggle_archived(self):
        self._show_archived = not self._show_archived
        self._build()

    def _act(self, func, *args):
        try:
            func(*args)
        except ValueError as e:
            show_error(e)
        self._build()

    def _delete(self, p: dict):
        answer = messagebox.askyesnocancel(
            "CLS", f"Projekt '{p['name']}' löschen?\n\n"
                   f"Ja = auch die {p['knowledge_count']} Wissenseinträge löschen\n"
                   "Nein = Wissen stillgelegt mit Herkunft behalten\nAbbrechen = nichts tun")
        if answer is None:
            return
        self._act(self.cls.delete_project, p["id"], answer)
