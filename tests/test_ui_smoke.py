"""
UI-Smoke-Test OHNE Display: customtkinter/tkinter werden durch Stubs ersetzt.
Spielt Views und Dialoge gegen den ECHTEN Core (In-Memory-DB) durch und fängt so Tippfehler,
falsche API-Namen und Logikfehler ab. Layout/Optik prüft das NICHT — dafür `python main.py`.
"""

import importlib
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from capabilities.registry import CapabilityRegistry
from core.api import CLSCore
from infrastructure.database import Database
from memory.conversation import ConversationHistory
from memory.longterm import LongTermMemory

CREATED: list = []
MB_CALLS: list = []
MB_ANSWERS = {"yesno": True, "yesnocancel": True, "file": ""}


class Stub:
    def __init__(self, *args, **kwargs):
        self._args, self._kw, self._calls = args, kwargs, []
        self._get_value = kwargs.get("value", "")
        CREATED.append(self)

    def destroy(self):
        self._calls.append(("destroy", (), {}))

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)

        def method(*a, **k):
            self._calls.append((name, a, k))
            if name == "set":
                self._get_value = a[0]
            if name == "insert":
                self._get_value = a[1]
            if name == "get":
                return getattr(self, "_get_value", "")
            if name == "winfo_children":
                return []
            if name == "winfo_toplevel":
                return self
            return None
        return method


def _make_ctk():
    class Module(types.ModuleType):
        def __getattr__(self, name):
            if name.startswith("__"):
                raise AttributeError(name)
            cls = type(name, (Stub,), {})
            setattr(self, name, cls)
            return cls
    return Module("customtkinter")


def _make_tk():
    tk = types.ModuleType("tkinter")
    tk.TclError = type("TclError", (Exception,), {})
    mb, fd = types.ModuleType("tkinter.messagebox"), types.ModuleType("tkinter.filedialog")
    mb.showerror = lambda t, m, **k: MB_CALLS.append(("error", str(m)))
    mb.showinfo = lambda t, m, **k: MB_CALLS.append(("info", str(m)))
    mb.askyesno = lambda *a, **k: MB_ANSWERS["yesno"]
    mb.askyesnocancel = lambda *a, **k: MB_ANSWERS["yesnocancel"]
    fd.askopenfilename = lambda **k: MB_ANSWERS["file"]
    tk.messagebox, tk.filedialog = mb, fd
    return tk, mb, fd


_saved: dict = {}
_NAMES = ("customtkinter", "tkinter", "tkinter.messagebox", "tkinter.filedialog")


def setUpModule():
    for n in _NAMES:
        _saved[n] = sys.modules.get(n)
    tk, mb, fd = _make_tk()
    sys.modules.update({"customtkinter": _make_ctk(), "tkinter": tk,
                        "tkinter.messagebox": mb, "tkinter.filedialog": fd})
    _drop_desktop()


def tearDownModule():
    _drop_desktop()
    for n, mod in _saved.items():
        if mod is None:
            sys.modules.pop(n, None)
        else:
            sys.modules[n] = mod


def _drop_desktop():
    for name in [m for m in sys.modules if m == "desktop" or m.startswith("desktop.")]:
        del sys.modules[name]


class UISmoke(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.d = d
        self.cls = CLSCore(registry=CapabilityRegistry(), conversation=ConversationHistory(d / "c.json"),
                           longterm=LongTermMemory(d / "l.json"), db=Database(":memory:"),
                           documents_dir=d / "docs")
        MB_CALLS.clear()
        MB_ANSWERS.update(yesno=True, yesnocancel=True, file="")
        CREATED.clear()
        self.master = Stub()
        self.KV = importlib.import_module("desktop.views.knowledge_view")
        self.PV = importlib.import_module("desktop.views.projects_view")
        self.D = importlib.import_module("desktop.components.dialogs")
        self.CW = importlib.import_module("desktop.components.chat_widget")

    def tearDown(self):
        self.cls.db.close()
        self.tmp.cleanup()

    def texts(self):
        return [o._kw.get("text", "") for o in CREATED if "text" in o._kw]

    def seed(self):
        self.project = self.cls.create_project("Mod", description="Ein Mod")
        self.cls.set_active_project(self.project["id"])
        self.a = self.cls.add_knowledge("Fabric API benötigt Java 17")["entry"]
        self.b = self.cls.add_knowledge("Fabric API benötigt Java 21")["entry"]   # Widerspruch (beide CONFIRMED → beide flagged)
        self.cls.knowledge.add_ai_candidate("Was ist Yarn?", "y" * 300, "gemini")

    # --- Knowledge View ---

    def test_knowledge_view_lists_entries_stats_and_conflict_button(self):
        self.seed()
        view = self.KV.KnowledgeView(self.master, self.cls)
        stats = [k["text"] for n, a, k in view.stats_label._calls if n == "configure"][-1]
        self.assertIn("3 Einträge", stats)
        self.assertIn("1 Kandidaten", stats)
        button = [k for n, a, k in view.conflict_button._calls if n == "configure"][-1]
        self.assertEqual(button["text"], "Widersprüche (1)")
        self.assertTrue(any("Fabric API benötigt Java 17" in t for t in self.texts()))

    def test_knowledge_view_search_filter_and_empty_state(self):
        self.seed()
        view = self.KV.KnowledgeView(self.master, self.cls)
        CREATED.clear()
        view.search_entry._get_value = "Yarn"
        view.refresh()
        shown = " ".join(self.texts())
        self.assertIn("Was ist Yarn?", shown)
        self.assertNotIn("Java 17", shown)
        CREATED.clear()
        view.search_entry._get_value = "Quokka"
        view.refresh()
        self.assertIn("Keine Einträge gefunden.", self.texts())

    def test_import_flow_success_duplicate_and_refusal(self):
        self.seed()
        f = self.d / "notiz.txt"
        f.write_text("Ein Dokument über Mixins.", encoding="utf-8")
        view = self.KV.KnowledgeView(self.master, self.cls)

        def run_import(path):
            MB_ANSWERS["file"] = str(path)
            view._import()
            for _ in range(200):
                if view._import_results.qsize():
                    break
                time.sleep(0.01)
            view._poll_import()

        MB_ANSWERS["yesnocancel"] = True            # ins aktive Projekt
        run_import(f)
        self.assertTrue(any(k == "info" and "importiert" in m and "Mod" in m for k, m in MB_CALLS))
        self.assertEqual(self.cls.get_documents(self.project["id"])[0]["filename"], "notiz.txt")
        run_import(f)
        self.assertTrue(any("schon importiert" in m for k, m in MB_CALLS))
        env = self.d / ".env"
        env.write_text("KEY=1", encoding="utf-8")
        run_import(env)
        self.assertTrue(any(k == "error" and "sensibl" in m for k, m in MB_CALLS))
        MB_ANSWERS["yesnocancel"] = None            # Abbrechen → nichts passiert
        before = len(self.cls.get_documents())
        MB_ANSWERS["file"] = str(self.d / "andere.txt")
        (self.d / "andere.txt").write_text("x", encoding="utf-8")
        view._import()
        self.assertEqual(len(self.cls.get_documents()), before)

    # --- Dialoge ---

    def test_entry_dialog_create_error_and_edit(self):
        done = []
        dlg = self.D.EntryDialog(self.master, self.cls, lambda: done.append(1))
        dlg._save()                                                 # leerer Inhalt → Fehlermeldung, kein Schließen
        self.assertTrue(any(k == "error" for k, m in MB_CALLS))
        self.assertEqual(done, [])
        dlg.content_field._get_value = "Neuer Fakt"
        dlg.tags_field._get_value = "a, b"
        dlg._save()
        self.assertEqual(done, [1])
        entry = self.cls.list_knowledge()[0]
        self.assertEqual((entry["content"], entry["tags"]), ("Neuer Fakt", ["a", "b"]))
        edit = self.D.EntryDialog(self.master, self.cls, lambda: done.append(2), entry=entry)
        edit.content_field._get_value = "Geänderter Fakt"
        edit.title_field._get_value = ""
        edit._save()
        self.assertEqual(self.cls.get_knowledge_entry(entry["id"])["current_version"], 2)

    def test_entry_dialog_duplicate_and_conflict_notes(self):
        self.cls.add_knowledge("Port ist 100")
        dlg = self.D.EntryDialog(self.master, self.cls, lambda: None)
        dlg.content_field._get_value = "Port ist 100"
        dlg._save()
        self.assertTrue(any("wusste ich schon" in m for k, m in MB_CALLS))
        dlg2 = self.D.EntryDialog(self.master, self.cls, lambda: None)
        dlg2.content_field._get_value = "Port ist 200"
        dlg2._save()
        self.assertTrue(any("widerspricht" in m for k, m in MB_CALLS))

    def test_detail_dialog_actions(self):
        self.seed()
        changes = []
        cand = self.cls.list_knowledge(trust="CANDIDATE")[0]
        dlg = self.D.EntryDetailDialog(self.master, self.cls, cand["id"], lambda: changes.append(1))
        dlg._act(self.cls.confirm_knowledge, cand["id"])
        self.assertEqual(self.cls.get_knowledge_entry(cand["id"])["trust"], "CONFIRMED")
        dlg._act(self.cls.confirm_knowledge, self.b["id"])          # hat offenen Widerspruch → Fehlermeldung
        self.assertTrue(any(k == "error" and "Widerspruch" in m for k, m in MB_CALLS))
        dlg._act(self.cls.restore_knowledge_version, cand["id"], 1)
        MB_ANSWERS["yesno"] = True
        dlg._delete()
        self.assertIsNone(self.cls.get_knowledge_entry(cand["id"]))
        self.assertGreaterEqual(len(changes), 2)
        self.D.EntryDetailDialog(self.master, self.cls, 9999, lambda: None)   # fehlender Eintrag → schließt still

    def test_strategy_detail_shows_scope_and_disables_promotion(self):
        self.project = self.cls.create_project('Atlas', path=str(self.d))
        task = self.cls.create_task('Atlas prüfen', project_id=self.project['id'])
        task.update(status='COMPLETED', verified=True, result='Atlas geprüft')
        self.cls.experience.record(task)
        entry = self.cls.propose_strategy('Bei Atlas Methode B prüfen', [task['id']],
            applicability='Gleiches Fehlermuster', rationale='Beobachtung aus einer Episode')
        self.D.EntryDetailDialog(self.master, self.cls, entry['id'], lambda: None)
        text = ' '.join(self.texts())
        self.assertIn('Gleiches Fehlermuster', text)
        self.assertIn('Confidence: nicht bewertet', text)
        self.assertIn('derived:experience:' + task['id'], text)
        for label in ('Bestätigen', 'Bearbeiten'):
            button = next(w for w in CREATED if w._kw.get('text') == label)
            self.assertEqual(button._kw['state'], 'disabled')

    def test_provider_settings_and_priority_via_existing_view(self):
        from capabilities.registry import build_default_registry
        module = importlib.import_module('desktop.views.providers_view')
        env = self.d / '.env'
        env.write_text('GEMINI_API_KEY=\nPERPLEXITY_API_KEY=\n')
        self.cls.registry = build_default_registry(self.cls.db, env)
        view = module.ProvidersView(self.master, self.cls)
        provider = next(p for p in self.cls.get_providers() if p['name'] == 'groq')
        dialog = module.ProviderDialog(self.master, self.cls, provider, lambda: None)
        dialog.enabled.set(True)
        dialog.model.set('fixture-model')
        dialog.key.set('synthetic-ui-key')
        dialog._save()
        self.assertTrue(self.cls.registry.available(self.cls.registry.get('groq')))
        view.priority_capability.set('research')
        view.priority.set('groq, gemini')
        view._save_priority()
        self.assertEqual(self.cls.get_routing_table()['research'][0]['name'], 'groq')
        self.assertNotIn('synthetic-ui-key', ' '.join(self.texts()))

    def test_memory_candidate_ui_confirmation_and_reference_selection(self):
        project = self.cls.create_project('Active', path=str(self.d))
        self.cls.set_active_project(project['id'])
        other = self.cls.create_project('Atlas reference', path=str(self.d))
        candidate = self.cls.propose_memory('Atlas ist mein Ziel')
        module = importlib.import_module('desktop.views.memory_view')
        view = module.MemoryView(self.master, self.cls)
        self.assertIn('CANDIDATE', ' '.join(self.texts()))
        view._confirm(candidate)
        self.assertEqual(self.cls.get_personal_memory()[0]['trust'], 'CONFIRMED')
        from desktop.components.task_policy import TaskDialog
        dialog = TaskDialog(self.master, self.cls)
        dialog.goal.set('Atlas untersuchen')
        dialog._find_references()
        self.assertFalse(dialog.references[other['id']].get())
        dialog.references[other['id']].set(True)
        dialog.policy.selected_provider.set('groq')
        dialog.policy.preferred.set('groq, ollama')
        dialog.policy.capability.set('coding')
        dialog.policy.local_only.set(True)
        task = dialog._save()
        self.assertEqual(task['reference_project_ids'], [other['id']])
        self.assertEqual(task['ai_policy']['selected_provider'], 'groq')
        self.assertEqual(task['ai_policy']['preferred_providers'], ['groq', 'ollama'])
        self.assertTrue(task['ai_policy']['local_only'])

    def test_conflicts_dialog_resolves(self):
        self.seed()
        dlg = self.D.ConflictsDialog(self.master, self.cls, lambda: None)
        self.assertIn("Unterschiedliche Zahlen/Versionen: 17 ↔ 21", " ".join(self.texts()))
        cid = self.cls.get_conflicts()[0]["id"]
        dlg._resolve(cid, "keep_a")
        self.assertEqual(self.cls.get_conflicts(), [])
        dlg._resolve(cid, "keep_a")                                 # schon gelöst → Fehlermeldung statt Absturz
        self.assertTrue(any(k == "error" for k, m in MB_CALLS))

    # --- Projects ---

    def test_project_dialog_optional_workspace_and_explicit_path(self):
        from unittest.mock import patch
        with patch('config.paths.WORKSPACE_BASE', self.d / 'workspaces'):
            dialog = self.D.ProjectDialog(self.master, self.cls, lambda: None)
            dialog.name_field._get_value = 'Native workspace'
            dialog.auto_workspace.set(True)
            dialog._save()
            created = self.cls.projects.get_by_name('Native workspace')
            self.assertTrue(Path(created['path']).is_dir())
            dialog = self.D.ProjectDialog(self.master, self.cls, lambda: None)
            dialog.name_field._get_value = 'Explicit workspace'
            dialog.path_field._get_value = str(self.d)
            dialog.auto_workspace.set(True)
            dialog._save()
            self.assertEqual(self.cls.projects.get_by_name('Explicit workspace')['path'], str(self.d))

    def test_projects_view_and_dialog(self):
        view = self.PV.ProjectsView(self.master, self.cls)
        self.assertIn("Noch keine Projekte.", self.texts())
        dlg = self.D.ProjectDialog(self.master, self.cls, view._build)
        dlg.name_field._get_value = "Web"
        dlg.instr_field._get_value = "Nutze Tailwind"
        dlg._save()
        p = self.cls.get_projects()[0]
        self.assertEqual((p["name"], p["instructions"]), ("Web", "Nutze Tailwind"))
        dup = self.D.ProjectDialog(self.master, self.cls, view._build)
        dup.name_field._get_value = "web"
        dup._save()
        self.assertTrue(any(k == "error" and "gibt es schon" in m for k, m in MB_CALLS))

        view._act(self.cls.set_active_project, p["id"])
        self.assertEqual(self.cls.get_active_project()["name"], "Web")
        view._act(self.cls.archive_project, p["id"])
        self.assertIsNone(self.cls.get_active_project())
        view._act(self.cls.set_active_project, p["id"])             # archiviert → Fehlermeldung
        self.assertTrue(any(k == "error" and "Archivierte" in m for k, m in MB_CALLS))
        view._toggle_archived()
        self.assertIn(" archiviert ", self.texts())

    def test_project_delete_choices(self):
        view = self.PV.ProjectsView(self.master, self.cls)
        for answer, expected_entries in ((True, 0), (False, 1), (None, None)):
            p = self.cls.create_project(f"P{answer}")
            e = self.cls.add_knowledge("Wissen", project_id=p["id"], title=f"T{answer}")["entry"]
            MB_ANSWERS["yesnocancel"] = answer
            view._delete(self.cls.get_project(p["id"]))
            if answer is None:
                self.assertIsNotNone(self.cls.get_project(p["id"]))
            else:
                self.assertIsNone(self.cls.get_project(p["id"]))
                self.assertEqual(1 if self.cls.get_knowledge_entry(e["id"]) else 0, expected_entries)
            self.cls.delete_knowledge(e["id"])

    def test_task_policy_dialog_saves_and_loads_area_rules(self):
        project = self.cls.create_project('Policy', path=str(self.d))
        self.cls.set_active_project(project['id'])
        from desktop.components.task_policy import TaskDialog
        dialog = TaskDialog(self.master, self.cls)
        dialog.goal.set('Feature')
        dialog.policy.mode.set('FALLBACK')
        backend = dialog.add_area(name='backend', subtask={'goal':'Backend umsetzen'}, policy={'mode':'NEVER'})
        frontend = dialog.add_area(name='frontend', subtask={'goal':'Frontend umsetzen'},
                                  policy={'mode':'ALLOWED','allowed_providers':['perplexity']})
        self.assertEqual(backend.policy.value()['knowledge_sources'], 'ALL_AVAILABLE')
        task = dialog._save()
        self.assertIsNotNone(task, MB_CALLS)
        self.assertEqual(task['ai_policy']['areas']['frontend']['allowed_providers'], ['perplexity'])
        loaded = TaskDialog(self.master, self.cls, task=self.cls.get_task(task['id']))
        self.assertEqual(loaded.policy.value()['mode'], 'FALLBACK')
        self.assertEqual(loaded.areas[0].policy.value()['mode'], 'NEVER')
        self.assertEqual(loaded.areas[1].policy.value()['allowed_providers'], ['perplexity'])
        self.assertEqual(loaded.areas[1].goal.get(), 'Frontend umsetzen')
        loaded.policy.knowledge_mode.set('RESTRICTED')
        for key, var in loaded.policy.sources.items():
            var.set(key == 'PROJECT_KNOWLEDGE')
        copied = loaded._save()
        self.assertEqual(copied['ai_policy']['knowledge_sources'], ['PROJECT_KNOWLEDGE'])
        self.assertEqual(self.cls.get_task(task['id'])['ai_policy']['knowledge_sources'], 'ALL_AVAILABLE')
        self.assertFalse(MB_CALLS, MB_CALLS)

    def test_task_dialog_edits_existing_task_and_subtask_policies(self):
        project = self.cls.create_project('Edit', path=str(self.d))
        self.cls.set_active_project(project['id'])
        task = self.cls.create_task('Feature', ai_policy={'mode':'NEVER','areas':{'front':{'mode':'NEVER'}}},
                                    subtasks=[{'area':'front','goal':'Frontend'}])
        from desktop.components.task_policy import TaskDialog
        dialog = TaskDialog(self.master, self.cls, task=self.cls.get_task(task['id']), edit=True)
        dialog.policy.mode.set('FALLBACK')
        dialog.areas[0].policy.mode.set('ALLOWED')
        dialog.areas[0].policy.provider_override.set(True)
        dialog.areas[0].policy.providers['perplexity'].set(True)
        saved = dialog._save()
        self.assertEqual(saved['id'], task['id'])
        self.assertEqual(len(self.cls.get_tasks()), 1)
        loaded = TaskDialog(self.master, self.cls, task=self.cls.get_task(task['id']), edit=True)
        self.assertEqual(loaded.policy.mode.get(), 'FALLBACK')
        self.assertEqual(loaded.areas[0].policy.value()['allowed_providers'], ['perplexity'])
        self.assertFalse(MB_CALLS, MB_CALLS)

    # --- Chat-Anzeige ---

    def test_chat_label_shows_knowledge_and_candidate(self):
        self.cls.add_knowledge("Fabric braucht Java 17")
        chat = self.CW.ChatWidget(self.master, self.cls)
        CREATED.clear()
        chat._add_message("Antwort", is_user=False, provider="gemini", knowledge=2, candidate=7)
        text = " ".join(self.texts())
        self.assertIn("CLS · Gemini · Wissen: 2 · als Kandidat #7 gespeichert", text)
        CREATED.clear()
        chat._add_message("Hi", is_user=True)
        self.assertIn("Du\nHi", " ".join(self.texts()))


if __name__ == "__main__":
    unittest.main()
