"""
Chat Widget — Chatverlauf + Eingabe.

FIX (v0.2): Die AI-Anfrage läuft in einem Hintergrund-Thread, die UI friert
nicht mehr ein. Tkinter wird nur im UI-Thread angefasst: der Thread legt sein
Ergebnis in eine Queue, die UI holt es per after()-Polling ab.
"""

import queue
import threading
import tkinter as tk

import customtkinter as ctk

from infrastructure.logger import get_logger

logger = get_logger(__name__)

POLL_MS = 100
PROVIDER_LABELS = {"gemini": "Gemini", "perplexity": "Perplexity", "cls": "System"}


class ChatWidget(ctk.CTkFrame):
    def __init__(self, master, cls_core, get_mode=lambda: "chat", get_provider=lambda: None, get_local_only=lambda: False, **kwargs):
        super().__init__(master, **kwargs)
        self.cls = cls_core
        self.get_mode = get_mode
        self.get_provider, self.get_local_only = get_provider, get_local_only
        self._busy = False
        self._results: queue.Queue = queue.Queue()
        self._pending_frame = None

        self._build()
        self._load_conversation()

    def _build(self):
        self.chat_frame = ctk.CTkScrollableFrame(self, label_text="")
        self.chat_frame.pack(fill="both", expand=True, padx=10, pady=(10, 5))

        input_frame = ctk.CTkFrame(self, fg_color="transparent")
        input_frame.pack(fill="x", padx=10, pady=(5, 10))

        self.input_entry = ctk.CTkEntry(input_frame, placeholder_text="Schreib was...", height=38)
        self.input_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.input_entry.bind("<Return>", self._on_send)

        self.send_button = ctk.CTkButton(
            input_frame, text="Senden", width=100, height=38, command=self._on_send
        )
        self.send_button.pack(side="right")

    # --- Senden ---

    def _on_send(self, event=None):
        if self._busy:
            return "break"
        text = self.input_entry.get().strip()
        if not text:
            return "break"

        self._add_message(text, is_user=True)
        self.input_entry.delete(0, "end")
        self._set_busy(True)
        self._pending_frame = self._add_message("denkt nach...", is_user=False, sender="CLS")

        mode = self.get_mode()
        self._selection = (self.get_provider(), self.get_local_only())
        threading.Thread(target=self._worker, args=(text, mode), daemon=True).start()
        self.after(POLL_MS, self._poll)
        return "break"

    def _worker(self, text: str, mode: str):
        """Läuft im Hintergrund-Thread — KEIN Tkinter-Zugriff hier!"""
        try:
            provider, local_only = getattr(self, '_selection', (None, False))
            result = self.cls.chat(text, mode, provider=provider, local_only=local_only)
        except Exception as e:  # letzte Sicherung, Core fängt normalerweise selbst
            logger.error(f"Fehler beim Senden: {e}")
            result = {"text": f"Fehler: {e}", "provider": "", "error": True}
        self._results.put(result)

    def _poll(self):
        try:
            result = self._results.get_nowait()
        except queue.Empty:
            try:
                self.after(POLL_MS, self._poll)
            except tk.TclError:
                pass  # View wurde inzwischen gewechselt
            return

        try:
            if self._pending_frame is not None:
                self._pending_frame.destroy()
                self._pending_frame = None
            self._add_message(
                result["text"], is_user=False,
                provider=result.get("provider", ""),
                error=result.get("error", False),
                fallback=result.get("fallback_used", False),
                knowledge=len(result.get("knowledge_used") or []),
                candidate=result.get("candidate_id"),
            )
            self._set_busy(False)
        except tk.TclError:
            pass  # Widget existiert nicht mehr; Antwort steht im Verlauf

    def _set_busy(self, busy: bool):
        self._busy = busy
        state = "disabled" if busy else "normal"
        self.send_button.configure(state=state)
        self.input_entry.configure(state=state)
        if not busy:
            self.input_entry.focus()

    # --- Anzeige ---

    def _add_message(self, text: str, is_user: bool, provider: str = "",
                     error: bool = False, fallback: bool = False, sender: str = "",
                     knowledge: int = 0, candidate: int | None = None):
        if not sender:
            if is_user:
                sender = "Du"
            else:
                name = PROVIDER_LABELS.get(provider, provider.title())
                sender = f"CLS · {name}" if name else "CLS"
                if fallback:
                    sender += " (Fallback)"
                if knowledge:
                    sender += f" · Wissen: {knowledge}"
                if candidate:
                    sender += f" · als Kandidat #{candidate} gespeichert"

        if error:
            color = ("#f7b7b7", "#8a2d2d")
        elif is_user:
            color = ("#7eb8f7", "#1a6ec7")
        else:
            color = ("#7ef7a0", "#2d8a4f")

        frame = ctk.CTkFrame(self.chat_frame, fg_color="transparent")
        frame.pack(fill="x", pady=4)

        ctk.CTkLabel(
            frame,
            text=f"{sender}\n{text}",
            anchor="w",
            justify="left",
            wraplength=560,
            fg_color=color,
            corner_radius=8,
            padx=12,
            pady=8,
        ).pack(anchor="e" if is_user else "w", padx=8)

        self.after(50, self._scroll_down)
        return frame

    def _scroll_down(self):
        try:
            self.chat_frame._parent_canvas.yview_moveto(1.0)
        except (tk.TclError, AttributeError):
            pass

    def _load_conversation(self):
        for msg in self.cls.get_conversation():
            is_user = msg["role"] == "user"
            provider = (msg.get("meta") or {}).get("provider", "")
            knowledge = len((msg.get("meta") or {}).get("knowledge") or [])
            self._add_message(msg["content"], is_user=is_user, provider=provider, knowledge=knowledge)
