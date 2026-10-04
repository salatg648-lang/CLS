"""
Desktop App — Hauptfenster der CLS Desktop-Anwendung.

Zweck: Initialisiert das Hauptfenster mit Sidebar und Inhaltsbereich.
Wechselt zwischen den verschiedenen Ansichten (Chat, Settings, etc.).

Die UI ruft NUR die CLS Core API (core.api.CLSCore) auf.
Keine Geschäftslogik in der UI.
"""

import customtkinter as ctk
import threading
from desktop.views.tasks_view import TasksView
from desktop.views.memory_view import MemoryView
from desktop.views.activity_view import ActivityView
from core.api import CLSCore
from desktop.components.sidebar import Sidebar
from desktop.views.chat_view import ChatView
from desktop.views.knowledge_view import KnowledgeView
from desktop.views.projects_view import ProjectsView
from desktop.views.providers_view import ProvidersView
from desktop.views.settings_view import SettingsView
from config import settings as cfg
from infrastructure.logger import get_logger

logger = get_logger(__name__)


class CLSDesktopApp:
    """Hauptfenster der CLS Desktop-Anwendung."""

    def __init__(self):
        # CustomTkinter Setup
        ctk.set_appearance_mode(cfg.THEME)
        ctk.set_default_color_theme(cfg.COLOR_THEME)

        # Hauptfenster
        self.root = ctk.CTk()
        self.root.title("CLS — Personal AI System")
        self.root.geometry(cfg.WINDOW_SIZE)
        self.root.minsize(*cfg.WINDOW_MIN_SIZE)

        # CLS Core initialisieren
        self.cls = CLSCore()
        from tools.clipboard import attach
        attach(self.root, self.cls.tools.clipboard)

        # Layout bauen
        self._build_layout()

        # Standard-Ansicht: Chat
        self._show_view("chat")

        self._scheduler_busy = False
        self._closing = False
        self.root.protocol('WM_DELETE_WINDOW', self._close)
        self.root.after(1000, self._tick)
        logger.info("CLS Desktop App gestartet")

    def _build_layout(self):
        """Baut das Hauptlayout: Sidebar links, Inhalt rechts."""
        # Sidebar
        self.sidebar = Sidebar(
            self.root,
            on_select_callback=self._show_view,
        )
        self.sidebar.pack(side="left", fill="y")

        # Trennlinie
        separator = ctk.CTkFrame(self.root, width=1)
        separator.pack(side="left", fill="y")

        # Inhaltsbereich
        self.content_frame = ctk.CTkFrame(self.root, fg_color="transparent")
        self.content_frame.pack(side="right", fill="both", expand=True)

    def _show_view(self, view_key: str):
        """Wechselt zur ausgewählten Ansicht."""
        # Aktuelle Ansicht entfernen
        for widget in self.content_frame.winfo_children():
            widget.destroy()

        # Neue Ansicht anzeigen
        if view_key == "chat":
            ChatView(self.content_frame, self.cls).pack(fill="both", expand=True)
        elif view_key == "tasks":
            TasksView(self.content_frame, self.cls).pack(fill="both", expand=True)
        elif view_key == "memory":
            MemoryView(self.content_frame, self.cls).pack(fill="both", expand=True)
        elif view_key == "activity":
            ActivityView(self.content_frame, self.cls).pack(fill="both", expand=True)
        elif view_key == "knowledge":
            KnowledgeView(self.content_frame, self.cls).pack(fill="both", expand=True)
        elif view_key == "projects":
            ProjectsView(self.content_frame, self.cls).pack(fill="both", expand=True)
        elif view_key == "providers":
            ProvidersView(self.content_frame, self.cls).pack(fill="both", expand=True)
        elif view_key == "settings":
            SettingsView(self.content_frame, self.cls).pack(fill="both", expand=True)
        else:
            # Noch nicht implementiert (spätere Phase)
            placeholder = ctk.CTkLabel(
                self.content_frame,
                text=f"{view_key.title()} — verfügbar in einer späteren Phase",
                font=("Arial", 14),
            )
            placeholder.pack(expand=True)

        logger.debug(f"Ansicht gewechselt: {view_key}")

    def run(self):
        """Startet die Anwendung."""
        self.root.mainloop()

    def _tick(self):
        if self._closing:
            return
        if not self._scheduler_busy:
            self._scheduler_busy = True
            def worker():
                try:
                    self.cls.tick_scheduler()
                except Exception:
                    logger.exception('Scheduler-Tick fehlgeschlagen')
                finally:
                    self._scheduler_busy = False
            threading.Thread(target=worker, daemon=True).start()
        self.root.after(1000, self._tick)

    def _close(self):
        self._closing = True
        for task in self.cls.get_tasks():
            if task['status'] == 'IN_PROGRESS':
                self.cls.pause_task(task['id'])
        # Kein DB-close, solange ein Worker noch schreiben könnte; Prozessende schließt SQLite.
        self.root.destroy()
