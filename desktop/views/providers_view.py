"""
Providers View (AIs) — zeigt Status und Capabilities aller AI-Provider
und welcher Provider für welche Capability zuerst gefragt wird.
"""

import customtkinter as ctk
from desktop.components.dialogs import _Dialog

CAPABILITY_LABELS = {
    "general_reasoning": "Allgemein",
    "research": "Recherche",
    "web_search": "Web-Suche",
    "coding": "Coding",
    "local_reasoning": "Lokal",
}


class ProvidersView(ctk.CTkFrame):
    def __init__(self, master, cls_core, **kwargs):
        super().__init__(master, **kwargs)
        self.cls = cls_core
        self._build()

    def _build(self):
        for w in self.winfo_children():
            w.destroy()

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(10, 10))
        ctk.CTkLabel(header, text="AIs", font=("Arial", 16, "bold")).pack(side="left")
        ctk.CTkButton(header, text="Aktualisieren", width=110, command=self._build).pack(side="right")

        body = ctk.CTkScrollableFrame(self)
        body.pack(fill="both", expand=True)

        # Provider-Karten
        for p in self.cls.get_providers():
            card = ctk.CTkFrame(body)
            card.pack(fill="x", padx=20, pady=6)

            status = "● konfiguriert (Verbindung ungeprüft)" if p["available"] else "○ deaktiviert oder nicht konfiguriert"
            status_color = ("#2d8a4f", "#7ef7a0") if p["available"] else ("gray50", "gray60")

            top = ctk.CTkFrame(card, fg_color="transparent")
            top.pack(fill="x", padx=15, pady=(10, 2))
            ctk.CTkLabel(top, text=p["display_name"], font=("Arial", 14, "bold")).pack(side="left")
            ctk.CTkLabel(top, text=status, text_color=status_color).pack(side="right")

            ctk.CTkButton(card, text='Konfigurieren', width=120,
                command=lambda provider=p: ProviderDialog(self, self.cls, provider, self._build)).pack(anchor='e', padx=15)
            caps = ", ".join(CAPABILITY_LABELS.get(c, c) for c in p["capabilities"])
            details = [f"Capabilities: {caps}", f"Standard-Modell: {p['default_model']}"]
            ctk.CTkLabel(card, text="\n".join(details), justify="left", anchor="w").pack(
                fill="x", padx=15, pady=(0, 10)
            )

        # Routing-Tabelle
        ctk.CTkLabel(body, text="Routing (wer wird zuerst gefragt?)",
                     font=("Arial", 13, "bold")).pack(anchor="w", padx=20, pady=(16, 4))
        table = ctk.CTkFrame(body)
        table.pack(fill="x", padx=20, pady=(0, 10))
        for capability, providers in self.cls.get_routing_table().items():
            row = ctk.CTkFrame(table, fg_color="transparent")
            row.pack(fill="x", padx=15, pady=4)
            ctk.CTkLabel(row, text=CAPABILITY_LABELS.get(capability, capability),
                         width=110, anchor="w").pack(side="left")
            chain = "  →  ".join(
                p["name"] if p["available"] else f"({p['name']} aus)" for p in providers
            )
            ctk.CTkLabel(row, text=chain, anchor="w").pack(side="left")

        from capabilities.registry import CAPABILITIES
        self.priority_capability = ctk.CTkOptionMenu(body, values=list(CAPABILITIES))
        self.priority_capability.pack(fill='x', padx=20, pady=4)
        self.priority = ctk.CTkEntry(body, placeholder_text='Priorität: gemini, groq, openrouter, ...')
        self.priority.pack(fill='x', padx=20, pady=4)
        ctk.CTkButton(body, text='Priorität speichern', command=self._save_priority).pack(pady=8)

    def _save_priority(self):
        from desktop.components.dialogs import show_error
        try:
            names = [p.strip() for p in self.priority.get().split(',') if p.strip()]
            self.cls.set_provider_priority(self.priority_capability.get(), names)
            self._build()
        except ValueError as exc:
            show_error(exc)


class ProviderDialog(_Dialog):
    def __init__(self, master, cls_core, provider, on_done):
        super().__init__(master, provider['display_name'] + ' konfigurieren', '540x650')
        from capabilities.registry import CAPABILITIES
        self.cls, self.provider, self.on_done = cls_core, provider, on_done
        body = ctk.CTkScrollableFrame(self)
        body.pack(fill='both', expand=True, padx=12, pady=12)
        ctk.CTkLabel(body, text='Lokal' if provider['is_local'] else 'Extern – Privacy-Regeln gelten immer').pack(pady=6)
        self.enabled = ctk.BooleanVar(value=provider['enabled'])
        ctk.CTkCheckBox(body, text='Aktiviert', variable=self.enabled).pack(anchor='w', pady=6)
        ctk.CTkLabel(body, text='Modell (muss beim Provider verfügbar sein)').pack(anchor='w')
        self.model = ctk.CTkEntry(body)
        self.model.pack(fill='x', pady=6)
        self.model.insert(0, provider['default_model'] or '')
        self.capabilities = {}
        for capability in CAPABILITIES:
            if capability == 'local_reasoning' and not provider['is_local']:
                continue
            var = ctk.BooleanVar(value=capability in provider['capabilities'])
            ctk.CTkCheckBox(body, text=CAPABILITY_LABELS.get(capability, capability), variable=var).pack(anchor='w', pady=4)
            self.capabilities[capability] = var
        self.key = None
        if not provider['is_local']:
            ctk.CTkLabel(body, text='Neuer API-Key (leer = bestehenden behalten)').pack(anchor='w', pady=(16, 2))
            self.key = ctk.CTkEntry(body, show='•')
            self.key.pack(fill='x')
            self.remove_key = ctk.BooleanVar(value=False)
            ctk.CTkCheckBox(body, text='Gespeicherten API-Key entfernen', variable=self.remove_key).pack(anchor='w', pady=8)
        ctk.CTkButton(body, text='Speichern', command=self._save).pack(pady=14)

    def _save(self):
        from desktop.components.dialogs import show_error
        try:
            key = ('' if self.remove_key.get() else self.key.get() or None) if self.key else None
            self.cls.configure_provider(self.provider['name'], enabled=bool(self.enabled.get()),
                model=self.model.get().strip() or None,
                capabilities=[c for c, var in self.capabilities.items() if var.get()], api_key=key)
            if self.key:
                self.key.delete(0, 'end')
            self.on_done()
            self.destroy()
        except (ValueError, OSError):
            show_error('Provider konnte nicht gespeichert werden. Modell, Capabilities und .env-Zugriff prüfen.')
