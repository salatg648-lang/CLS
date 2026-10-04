"""
Dialoge für Knowledge und Projekte (Phase 3).

Enthalten keine Geschäftslogik: sie rufen nur die CLS Core API auf und zeigen
ValueError-Meldungen des Cores verständlich an.
"""

import tkinter as tk
from tkinter import messagebox

import customtkinter as ctk

TRUST_COLORS = {
    "CONFIRMED": "#2fa35b", "SUPPORTED": "#2f8fa3", "UNCERTAIN": "#d98b1f",
    "CONFLICTING": "#d64545", "OUTDATED": "#8a8a8a", "CANDIDATE": "#b89b2b",
}
KIND_LABELS = {"fact": "Fakt", "answer": "AI-Antwort", "chunk": "Dokument-Teil", "strategy": "Strategiekandidat"}
SOURCE_LABELS = {"user": "Nutzer", "document": "Dokument", "ai_provider": "AI",
                 "web": "Web", "system": "System", "experience": "Experience"}


def show_error(message) -> None:
    messagebox.showerror("CLS", str(message))


def snippet(text: str, n: int = 160) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[:n - 1].rstrip() + "…"


def trust_badge(parent, trust: str, labels: dict) -> ctk.CTkLabel:
    return ctk.CTkLabel(parent, text=f" {labels.get(trust, trust)} ", corner_radius=6,
                        fg_color=TRUST_COLORS.get(trust, "gray40"), text_color="white",
                        font=("Arial", 11, "bold"))


class _Dialog(ctk.CTkToplevel):
    def __init__(self, master, title: str, size: str):
        super().__init__(master)
        self.title(title)
        self.geometry(size)
        self.transient(master.winfo_toplevel())
        self._grab_id = self.after(150, self._grab)

    def destroy(self):
        if self._grab_id:
            self.after_cancel(self._grab_id)
            self._grab_id = None
        super().destroy()

    def _grab(self):
        self._grab_id = None
        try:
            self.grab_set()
            self.focus_set()
        except tk.TclError:
            pass  # Fenster wurde schon geschlossen

    def _field(self, label: str, initial: str = "", height: int = 0):
        ctk.CTkLabel(self, text=label, anchor="w").pack(fill="x", padx=20, pady=(10, 2))
        if height:
            box = ctk.CTkTextbox(self, height=height, wrap="word")
            box.pack(fill="x", padx=20)
            box.insert("1.0", initial)
            return box
        entry = ctk.CTkEntry(self)
        entry.pack(fill="x", padx=20)
        entry.insert(0, initial)
        return entry

    @staticmethod
    def _value(widget) -> str:
        return widget.get("1.0", "end").strip() if isinstance(widget, ctk.CTkTextbox) else widget.get().strip()


class EntryDialog(_Dialog):
    """Wissen anlegen oder bearbeiten."""

    def __init__(self, master, cls_core, on_done, entry: dict | None = None):
        super().__init__(master, "Wissen bearbeiten" if entry else "Neues Wissen", "560x560")
        self.cls, self.on_done, self.entry = cls_core, on_done, entry
        self.title_field = self._field("Titel (optional)", entry["title"] if entry else "")
        self.content_field = self._field("Inhalt", entry["content"] if entry else "", height=190)
        self.topic_field = self._field("Thema (optional)", entry["topic"] if entry else "")
        self.tags_field = self._field("Tags (Komma-getrennt)", ", ".join(entry["tags"]) if entry else "")

        self.project_box = None
        active = None if entry else self.cls.get_active_project()
        if active:
            self.project_box = ctk.CTkCheckBox(self, text=f"Zum aktiven Projekt '{active['name']}' hinzufügen")
            self.project_box.select()
            self.project_box.pack(anchor="w", padx=20, pady=(12, 0))
            self._active = active

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.pack(fill="x", padx=20, pady=16)
        ctk.CTkButton(buttons, text="Speichern", width=110, command=self._save).pack(side="right")
        ctk.CTkButton(buttons, text="Abbrechen", width=110, fg_color="gray40",
                      command=self.destroy).pack(side="right", padx=8)

    def _save(self):
        tags = [t.strip() for t in self._value(self.tags_field).split(",") if t.strip()]
        try:
            if self.entry:
                self.cls.update_knowledge(self.entry["id"], content=self._value(self.content_field),
                                          title=self._value(self.title_field),
                                          topic=self._value(self.topic_field), tags=tags)
                note = ""
            else:
                project_id = self._active["id"] if self.project_box and self.project_box.get() else None
                result = self.cls.add_knowledge(
                    self._value(self.content_field), title=self._value(self.title_field),
                    topic=self._value(self.topic_field), tags=tags, project_id=project_id)
                note = self._result_note(result)
        except ValueError as e:
            show_error(e)
            return
        self.destroy()
        if note:
            messagebox.showinfo("CLS", note)
        self.on_done()

    @staticmethod
    def _result_note(result: dict) -> str:
        if not result["created"]:
            return "Das wusste ich schon — ich habe nur die Quelle ergänzt."
        if result["conflicts"]:
            return ("Achtung: Dieser Eintrag widerspricht bestehendem Wissen. "
                    "Beides bleibt erhalten — bitte unter 'Widersprüche' klären.")
        return ""


class EntryDetailDialog(_Dialog):
    """Ein Eintrag mit Quellen, Verlauf und Aktionen."""

    def __init__(self, master, cls_core, entry_id: int, on_change):
        super().__init__(master, f"Wissen #{entry_id}", "640x680")
        self.cls, self.entry_id, self.on_change = cls_core, entry_id, on_change
        self.body = ctk.CTkScrollableFrame(self)
        self.body.pack(fill="both", expand=True, padx=10, pady=10)
        self._render()

    def _render(self):
        for w in self.body.winfo_children():
            w.destroy()
        e = self.cls.get_knowledge_entry(self.entry_id)
        if not e:
            self.destroy()
            return
        labels = self.cls.get_trust_levels()

        top = ctk.CTkFrame(self.body, fg_color="transparent")
        top.pack(fill="x", pady=(0, 6))
        trust_badge(top, e["trust"], labels).pack(side="left")
        meta = f"  #{e['id']} · {KIND_LABELS.get(e['kind'], e['kind'])} · Version {e['current_version']}"
        if e["project_id"]:
            project = self.cls.get_project(e["project_id"])
            meta += f" · Projekt: {project['name'] if project else e['project_id']}"
        ctk.CTkLabel(top, text=meta).pack(side="left")

        ctk.CTkLabel(self.body, text=e["title"], font=("Arial", 15, "bold"), anchor="w",
                     wraplength=560, justify="left").pack(fill="x", pady=(4, 4))
        box = ctk.CTkTextbox(self.body, height=170, wrap="word")
        box.pack(fill="x")
        box.insert("1.0", e["content"])
        box.configure(state="disabled")
        if e["topic"] or e["tags"]:
            ctk.CTkLabel(self.body, anchor="w", text_color="gray60",
                         text=f"Thema: {e['topic'] or '—'}   Tags: {', '.join(e['tags']) or '—'}").pack(fill="x", pady=4)

        for c in e["conflicts"]:
            other = c["b"] if c["a"]["id"] == e["id"] else c["a"]
            ctk.CTkLabel(self.body, anchor="w", justify="left", wraplength=560, text_color="#d64545",
                         text=f"Widerspricht #{other['id']} ({c['reason']}). "
                              "Lösen unter 'Widersprüche'.").pack(fill="x", pady=4)

        self._section("Datenschutz (Dokumentregeln gelten zusätzlich)")
        privacy = ctk.CTkOptionMenu(self.body,
            values=["LOCAL_ONLY", "SAFE_FOR_EXTERNAL", "USER_CONFIRMATION_REQUIRED", "BLOCKED"],
            command=lambda level: self.cls.set_knowledge_privacy(self.entry_id, level))
        privacy.set(self.cls.get_knowledge_privacy(self.entry_id))
        privacy.pack(fill="x", pady=4)

        if e['project_id'] is not None and e['kind'] != 'strategy':
            allowed = ctk.BooleanVar(value=bool(e.get('reference_allowed')))
            ctk.CTkCheckBox(self.body, text='Für ausdrücklich ausgewählte Referenz-Tasks freigeben', variable=allowed,
                command=lambda: self.cls.set_knowledge_reference(self.entry_id, bool(allowed.get()))).pack(anchor='w', pady=6)
        if e.get('strategy'):
            strategy = e['strategy']
            self._section('Vorgehensweise (nicht zur Ausführung freigegeben)')
            scope = strategy['scope']
            text = (f"Status: {strategy['status']} · Confidence: nicht bewertet\n"
                    f"Geltungsbereich: {scope['kind']} / {scope['project_id']}\n"
                    f"Anwendbar: {strategy['applicability']}\nBegründung: {strategy['rationale']}")
            ctk.CTkLabel(self.body, text=text, anchor='w', justify='left', wraplength=560).pack(fill='x', pady=4)

        self._section("Quellen")
        for s in e["sources"]:
            line = f"{SOURCE_LABELS.get(s['source_type'], s['source_type'])}: {s['name'] or '—'}"
            if s["reference"]:
                line += f" ({s['reference']})"
            if s["url"]:
                line += f"\n{s['url']}"
            ctk.CTkLabel(self.body, text=line, anchor="w", justify="left", wraplength=560).pack(fill="x", pady=1)

        self._section("Verlauf (nichts geht verloren)")
        for v in e["versions"]:
            row = ctk.CTkFrame(self.body, fg_color="transparent")
            row.pack(fill="x", pady=1)
            current = v["version"] == e["current_version"]
            text = f"v{v['version']} · {v['created_at'].replace('T', ' ')} · {v['changed_by']} · {v['change_note']}"
            ctk.CTkLabel(row, text=text + ("  (aktuell)" if current else ""), anchor="w").pack(side="left")
            if not current:
                ctk.CTkButton(row, text="Wiederherstellen", width=120, height=24,
                              command=lambda n=v["version"]: self._act(self.cls.restore_knowledge_version,
                                                                       self.entry_id, n)).pack(side="right")

        buttons = ctk.CTkFrame(self.body, fg_color="transparent")
        buttons.pack(fill="x", pady=(16, 4))
        ctk.CTkButton(buttons, text="Bestätigen", width=100,
                      state='disabled' if e['kind'] == 'strategy' else 'normal',
                      command=lambda: self._act(self.cls.confirm_knowledge, self.entry_id)).pack(side="left", padx=(0, 6))
        ctk.CTkButton(buttons, text="Veraltet", width=90, fg_color="gray40",
                      command=lambda: self._act(self.cls.mark_knowledge_outdated, self.entry_id)).pack(side="left", padx=6)
        ctk.CTkButton(buttons, text="Bearbeiten", width=100, fg_color="gray40",
                      state='disabled' if e['kind'] == 'strategy' else 'normal',
                      command=lambda: EntryDialog(self, self.cls, self._changed, entry=e)).pack(side="left", padx=6)
        ctk.CTkButton(buttons, text="Löschen", width=90, fg_color="#a83232",
                      command=self._delete).pack(side="right")

    def _section(self, text: str):
        ctk.CTkLabel(self.body, text=text, font=("Arial", 13, "bold"), anchor="w").pack(fill="x", pady=(14, 2))

    def _act(self, func, *args):
        try:
            func(*args)
        except ValueError as e:
            show_error(e)
            return
        self._changed()

    def _changed(self):
        self.on_change()
        self._render()

    def _delete(self):
        if messagebox.askyesno("CLS", "Diesen Eintrag samt Verlauf endgültig löschen?", parent=self):
            self.cls.delete_knowledge(self.entry_id)
            self.on_change()
            self.destroy()


class ConflictsDialog(_Dialog):
    """Offene Widersprüche lösen."""

    def __init__(self, master, cls_core, on_change):
        super().__init__(master, "Widersprüche", "760x600")
        self.cls, self.on_change = cls_core, on_change
        self.body = ctk.CTkScrollableFrame(self)
        self.body.pack(fill="both", expand=True, padx=10, pady=10)
        self._render()

    def _render(self):
        for w in self.body.winfo_children():
            w.destroy()
        conflicts = self.cls.get_conflicts("open")
        if not conflicts:
            ctk.CTkLabel(self.body, text="Keine offenen Widersprüche.").pack(pady=30)
            return
        labels = self.cls.get_trust_levels()
        for c in conflicts:
            card = ctk.CTkFrame(self.body)
            card.pack(fill="x", pady=6, padx=4)
            ctk.CTkLabel(card, text=c["reason"], font=("Arial", 12, "bold"), anchor="w").pack(
                fill="x", padx=12, pady=(10, 4))
            cols = ctk.CTkFrame(card, fg_color="transparent")
            cols.pack(fill="x", padx=8)
            for side, key in (("A", "a"), ("B", "b")):
                e = c[key]
                col = ctk.CTkFrame(cols)
                col.pack(side="left", fill="both", expand=True, padx=4, pady=4)
                trust_badge(col, e["trust"], labels).pack(anchor="w", padx=8, pady=(8, 2))
                ctk.CTkLabel(col, text=f"{side} · #{e['id']} {e['title']}\n{snippet(e['content'], 220)}",
                             anchor="w", justify="left", wraplength=300).pack(fill="x", padx=8, pady=(0, 8))
            row = ctk.CTkFrame(card, fg_color="transparent")
            row.pack(fill="x", padx=12, pady=(4, 10))
            for text, resolution in (("A behalten", "keep_a"), ("B behalten", "keep_b"), ("Beide gültig", "both_valid")):
                ctk.CTkButton(row, text=text, width=110,
                              command=lambda cid=c["id"], r=resolution: self._resolve(cid, r)).pack(side="left", padx=(0, 8))

    def _resolve(self, conflict_id: int, resolution: str):
        try:
            self.cls.resolve_conflict(conflict_id, resolution)
        except ValueError as e:
            show_error(e)
        self.on_change()
        self._render()


class ProjectDialog(_Dialog):
    """Projekt anlegen oder bearbeiten."""

    def __init__(self, master, cls_core, on_done, project: dict | None = None):
        super().__init__(master, "Projekt bearbeiten" if project else "Neues Projekt", "540x560")
        self.cls, self.on_done, self.project = cls_core, on_done, project
        p = project or {}
        self.name_field = self._field("Name", p.get("name", ""))
        self.desc_field = self._field("Beschreibung", p.get("description", ""), height=80)
        self.instr_field = self._field("Anweisungen für die AI in diesem Projekt (optional)",
                                      p.get("instructions", ""), height=110)
        self.path_field = self._field("Absoluter Projekt-Arbeitsordner (für alle Tools)", p.get("path", ""))

        self.auto_workspace = ctk.BooleanVar(value=False)
        if not project:
            ctk.CTkCheckBox(self, text="Bei leerem Pfad eigenen Workspace aus Projektnamen erstellen",
                           variable=self.auto_workspace).pack(padx=20, pady=4)
        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.pack(fill="x", padx=20, pady=16)
        ctk.CTkButton(buttons, text="Speichern", width=110, command=self._save).pack(side="right")
        ctk.CTkButton(buttons, text="Abbrechen", width=110, fg_color="gray40",
                      command=self.destroy).pack(side="right", padx=8)

    def _save(self):
        fields = dict(name=self._value(self.name_field), description=self._value(self.desc_field),
                      instructions=self._value(self.instr_field), path=self._value(self.path_field))
        try:
            if self.project:
                self.cls.update_project(self.project["id"], **fields)
            else:
                self.cls.create_project(**fields, auto_workspace=bool(self.auto_workspace.get()))
        except (ValueError, OSError) as e:
            show_error(e)
            return
        self.destroy()
        self.on_done()
