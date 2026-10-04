"""
Chat View — Chat mit Modus-Wechsler (Phase 2).

Chat     = automatisches Routing anhand des Textes
Research = Recherche-Capability erzwingen
Coding   = Coding-Capability erzwingen
"""

import customtkinter as ctk

from desktop.components.chat_widget import ChatWidget
from infrastructure.logger import get_logger

logger = get_logger(__name__)

MODE_LABELS = {"chat": "Chat", "research": "Research", "coding": "Coding"}
_LABEL_TO_MODE = {v: k for k, v in MODE_LABELS.items()}


class ChatView(ctk.CTkFrame):
    _last_mode = "chat"  # Modus bleibt beim Wechsel der Ansicht erhalten

    def __init__(self, master, cls_core, **kwargs):
        super().__init__(master, **kwargs)
        self.cls = cls_core
        self._build()

    def _build(self):
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(10, 5))

        ctk.CTkLabel(header, text="Chat", font=("Arial", 16, "bold")).pack(side="left")
        project = self.cls.get_active_project()
        ctk.CTkLabel(header, text=f"Projekt: {project['name']}" if project else "kein aktives Projekt",
                     text_color="gray60").pack(side="left", padx=14)

        self.mode_button = ctk.CTkSegmentedButton(
            header,
            values=[MODE_LABELS[m] for m in self.cls.get_modes()],
            command=self._on_mode_change,
        )
        self.mode_button.set(MODE_LABELS[ChatView._last_mode])
        self.mode_button.pack(side="right")

        selection = ctk.CTkFrame(self, fg_color='transparent')
        selection.pack(fill='x', padx=20, pady=4)
        self.provider = ctk.CTkOptionMenu(selection, values=['Automatic'] + [p['name'] for p in self.cls.get_providers()])
        self.provider.set('Automatic')
        self.provider.pack(side='left')
        self.local_only = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(selection, text='Nur lokale Provider', variable=self.local_only).pack(side='left', padx=12)
        self.chat = ChatWidget(self, self.cls, get_mode=self.get_mode,
            get_provider=lambda: None if self.provider.get() == 'Automatic' else self.provider.get(),
            get_local_only=lambda: bool(self.local_only.get()))
        self.chat.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def get_mode(self) -> str:
        return ChatView._last_mode

    def _on_mode_change(self, label: str):
        ChatView._last_mode = _LABEL_TO_MODE.get(label, "chat")
        logger.debug(f"Chat-Modus: {ChatView._last_mode}")
