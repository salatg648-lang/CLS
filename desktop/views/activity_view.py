"""Action-Trail-Ansicht mit Task- und Ereignisfilter."""
import json
import customtkinter as ctk


class ActivityView(ctk.CTkFrame):
    def __init__(self, master, cls_core, **kwargs):
        super().__init__(master, **kwargs)
        self.cls = cls_core
        self.task = ctk.CTkEntry(self, placeholder_text='Task-ID (leer = alle)')
        self.task.pack(fill='x', padx=14, pady=8)
        self.kind = ctk.CTkEntry(self, placeholder_text='Art: tool, error, ai_call, status …')
        self.kind.pack(fill='x', padx=14, pady=8)
        ctk.CTkButton(self, text='Filtern / Aktualisieren', command=self.refresh).pack(pady=8)
        self.output = ctk.CTkTextbox(self, wrap='word')
        self.output.pack(fill='both', expand=True, padx=14, pady=8)
        self.refresh()
        self._poll_id = self.after(1500, self._poll)

    def refresh(self):
        rows = self.cls.get_activity({'task_id': self.task.get().strip() or None,
                                     'kind': self.kind.get().strip() or None})
        rendered = '\n\n'.join(f"{r['created_at']} · {r['task_id']} · {r['kind']}\n"
            + json.dumps(r['detail'], ensure_ascii=False) for r in rows) or 'Noch keine Aktivität.'
        if rendered == getattr(self, '_rendered', None):
            return
        position = self.output.yview()
        self.output.configure(state='normal')
        self.output.delete('1.0', 'end')
        self.output.insert('1.0', rendered)
        if position:
            self.output.yview_moveto(position[0])
        self.output.configure(state='disabled')
        self._rendered = rendered

    def _poll(self):
        if self.winfo_exists():
            self.refresh()
            self._poll_id = self.after(1500, self._poll)

    def destroy(self):
        if self._poll_id:
            self.after_cancel(self._poll_id)
        super().destroy()
