"""
Assistant — verarbeitet eine Chat-Nachricht (ein Durchlauf, kein Loop).

Ablauf:
1. "Merk dir ..."-Befehl? → direkt speichern, keine AI nötig
1b. "Was weißt du über X?" → direkt aus der Wissensbasis antworten (ehrlich, wenn nichts da ist)
2. Router wählt Capability + Provider
3. Context Manager baut die Messages (inkl. Projekt + Wissen)
4. Provider aufrufen; bei Fehler den nächsten Fallback-Provider probieren
5. Erst bei Erfolg landen User-Nachricht + Antwort im Verlauf
   (Fehler stehen NIE im Verlauf und verwirren die AI nicht)
6. Research-/Web-Antworten werden als Wissens-KANDIDAT gespeichert (nie automatisch als Wissen)
"""

import re
from dataclasses import dataclass, field, asdict

from core.context_manager import ContextManager
from core.router import Router
from memory.conversation import ConversationHistory
from memory.longterm import LongTermMemory
from tools.safety import PermissionDenied
from providers.base import ProviderError, valid_text
from config import knowledge as kcfg
from config.routing import MODES
from knowledge.trust import label as trust_label
from infrastructure.logger import get_logger

logger = get_logger(__name__)

# "Merk dir, dass X" | "Merk dir X" | "Merke dir dass X" | "Merke: X"
_MEMORY_PATTERNS = [
    re.compile(r"^\s*merke?\s+dir\b[\s:,]*(?:dass\s+)?(?P<fact>.+?)\s*$", re.IGNORECASE | re.DOTALL),
    re.compile(r"^\s*merke\s*:\s*(?P<fact>.+?)\s*$", re.IGNORECASE | re.DOTALL),
]


# "Was weißt du über X?" — aber nicht, wenn nach dem Nutzer selbst gefragt wird (das ist Personal Memory)
_KNOWLEDGE_PATTERN = re.compile(
    r"^\s*was\s+wei(?:ß|ss)t\s+du\s+(?:alles\s+)?(?:über|ueber|zu|von)\s+(?P<topic>.+?)\s*[?.!]*\s*$",
    re.IGNORECASE | re.DOTALL)
_SELF_TOPICS = {"mich", "mir", "robin", "uns", "dich", "dir", "ihn", "sie", "ihm"}


def _snippet(text: str, n: int = 200) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[:n - 1].rstrip() + "…"


@dataclass
class Reply:
    text: str
    provider: str = ""       # "gemini" | "perplexity" | "cls" (System) | ""
    capability: str = ""
    mode: str = "chat"
    fallback_used: bool = False
    error: bool = False
    knowledge_used: list[int] = field(default_factory=list)   # Wissenseinträge im Kontext
    candidate_id: int | None = None                           # als Kandidat gespeicherte Antwort

    def to_dict(self) -> dict:
        return asdict(self)


class Assistant:
    def __init__(self, router: Router, context: ContextManager,
                 conversation: ConversationHistory, longterm: LongTermMemory,
                 knowledge=None, projects=None):
        self.router = router
        self.context = context
        self.conversation = conversation
        self.longterm = longterm
        self.knowledge = knowledge
        self.projects = projects

    def handle_message(self, user_input: str, mode: str = "chat", *, provider=None, local_only=False) -> Reply:
        mode = mode if mode in MODES else "chat"
        logger.info("Nachricht im Modus %s", mode)

        project_id = (self.projects.get_active() or {}).get('id') if self.projects else None

        # 1. Memory-Befehl
        memory_reply = self._check_memory_command(user_input)
        if memory_reply:
            self.conversation.add("user", user_input, meta={"project_id": project_id, "local_only": True})
            self.conversation.add("assistant", memory_reply, meta={"provider": "cls", "project_id": project_id, "local_only": True})
            return Reply(memory_reply, provider="cls", capability="memory", mode=mode)

        # 1b. Wissensfrage → direkt aus der Wissensbasis
        knowledge_reply = self._check_knowledge_question(user_input, mode)
        if knowledge_reply:
            self.conversation.add("user", user_input, meta={"project_id": project_id, "local_only": True})
            self.conversation.add("assistant", knowledge_reply.text, meta={
                "provider": "cls", "project_id": project_id, "capability": "knowledge", "knowledge": knowledge_reply.knowledge_used, "local_only": True})
            return knowledge_reply

        # 2. Routing
        decision = self.router.route(user_input, mode, selected=provider, local_only=local_only)
        if decision is None:
            return Reply(
                "Kein AI-Provider verfügbar. Trage mindestens einen API-Key in die "
                "Provider-Einstellungen ein und prüfe Modell, Capability und Auswahl.",
                mode=mode, error=True,
            )

        # 3./4. Provider probieren (erst der gewählte, dann Fallbacks)
        errors: list[str] = []
        for index, provider in enumerate([decision.provider] + decision.fallbacks):
            try:
                self.context.check_chat_provider(provider)
                ctx = self.context.build(user_input, decision.capability, external=not provider.is_local)
                messages = ctx.messages
                text = valid_text(provider.chat(messages, model=provider.model_for(decision.capability)))
            except (ProviderError, PermissionDenied) as e:
                logger.warning("Provider %s fehlgeschlagen (%s)", provider.name, type(e).__name__)
                errors.append(f"{provider.name}: Anfrage fehlgeschlagen oder durch Regeln gesperrt.")
                continue

            # 5. Erfolg → Verlauf speichern
            self.conversation.add("user", user_input, meta={"project_id": project_id, "local_only": provider.is_local})
            self.conversation.add("assistant", text, meta={
                "provider": provider.name, "project_id": project_id,
                "capability": decision.capability,
                "mode": mode,
                "local_only": provider.is_local,
                "knowledge": ctx.knowledge_ids,
                "memory": ctx.memory_ids,
                "memory_versions": ctx.memory_versions,
            })
            candidate_id = self._store_candidate(user_input, text, provider.name,
                                                 decision.capability, ctx.project, context=ctx)
            if candidate_id and provider.is_local and self.context.privacy:
                self.context.privacy.set_entry(candidate_id, 'LOCAL_ONLY')
            return Reply(text, provider=provider.name, capability=decision.capability,
                         mode=mode, fallback_used=index > 0,
                         knowledge_used=ctx.knowledge_ids, candidate_id=candidate_id)

        return Reply("Alle Provider sind fehlgeschlagen:\n- " + "\n- ".join(errors),
                     capability=decision.capability, mode=mode, error=True)

    def _check_memory_command(self, user_input: str) -> str | None:
        if user_input.casefold().startswith('lernvorschlag:'):
            content = user_input.split(':', 1)[1].strip()
            if not content:
                return 'Bitte formuliere die Information, die du prüfen möchtest.'
            self.longterm.add_fact(content, category='user_profile', trust='CANDIDATE', privacy='LOCAL_ONLY',
                                   provenance={'source_type': 'user', 'reference': 'explicit_learning_proposal'})
            return 'Als lokalen Memory-Kandidaten gespeichert. Du kannst ihn unter Memory prüfen und bestätigen.'
        for pattern in _MEMORY_PATTERNS:
            match = pattern.match(user_input)
            if not match:
                continue
            fact = match.group("fact").strip()
            if not fact:
                continue
            if self.longterm.has_fact(fact):
                return f"Das wusste ich schon: {fact}"
            self.longterm.add_fact(content=fact, category="user_stated", tags=["memory_command"], privacy="LOCAL_ONLY")
            return f"Okay, gemerkt: {fact}"
        return None

    # --- Phase 3: Wissen ---

    def _check_knowledge_question(self, user_input: str, mode: str) -> Reply | None:
        """'Was weißt du über X?' → Antwort aus der Wissensbasis. None = normal an die AI."""
        if not self.knowledge:
            return None
        match = _KNOWLEDGE_PATTERN.match(user_input)
        if not match:
            return None
        topic = match.group("topic").strip()
        if topic.lower() in _SELF_TOPICS:
            return None
        try:
            return self._answer_from_knowledge(topic, mode)
        except Exception as e:  # dann eben die AI fragen
            logger.warning(f"Wissensantwort fehlgeschlagen: {e}")
            return None

    def _answer_from_knowledge(self, topic: str, mode: str) -> Reply:
        project = self.projects.get_active() if self.projects else None
        hits = self.knowledge.search(topic, project_id=project["id"] if project else None,
                                     include_global=True, exclude_trust=("OUTDATED",),
                                     kinds=kcfg.CONTEXT_KINDS, limit=6)
        if self.context.privacy:
            hits = [h for h in hits if self.context._may_use(h, False)]
        trusted = [h for h in hits if h["trust"] in kcfg.CONTEXT_TRUST_LEVELS]
        candidates = [h for h in hits if h["trust"] == "CANDIDATE"]

        if not trusted and not candidates:
            text = (f"Zu \"{topic}\" habe ich nichts in meiner Wissensbasis — ich rate nicht. "
                    "Wenn du willst, recherchiere ich das im Research-Modus.")
        else:
            lines = []
            if trusted:
                lines.append(f"Das steht in meiner Wissensbasis zu \"{topic}\":")
                for h in trusted:
                    snippet = _snippet(h["content"])
                    title = h["title"].rstrip("…")
                    head = f"- #{h['id']} [{trust_label(h['trust'])}]"
                    line = f"{head} {snippet}" if snippet.startswith(title) else f"{head} {title}: {snippet}"
                    partners = self.knowledge.conflicts.partner_ids(h["id"])
                    if partners:
                        line += " — Achtung: widerspricht " + ", ".join(f"#{i}" for i in partners)
                    lines.append(line)
            else:
                lines.append(f"Gesichertes Wissen zu \"{topic}\" habe ich nicht.")
            if candidates:
                ids = ", ".join(f"#{c['id']}" for c in candidates)
                lines.append(f"Dazu gibt es {len(candidates)} ungeprüfte AI-Antwort(en) ({ids}). "
                             "Das ist noch kein Wissen — im Bereich Knowledge kannst du sie prüfen.")
            text = "\n".join(lines)

        return Reply(text, provider="cls", capability="knowledge", mode=mode,
                     knowledge_used=[h["id"] for h in trusted])

    def _store_candidate(self, question: str, answer: str, provider: str,
                         capability: str, project: dict | None, context=None) -> int | None:
        """Controlled Learning: AI-Antwort → Kandidat. Darf den Chat nie stören."""
        if not (self.knowledge and kcfg.AUTO_CANDIDATES
                and capability in kcfg.AUTO_CANDIDATE_CAPABILITIES):
            return None
        try:
            references = []
            if context:
                refs = [f'memory:{identity}@{version}' for identity, version in context.memory_versions.items()]
                refs += [f'knowledge:{identity}@{version}' for identity, version in context.knowledge_versions.items()]
                if project:
                    refs.append(f"project:{project['id']}")
                references = [{'source_type': 'ai_provider', 'name': provider, 'reference': 'derived:' + ref}
                              for ref in refs]
            result = self.knowledge.add_ai_candidate(
                question, answer, provider, project["id"] if project else None, references=references)
            return result["entry"]["id"] if result else None
        except Exception as e:
            logger.warning(f"Kandidat konnte nicht gespeichert werden: {e}")
            return None
