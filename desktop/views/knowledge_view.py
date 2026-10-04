"""
Knowledge View (Phase 3) — Wissen durchsuchen, anlegen, prüfen; Dokumente importieren;
Widersprüche lösen.
"""

import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk

from desktop.components.dialogs import (
    ConflictsDialog, EntryDetailDialog, EntryDialog, KIND_LABELS, show_error, snippet, trust_badge,
)
from infrastructure.logger import get_logger

logger = get_logger(__name__)

POLL_MS = 150
ALL = "Alle"
FILETYPES = [("Dokumente & Text", "*.txt *.md *.pdf *.docx *.py *.java *.kt *.js *.json *.html *.css *.csv *.xml *.yml *.yaml *.gradle"),
             ("Alle Dateien", "*.*")]


class KnowledgeView(ctk.CTkFrame):
    def __init__(self, master, cls_core, **kwargs):
        super().__init__(master, **kwargs)
        self.cls = cls_core
        self.labels = self.cls.get_trust_levels()               # Trust → Anzeigename
        self._by_label = {v: k for k, v in self.labels.items()}
        self._import_results: queue.Queue = queue.Queue()
        self._build()
        self.refresh()

    def _build(self):
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(10, 4))
        ctk.CTkLabel(header, text="Knowledge", font=("Arial", 16, "bold")).pack(side="left")
        self.stats_label = ctk.CTkLabel(header, text="", text_color="gray60")
        self.stats_label.pack(side="left", padx=14)
        self.conflict_button = ctk.CTkButton(header, text="Widersprüche", width=130, fg_color="gray40",
                                             command=self._open_conflicts)
        self.conflict_button.pack(side="right")
        self.import_button = ctk.CTkButton(header, text="Dokument importieren", width=160, fg_color="gray40",
                                           command=self._import)
        self.import_button.pack(side="right", padx=8)
        ctk.CTkButton(header, text="Neu", width=70, command=self._new).pack(side="right")

        filters = ctk.CTkFrame(self, fg_color="transparent")
        filters.pack(fill="x", padx=20, pady=(4, 6))
        self.search_entry = ctk.CTkEntry(filters, placeholder_text="Suchen...")
        self.search_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.search_entry.bind("<Return>", lambda e: self.refresh())
        self.trust_menu = ctk.CTkOptionMenu(filters, values=[ALL] + list(self.labels.values()),
                                            width=190, command=lambda _: self.refresh())
        self.trust_menu.set(ALL)
        self.trust_menu.pack(side="left", padx=(0, 8))
        ctk.CTkButton(filters, text="Suchen", width=80, command=self.refresh).pack(side="left")

        self.list_frame = ctk.CTkScrollableFrame(self)
        self.list_frame.pack(fill="both", expand=True, padx=14, pady=(0, 10))

    # --- Liste ---

    def refresh(self):
        query = self.search_entry.get().strip()
        trust = self._by_label.get(self.trust_menu.get())
        try:
            if query:
                entries = self.cls.search_knowledge(query)
                if trust:
                    entries = [e for e in entries if e["trust"] == trust]
            else:
                entries = self.cls.list_knowledge(trust=trust, limit=200)
            stats = self.cls.get_knowledge_stats()
        except Exception as e:  # UI soll bei einem DB-Problem nicht abstürzen
            logger.error(f"Knowledge laden fehlgeschlagen: {e}")
            show_error(f"Wissen konnte nicht geladen werden: {e}")
            return

        self.stats_label.configure(
            text=f"{stats['total']} Einträge · {stats['by_trust'].get('CANDIDATE', 0)} Kandidaten · "
                 f"{stats['documents']} Dokumente")
        n = stats["open_conflicts"]
        self.conflict_button.configure(text=f"Widersprüche ({n})" if n else "Widersprüche",
                                       fg_color="#a83232" if n else "gray40")

        for w in self.list_frame.winfo_children():
            w.destroy()
        if not entries:
            ctk.CTkLabel(self.list_frame, text="Keine Einträge gefunden." if (query or trust)
                         else "Noch kein Wissen. Klick auf 'Neu' oder importiere ein Dokument.",
                         text_color="gray60").pack(pady=30)
            return
        for e in entries:
            self._card(e)

    def _card(self, e: dict):
        card = ctk.CTkFrame(self.list_frame)
        card.pack(fill="x", pady=4, padx=4)
        top = ctk.CTkFrame(card, fg_color="transparent")
        top.pack(fill="x", padx=10, pady=(8, 2))
        trust_badge(top, e["trust"], self.labels).pack(side="left")
        ctk.CTkLabel(top, text=f"  #{e['id']} · {KIND_LABELS.get(e['kind'], e['kind'])}",
                     text_color="gray60").pack(side="left")
        ctk.CTkButton(top, text="Details", width=80, height=26,
                      command=lambda i=e["id"]: self._details(i)).pack(side="right")
        ctk.CTkLabel(card, text=e["title"], font=("Arial", 13, "bold"), anchor="w",
                     justify="left", wraplength=620).pack(fill="x", padx=10)
        ctk.CTkLabel(card, text=snippet(e["content"]), anchor="w", justify="left",
                     wraplength=620, text_color="gray70").pack(fill="x", padx=10, pady=(0, 8))

    # --- Aktionen ---

    def _new(self):
        EntryDialog(self, self.cls, self.refresh)

    def _details(self, entry_id: int):
        EntryDetailDialog(self, self.cls, entry_id, self.refresh)

    def _open_conflicts(self):
        ConflictsDialog(self, self.cls, self.refresh)

    def _import(self):
        path = filedialog.askopenfilename(title="Dokument importieren", filetypes=FILETYPES)
        if not path:
            return
        project_id, target = None, "global"
        active = self.cls.get_active_project()
        if active:
            answer = messagebox.askyesnocancel(
                "CLS", f"Ins aktive Projekt '{active['name']}' importieren?\n\n"
                       "Ja = nur in diesem Projekt\nNein = global (überall verfügbar)")
            if answer is None:
                return
            if answer:
                project_id, target = active["id"], f"Projekt '{active['name']}'"

        self.import_button.configure(state="disabled", text="Importiere...")
        threading.Thread(target=self._import_worker, args=(path, project_id, target), daemon=True).start()
        self.after(POLL_MS, self._poll_import)

    def _import_worker(self, path: str, project_id, target: str):
        """Hintergrund-Thread — kein Tkinter-Zugriff!"""
        try:
            self._import_results.put((self.cls.ingest_document(path, project_id), target, None))
        except Exception as e:
            self._import_results.put((None, target, e))

    def _poll_import(self):
        try:
            result, target, error = self._import_results.get_nowait()
        except queue.Empty:
            try:
                self.after(POLL_MS, self._poll_import)
            except tk.TclError:
                pass  # Ansicht wurde gewechselt
            return
        try:
            self.import_button.configure(state="normal", text="Dokument importieren")
            if isinstance(error, ValueError):
                show_error(error)                      # erwartbar (z.B. sensible Datei) → Klartext
            elif error:
                logger.error(f"Import fehlgeschlagen: {error}")
                show_error(f"Import fehlgeschlagen: {error}")
            elif result["skipped"]:
                messagebox.showinfo("CLS", f"'{result['document']['filename']}' war in {target} schon importiert.")
            else:
                messagebox.showinfo("CLS", f"'{result['document']['filename']}' importiert "
                                           f"({result['chunks']} Teile) in {target}.")
            self.refresh()
        except tk.TclError:
            pass
