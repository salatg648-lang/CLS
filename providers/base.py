"""
Base Provider — einheitliche Schnittstelle für alle AI-Provider.

Der Core kennt nur diese Schnittstelle. Welcher Provider dahintersteckt,
ist ihm egal. Provider deklarieren ihre Capabilities; der Router (Phase 2)
wählt darüber den passenden Provider.

Fehler werden als ProviderError geworfen (nicht als Text-Antwort zurückgegeben),
damit sie nie versehentlich im Chatverlauf landen und der Router einen
Fallback-Provider probieren kann.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


class ProviderError(Exception):
    """Ein AI-Provider konnte die Anfrage nicht beantworten."""


def split_system(messages: list[dict]) -> tuple[str, list[dict]]:
    """
    Trennt System-Prompt und Verlauf.

    Returns:
        (system_text, history) — history enthält nur user/assistant-Nachrichten,
        ohne leere Einträge, mit zusammengefassten gleichen Rollen hintereinander
        und beginnend mit 'user' (Voraussetzung für Gemini und Perplexity).
    """
    system_parts = [m["content"] for m in messages if m.get("role") == "system" and m.get("content")]
    history: list[dict] = []
    for m in messages:
        role, content = m.get("role"), (m.get("content") or "").strip()
        if role not in ("user", "assistant") or not content:
            continue
        if history and history[-1]["role"] == role:
            history[-1]["content"] += "\n\n" + content
        else:
            history.append({"role": role, "content": content})
    while history and history[0]["role"] != "user":
        history.pop(0)
    return "\n\n".join(system_parts), history


class BaseProvider(ABC):
    """Jede AI-Anbindung implementiert diese Schnittstelle."""

    name: str = "base"
    display_name: str = "Base"

    # z.B. "general_reasoning", "research", "web_search", "coding"
    capabilities: list[str] = []

    @abstractmethod
    def chat(self, messages: list[dict], model: Optional[str] = None) -> str:
        """
        Sendet eine Chat-Anfrage.

        Args:
            messages: [{"role": "system|user|assistant", "content": "..."}]
                      (System-Prompt zuerst, letzte Nachricht vom User)
            model: optionaler Modellname

        Raises:
            ProviderError: bei jedem Fehler (kein Key, Netzwerk, API-Fehler, leere Antwort)
        """

    @abstractmethod
    def is_available(self) -> bool:
        """API-Key gesetzt / Service erreichbar (ohne Netzwerk-Call)."""

    def model_for(self, capability: str) -> Optional[str]:
        """Modellname für eine Capability (None = Provider-Standard)."""
        return None

    is_local = False
    enabled = True

    def configured_model(self, capability, default):
        models = getattr(self, 'configured_models', {})
        return models.get(capability, models.get('default', default))

    def tool_chat(self, messages: list[dict], tools: list[dict], model=None):
        raise ProviderError(f"{self.display_name} unterstützt keine nativen Tool-Aufrufe.")

    def supports_tool_calls(self) -> bool:
        return False

    def supports_streaming(self) -> bool:
        return False

    def get_capabilities(self) -> list[str]:
        return list(self.capabilities)


# Native Antworten sind typisiert; der Agent interpretiert niemals Text als Tool-Aufruf.


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class ProviderTurn:
    text: str = ''
    calls: list[ToolCall] = field(default_factory=list)
    # Provider-eigene Parts (z.B. Gemini thought_signature) müssen unverändert zurück.
    native: dict | None = None


def valid_text(text):
    """Core-Grenze: leere/falsch typisierte Rückgaben sind kein Erfolg."""
    if not isinstance(text, str) or not text.strip():
        raise ProviderError('Provider lieferte keine gültige Textantwort.')
    return text.strip()


def validate_turn(turn):
    if not isinstance(turn, ProviderTurn) or not isinstance(turn.text, str) or not isinstance(turn.calls, list):
        raise ProviderError('Ungültige native Provider-Antwort.')
    if turn.native is not None and not isinstance(turn.native, dict):
        raise ProviderError('Ungültige native Provider-Metadaten.')
    seen = set()
    for call in turn.calls:
        if (not isinstance(call, ToolCall) or not isinstance(call.id, str) or not call.id.strip()
                or call.id in seen or not isinstance(call.name, str) or not call.name.strip()
                or not isinstance(call.arguments, dict)):
            raise ProviderError('Ungültiger nativer Tool-Aufruf.')
        seen.add(call.id)
    if not turn.calls:
        valid_text(turn.text)
    return turn
