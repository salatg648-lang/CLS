"""
Capability Registry (Phase 2) — Provider ↔ Capability Mapping.

Der Router fragt: "Welche verfügbaren Provider haben Capability X?"
Die Reihenfolge kommt aus config/providers.py (CAPABILITY_PREFERENCE).
"""

import json
from copy import deepcopy

from config.providers import ACTIVE_PROVIDERS, CAPABILITY_PREFERENCE, PROVIDER_CONFIG
from providers.base import BaseProvider
from infrastructure.logger import get_logger

logger = get_logger(__name__)

# Capability-Namen (Strings, damit config/ sie ohne Import nutzen kann)
GENERAL = "general_reasoning"
RESEARCH = "research"
WEB_SEARCH = "web_search"
CODING = "coding"
CAPABILITIES = (GENERAL, RESEARCH, WEB_SEARCH, CODING, "local_reasoning")


class CapabilityRegistry:
    def __init__(self, db=None, env_path=None):
        self._providers: dict[str, BaseProvider] = {}
        self.db, self.env_path = db, env_path
        self.preferences = deepcopy(CAPABILITY_PREFERENCE)
        self.settings = {}
        if db:
            row = db.query_one("SELECT value FROM app_state WHERE key='provider_settings'")
            if row:
                saved = json.loads(row['value'])
                self.preferences.update(saved.get('preferences', {}))
                self.settings = saved.get('providers', {})

    def register(self, provider: BaseProvider):
        self._providers[provider.name] = provider
        logger.debug(f"Provider registriert: {provider.name} {provider.get_capabilities()}")

    def get(self, name: str) -> BaseProvider | None:
        return self._providers.get(name)

    def all(self) -> list[BaseProvider]:
        return list(self._providers.values())

    def providers_for(self, capability: str, only_available: bool = True) -> list[BaseProvider]:
        """Provider mit dieser Capability, nach Präferenz sortiert."""
        found = [
            p for p in self._providers.values()
            if capability in p.get_capabilities()
            and (self.available(p) or not only_available)
        ]
        preference = self.preferences.get(capability, ACTIVE_PROVIDERS)

        def rank(p: BaseProvider) -> int:
            return preference.index(p.name) if p.name in preference else len(preference)

        return sorted(found, key=rank)  # sorted ist stabil → Registrierungs-Reihenfolge bei Gleichstand

    def routing_table(self) -> dict[str, list[dict]]:
        """capability → [{name, available}] in Prioritäts-Reihenfolge (für die UI)."""
        caps = sorted({c for p in self._providers.values() for c in p.get_capabilities()})
        return {
            cap: [{"name": p.name, "available": self.available(p)}
                  for p in self.providers_for(cap, only_available=False)]
            for cap in caps
        }


    def available(self, provider):
        return bool(provider.enabled and provider.is_available())

    def candidates(self, capability, *, selected=None, preferred=None):
        candidates = self.providers_for(capability)
        if selected and selected != 'automatic':
            return [p for p in candidates if p.name == selected]
        preferred = preferred or []
        return sorted(candidates, key=lambda p: preferred.index(p.name) if p.name in preferred else len(preferred))

    def _save(self):
        if self.db:
            self.db.execute("INSERT INTO app_state(key,value) VALUES ('provider_settings',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (json.dumps({'providers': self.settings, 'preferences': self.preferences}),))

    def configure(self, name, *, enabled=None, model=None, capabilities=None, api_key=None):
        if name not in PROVIDER_CONFIG:
            raise ValueError('Unbekannter Provider.')
        if enabled is not None and not isinstance(enabled, bool):
            raise ValueError('Enabled muss ein Boolean sein.')
        if model is not None and (not isinstance(model, str) or not model.strip() or len(model) > 200):
            raise ValueError('Modellname fehlt oder ist zu lang.')
        if capabilities is not None and (not isinstance(capabilities, list) or
                any(c not in CAPABILITIES for c in capabilities)):
            raise ValueError('Unbekannte Capability.')
        if name != 'ollama' and capabilities and 'local_reasoning' in capabilities:
            raise ValueError('Ein externer Provider kann nicht als lokal konfiguriert werden.')
        config = {**self.settings.get(name, {})}
        if enabled is not None:
            config['enabled'] = enabled
        if model is not None:
            config['model'] = model.strip()
        if capabilities is not None:
            config['capabilities'] = list(dict.fromkeys(capabilities))
        from infrastructure.config import provider_key, save_provider_key
        key = provider_key(name, self.env_path) if api_key is None else api_key
        if not isinstance(key, str) or any(c in key for c in '\r\n\x00'):
            raise ValueError('Ungültiger API-Key.')
        provider = create_provider(name, config, key)
        if api_key is not None:
            save_provider_key(name, api_key, self.env_path)
        self.settings[name] = config
        self._save()
        self.register(provider)

    def set_priority(self, capability, names):
        if capability not in CAPABILITIES or not isinstance(names, list) or any(n not in self._providers for n in names):
            raise ValueError('Ungültige Capability oder Provider-Reihenfolge.')
        if len(names) != len(set(names)):
            raise ValueError('Provider dürfen in der Reihenfolge nicht doppelt vorkommen.')
        self.preferences[capability] = list(names)
        self._save()


def create_provider(name, settings, api_key):
    from providers.gemini import GeminiProvider
    from providers.perplexity import PerplexityProvider
    from providers.ollama import OllamaProvider
    from providers.openai_compatible import OpenAICompatibleProvider
    classes = {'gemini': GeminiProvider, 'perplexity': PerplexityProvider}
    if name in classes:
        provider = classes[name](api_key=api_key)
    elif name == 'ollama':
        provider = OllamaProvider()
    else:
        provider = OpenAICompatibleProvider(name, api_key)
    provider.enabled = settings.get('enabled', PROVIDER_CONFIG[name]['enabled'])
    if 'capabilities' in settings:
        provider.capabilities = settings['capabilities']
    if 'model' in settings:
        provider.configured_models = {'default': settings['model']}
    return provider


def build_default_registry(db=None, env_path=None) -> CapabilityRegistry:
    """Alle bekannten Provider anzeigen; Enabled/Keys/Modelle filtern erst bei Auswahl."""
    from infrastructure.config import provider_key
    registry = CapabilityRegistry(db, env_path)
    for name in ACTIVE_PROVIDERS:
        try:
            registry.register(create_provider(name, registry.settings.get(name, {}), provider_key(name, env_path)))
        except ValueError:
            logger.warning('Ungültige Konfiguration für Provider %s; Provider übersprungen.', name)
    return registry
