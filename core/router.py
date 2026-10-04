"""
Router (Phase 2) — Intent → Capability → Provider. Regelbasiert, keine AI.

1. Capability bestimmen: aus dem Modus (Research/Coding) oder per Keyword-Regeln
2. Provider wählen: erster verfügbarer Provider mit dieser Capability
3. Kein Provider dafür? → Ersatz-Capabilities (config/routing.py)
4. Fallback-Liste: weitere verfügbare Provider, falls der erste fehlschlägt
"""

import re
from dataclasses import dataclass, field

from capabilities.registry import CapabilityRegistry
from config.routing import (
    CAPABILITY_FALLBACKS, DEFAULT_CAPABILITY, KEYWORD_RULES, MODE_CAPABILITY,
)
from providers.base import BaseProvider
from infrastructure.logger import get_logger

logger = get_logger(__name__)


@dataclass
class RouteDecision:
    capability: str            # gewünschte Capability
    provider: BaseProvider     # gewählter Provider
    reason: str                # verständliche Begründung (Logs/UI)
    fallbacks: list[BaseProvider] = field(default_factory=list)
    used_capability: str = ""  # Capability, über die der Provider gefunden wurde


class Router:
    def __init__(self, registry: CapabilityRegistry):
        self.registry = registry
        self._rules = [
            (cap, [re.compile(p, re.IGNORECASE) for p in patterns])
            for cap, patterns in KEYWORD_RULES
        ]

    def detect_capability(self, text: str, mode: str = "chat") -> str:
        if mode in MODE_CAPABILITY:
            return MODE_CAPABILITY[mode]
        for capability, patterns in self._rules:
            if any(p.search(text) for p in patterns):
                return capability
        return DEFAULT_CAPABILITY

    def route(self, text: str, mode: str = "chat", *, selected=None, local_only=False) -> RouteDecision | None:
        """Gibt None zurück, wenn gar kein Provider verfügbar ist."""
        wanted = self.detect_capability(text, mode)
        chain = [wanted] + CAPABILITY_FALLBACKS.get(wanted, [])
        if DEFAULT_CAPABILITY not in chain:
            chain.append(DEFAULT_CAPABILITY)

        for capability in chain:
            candidates = self.registry.candidates(capability, selected=selected)
            candidates = [p for p in candidates if not local_only or p.is_local]
            if not candidates:
                continue

            primary = candidates[0]
            fallbacks: list[BaseProvider] = []
            for c in chain:
                for p in self.registry.candidates(c, selected=selected):
                    if local_only and not p.is_local:
                        continue
                    if p is not primary and p not in fallbacks:
                        fallbacks.append(p)

            reason = f"Modus '{mode}' → {wanted} → {primary.name}"
            if capability != wanted:
                reason += f" (Ersatz über {capability}, kein Provider für {wanted})"
            logger.info(f"Routing: {reason}")
            return RouteDecision(wanted, primary, reason, fallbacks, capability)

        logger.error("Routing: kein verfügbarer Provider")
        return None
