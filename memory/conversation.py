"""
Conversation History — Chatverlauf mit Rolling Window.

Nachrichten können Metadaten tragen (z.B. welcher Provider geantwortet hat).
An die KI gehen nur role + content (get_messages), die UI bekommt alles (get_all).
"""

from datetime import datetime
from pathlib import Path

from config.settings import MAX_CONVERSATION_MESSAGES
from infrastructure.paths import CONVERSATION_FILE
from infrastructure.storage import load_json, save_json
from infrastructure.logger import get_logger

logger = get_logger(__name__)


class ConversationHistory:
    def __init__(self, filepath: Path = CONVERSATION_FILE,
                 max_messages: int = MAX_CONVERSATION_MESSAGES, db=None):
        self.db = db
        self.filepath = filepath
        self.max_messages = max_messages
        self.messages: list[dict] = []
        self._load()

    def add(self, role: str, content: str, meta: dict | None = None):
        """Fügt eine Nachricht hinzu und speichert automatisch."""
        entry = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
        }
        if meta:
            entry["meta"] = meta
        self.messages.append(entry)
        self._trim()
        self._save()

    def get_messages(self) -> list[dict]:
        """Nachrichten für die KI (nur role + content)."""
        return [{"role": m["role"], "content": m["content"]} for m in self.messages]

    def get_all(self) -> list[dict]:
        """Komplette Nachrichten inkl. Timestamp/Meta (für die UI)."""
        return list(self.messages)

    def get_recent(self, n: int = 10) -> list[dict]:
        return self.messages[-n:]

    def clear(self):
        self.messages = []
        self._save()
        logger.info("Conversation History gelöscht")

    def _trim(self):
        """Rolling Window. Das Fenster beginnt immer mit einer User-Nachricht
        (manche APIs lehnen einen Verlauf ab, der mit 'assistant' anfängt)."""
        if len(self.messages) <= self.max_messages:
            return
        removed = len(self.messages) - self.max_messages
        self.messages = self.messages[-self.max_messages:]
        while self.messages and self.messages[0]["role"] != "user":
            self.messages.pop(0)
            removed += 1
        logger.debug(f"Rolling Window: {removed} alte Nachrichten entfernt")

    def _save(self):
        if self.db:
            from memory.sqlite_store import save
            save(self.db, 'conversation', self.messages)
        else:
            save_json(self.filepath, self.messages)

    def _load(self):
        if self.db:
            from memory.sqlite_store import load_or_migrate
            data = load_or_migrate(self.db, 'conversation', self.filepath)
        else:
            data = load_json(self.filepath)
        if isinstance(data, list):
            self.messages = data
            logger.debug(f"Conversation geladen: {len(self.messages)} Nachrichten")
