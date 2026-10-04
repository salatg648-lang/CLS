"""
Sidebar — Navigationsleiste für das CLS Hauptfenster.

Zweck: Zeigt alle Bereiche von CLS an.
Aktiv: Chat, Projects, Knowledge (Phase 3), AIs (Phase 2) und Settings.
Spätere Bereiche sind sichtbar aber ausgegraut (deaktiviert).
"""

import customtkinter as ctk
from infrastructure.logger import get_logger

logger = get_logger(__name__)


class Sidebar(ctk.CTkFrame):
    """Navigations-Sidebar mit allen CLS-Bereichen."""

    # Alle Bereiche: (key, label, aktiv)
    SECTIONS = [
        ("chat", "Chat", True),
        ("tasks", "Tasks", True),
        ("projects", "Projects", True),
        ("knowledge", "Knowledge", True),
        ("memory", "Memory", True),
        ("activity", "Activity", True),
        ("providers", "AIs", True),
        ("settings", "Settings", True),
    ]

    def __init__(self, master, on_select_callback=None, **kwargs):
        super().__init__(master, width=200, **kwargs)
        self.on_select_callback = on_select_callback
        self.active_section = "chat"
        self.buttons: dict[str, ctk.CTkButton] = {}

        self._build()

    def _build(self):
        """Baut die Sidebar-Elemente."""
        # Titel
        title = ctk.CTkLabel(self, text="CLS", font=("Arial", 20, "bold"))
        title.pack(pady=(20, 30), padx=20, anchor="w")

        # Bereich-Buttons
        for key, label, active in self.SECTIONS:
            btn = ctk.CTkButton(
                self,
                text=label,
                anchor="w",
                height=36,
                corner_radius=8,
                state="normal" if active else "disabled",
                fg_color="transparent" if key != self.active_section else ("gray30", "gray70"),
                hover_color=("gray25", "gray65"),
                text_color_disabled=("gray50", "gray50"),
                command=lambda k=key: self._on_click(k),
            )
            btn.pack(pady=2, padx=12, fill="x")
            self.buttons[key] = btn

    def _on_click(self, key: str):
        """Wird aufgerufen, wenn ein Bereich geklickt wird."""
        if key == self.active_section:
            return

        # Aktiven Button aktualisieren
        for k, btn in self.buttons.items():
            if k == key:
                btn.configure(fg_color=("gray30", "gray70"))
            else:
                btn.configure(fg_color="transparent")

        self.active_section = key

        if self.on_select_callback:
            self.on_select_callback(key)

    def get_active_section(self) -> str:
        """Gibt den aktuell aktiven Bereich zurück."""
        return self.active_section
