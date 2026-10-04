"""Tests ohne Netzwerk, ohne API-Keys, ohne GUI:  python -m unittest discover -s tests -v"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from capabilities.registry import CapabilityRegistry
from core.assistant import Assistant
from core.context_manager import ContextManager
from core.router import Router
from memory.conversation import ConversationHistory
from memory.longterm import LongTermMemory
from providers.base import BaseProvider, ProviderError, split_system
from providers.perplexity import PerplexityProvider
from infrastructure.storage import load_json, save_json


class FakeProvider(BaseProvider):
    def __init__(self, name, caps, available=True, fail=False):
        self.name, self.display_name, self.capabilities = name, name.title(), caps
        self._available, self._fail = available, fail
        self.calls = []

    def is_available(self):
        return self._available

    def chat(self, messages, model=None):
        self.calls.append((messages, model))
        if self._fail:
            raise ProviderError("kaputt")
        return f"antwort von {self.name}"


def make_registry(**kw):
    reg = CapabilityRegistry()
    reg.register(FakeProvider("gemini", ["general_reasoning", "research"], **kw.get("gemini", {})))
    reg.register(FakeProvider("perplexity", ["coding", "web_search", "research", "general_reasoning"],
                              **kw.get("perplexity", {})))
    return reg


class RouterTests(unittest.TestCase):
    def test_modes_force_capability(self):
        r = Router(make_registry())
        self.assertEqual(r.route("hallo", "coding").provider.name, "perplexity")
        self.assertEqual(r.route("hallo", "research").provider.name, "gemini")

    def test_auto_detection(self):
        r = Router(make_registry())
        self.assertEqual(r.detect_capability("Ich habe einen Bug in meinem Mod"), "coding")
        self.assertEqual(r.detect_capability("Was ist das Neueste zu Fabric?"), "coding")  # coding hat Vorrang
        self.assertEqual(r.detect_capability("Wie wird das Wetter heute?"), "web_search")
        self.assertEqual(r.detect_capability("Hallo, wie geht's?"), "general_reasoning")
        # \b verhindert Treffer mitten im Wort
        self.assertEqual(r.detect_capability("Das ist ein moderner Barcode"), "general_reasoning")

    def test_unavailable_falls_back(self):
        r = Router(make_registry(perplexity={"available": False}))
        d = r.route("Python Fehler", "chat")
        self.assertEqual(d.provider.name, "gemini")
        self.assertIn("Ersatz", d.reason)

    def test_nothing_available(self):
        r = Router(make_registry(gemini={"available": False}, perplexity={"available": False}))
        self.assertIsNone(r.route("hallo"))

    def test_routing_table_order(self):
        table = make_registry().routing_table()
        self.assertEqual([p["name"] for p in table["coding"]], ["perplexity"])
        self.assertEqual([p["name"] for p in table["research"]], ["gemini", "perplexity"])


class AssistantTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.conv = ConversationHistory(d / "c.json")
        self.lt = LongTermMemory(d / "l.json")

    def tearDown(self):
        self.tmp.cleanup()

    def assistant(self, **kw):
        self.reg = make_registry(**kw)
        return Assistant(Router(self.reg), ContextManager(self.conv, self.lt), self.conv, self.lt)

    def test_provider_gets_system_prompt_facts_and_history(self):
        self.lt.add_fact("Robin mag Fabric")
        a = self.assistant()
        a.handle_message("Hallo")
        reply = a.handle_message("Und jetzt zu Fabric?")
        messages, _ = self.reg.get(reply.provider).calls[-1]
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("Robin mag Fabric", messages[0]["content"])
        self.assertEqual([m["role"] for m in messages[1:]], ["user", "assistant", "user"])

    def test_error_not_stored_and_fallback_used(self):
        a = self.assistant(perplexity={"fail": True})
        reply = a.handle_message("Python Bug", "coding")
        self.assertEqual(reply.provider, "gemini")
        self.assertTrue(reply.fallback_used)
        self.assertEqual(len(self.conv.messages), 2)

    def test_all_fail_stores_nothing(self):
        a = self.assistant(gemini={"fail": True}, perplexity={"fail": True})
        reply = a.handle_message("Hallo")
        self.assertTrue(reply.error)
        self.assertEqual(self.conv.messages, [])

    def test_no_provider(self):
        a = self.assistant(gemini={"available": False}, perplexity={"available": False})
        self.assertTrue(a.handle_message("Hallo").error)

    def test_memory_commands(self):
        a = self.assistant()
        for text, fact in [("Merk dir, dass ich Java mag", "ich Java mag"),
                           ("merke dir dass X", "X"), ("Merke: Y", "Y"), ("Merk dir Z", "Z")]:
            reply = a.handle_message(text)
            self.assertEqual(reply.provider, "cls")
            self.assertIn(fact, [f["content"] for f in self.lt.get_all()])
        self.assertEqual(a.handle_message("Merk dir Z").text, "Das wusste ich schon: Z")
        self.assertNotEqual(a.handle_message("Das ist merkwürdig").provider, "cls")
        self.assertEqual(self.reg.get("gemini").calls[-1][0][-1]["content"], "Das ist merkwürdig")


class MemoryTests(unittest.TestCase):
    def test_fact_ids_unique_after_delete(self):
        with tempfile.TemporaryDirectory() as d:
            lt = LongTermMemory(Path(d) / "l.json")
            for t in "abc":
                lt.add_fact(t)
            lt.delete_fact(2)
            new = lt.add_fact("d")
            self.assertEqual(sorted(f["id"] for f in lt.get_all()), [1, 3, 4])
            self.assertEqual(new["id"], 4)

    def test_rolling_window_starts_with_user(self):
        with tempfile.TemporaryDirectory() as d:
            c = ConversationHistory(Path(d) / "c.json", max_messages=4)
            for i in range(4):
                c.add("user", f"u{i}")
                c.add("assistant", f"a{i}")
            self.assertLessEqual(len(c.messages), 4)
            self.assertEqual(c.messages[0]["role"], "user")

    def test_meta_persists_but_not_sent_to_ai(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.json"
            c = ConversationHistory(p)
            c.add("assistant", "hi", meta={"provider": "gemini"})
            self.assertEqual(ConversationHistory(p).get_all()[0]["meta"]["provider"], "gemini")
            self.assertEqual(c.get_messages(), [{"role": "assistant", "content": "hi"}])


class StorageTests(unittest.TestCase):
    def test_corrupt_file_is_backed_up(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.json"
            p.write_text("{kaputt", encoding="utf-8")
            self.assertIsNone(load_json(p))
            backups = [f for f in os.listdir(d) if ".corrupt-" in f]
            self.assertEqual(len(backups), 1)
            self.assertTrue(save_json(p, [1]))
            self.assertEqual(load_json(p), [1])
            self.assertFalse(any(f.endswith(".tmp") for f in os.listdir(d)))


class ProviderHelperTests(unittest.TestCase):
    def test_split_system_normalizes(self):
        system, hist = split_system([
            {"role": "system", "content": "S"},
            {"role": "assistant", "content": "verwaist"},
            {"role": "user", "content": "a"}, {"role": "user", "content": "b"},
            {"role": "assistant", "content": ""}, {"role": "assistant", "content": "c"},
            {"role": "user", "content": "d"},
        ])
        self.assertEqual(system, "S")
        self.assertEqual([(m["role"], m["content"]) for m in hist],
                         [("user", "a\n\nb"), ("assistant", "c"), ("user", "d")])

    def test_perplexity_parsing_and_payload(self):
        p = PerplexityProvider(api_key="test")
        sent = {}
        p._post = lambda payload: (sent.update(payload) or
                                   {"choices": [{"message": {"content": "Antwort"}}],
                                    "citations": ["https://a.de", "https://b.de"]})
        text = p.chat([{"role": "system", "content": "S"}, {"role": "user", "content": "Frage"}], model="sonar-pro")
        self.assertIn("Antwort", text)
        self.assertIn("[2] https://b.de", text)
        self.assertEqual(sent["model"], "sonar-pro")
        self.assertEqual(sent["messages"][0], {"role": "system", "content": "S"})

    def test_perplexity_errors(self):
        self.assertFalse(PerplexityProvider(api_key="").is_available())
        with self.assertRaises(ProviderError):
            PerplexityProvider(api_key="").chat([{"role": "user", "content": "x"}])
        with self.assertRaises(ProviderError):
            PerplexityProvider._parse_response({"choices": []})
        with self.assertRaises(ProviderError):
            PerplexityProvider._parse_response({"choices": [{"message": {"content": " "}}]})


if __name__ == "__main__":
    unittest.main()
