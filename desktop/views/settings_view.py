"""
Settings View — zeigt CLS-Konfiguration (read-only in Phase 1-3).
"""

import customtkinter as ctk


class SettingsView(ctk.CTkFrame):
    def __init__(self, master, cls_core, **kwargs):
        super().__init__(master, **kwargs)
        self.cls = cls_core
        self._build()

    def _build(self):
        ctk.CTkLabel(self, text="Settings", font=("Arial", 16, "bold")).pack(
            pady=(10, 20), padx=20, anchor="w"
        )

        settings = self.cls.get_settings()
        info_frame = ctk.CTkFrame(self)
        info_frame.pack(fill="x", padx=20, pady=10)

        items = [
            ("Name", settings["app_name"]),
            ("Version", settings["app_version"]),
            ("Benutzer", settings["user_name"]),
            ("Theme", settings["theme"]),
            ("Aktives Projekt", settings["active_project"] or "—"),
        ]
        for p in settings["providers"]:
            items.append((p["name"], "verfügbar" if p["available"] else "nicht konfiguriert"))

        for label, value in items:
            row = ctk.CTkFrame(info_frame, fg_color="transparent")
            row.pack(fill="x", padx=15, pady=6)
            ctk.CTkLabel(row, text=label, width=150, anchor="w").pack(side="left")
            ctk.CTkLabel(row, text=str(value), anchor="w").pack(side="left", fill="x", expand=True)

        from desktop.components.dialogs import show_error
        self.privacy_path = ctk.CTkEntry(self, placeholder_text="Datei oder Ordner für Datenschutzregel")
        self.privacy_path.pack(fill="x", padx=20, pady=4)
        self.privacy_level = ctk.CTkOptionMenu(self, values=["LOCAL_ONLY", "SAFE_FOR_EXTERNAL", "USER_CONFIRMATION_REQUIRED", "BLOCKED"])
        self.privacy_level.pack(fill="x", padx=20, pady=4)
        def save_privacy():
            try:
                if not self.privacy_path.get().strip():
                    raise ValueError("Pfad fehlt.")
                self.cls.set_path_privacy(self.privacy_path.get(), self.privacy_level.get())
            except ValueError as exc:
                show_error(exc)
        ctk.CTkButton(self, text="Datenschutzregel speichern", command=save_privacy).pack(pady=4)

        ctk.CTkLabel(
            self,
            text="API-Keys stehen in der .env Datei:\n"
                 "GEMINI_API_KEY, PERPLEXITY_API_KEY, GROQ_API_KEY\nOPENROUTER_API_KEY, COMETAPI_API_KEY\n\n"
                 "Provider, Modelle und Prioritäten: Bereich AIs. Theme: config/settings.py",
            justify="left",
        ).pack(pady=20, padx=20, anchor="w")
