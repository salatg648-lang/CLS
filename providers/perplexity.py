"""
Perplexity Provider (Phase 2) — Coding-Hilfe und Web-Suche mit Quellen.

Nutzt die OpenAI-kompatible Chat-Completions-Schnittstelle von Perplexity
über die Standardbibliothek (urllib) — keine zusätzliche Abhängigkeit.
Quellen (citations) werden an die Antwort angehängt.
"""

import json
import urllib.error
import urllib.request
from typing import Optional

from providers.base import BaseProvider, ProviderError, split_system
from config.models import MODEL_BY_CAPABILITY
from config.providers import PROVIDER_CONFIG
from config.settings import REQUEST_TIMEOUT
from infrastructure.config import PERPLEXITY_API_KEY
from infrastructure.logger import get_logger

logger = get_logger(__name__)

MAX_SOURCES = 8


class PerplexityProvider(BaseProvider):
    name = "perplexity"
    display_name = "Perplexity"
    capabilities = ["coding", "web_search", "research", "general_reasoning"]

    def __init__(self, api_key: str = PERPLEXITY_API_KEY):
        self.api_key = api_key
        self.url = PROVIDER_CONFIG["perplexity"]["base_url"]
        if not api_key:
            logger.warning("PERPLEXITY_API_KEY nicht gesetzt — Perplexity nicht verfügbar.")
        else:
            logger.info("Perplexity Provider initialisiert")

    def model_for(self, capability: str) -> Optional[str]:
        models = MODEL_BY_CAPABILITY["perplexity"]
        return self.configured_model(capability, models.get(capability, models["default"]))

    def is_available(self) -> bool:
        return bool(self.api_key)

    def chat(self, messages: list[dict], model: Optional[str] = None) -> str:
        if not self.is_available():
            raise ProviderError("Perplexity ist nicht konfiguriert (PERPLEXITY_API_KEY fehlt).")

        model_name = model or self.model_for("default")
        system, history = split_system(messages)
        if not history:
            raise ProviderError("Keine User-Nachricht zum Senden.")

        payload_messages = ([{"role": "system", "content": system}] if system else []) + history
        data = self._post({"model": model_name, "messages": payload_messages})
        text = self._parse_response(data)
        logger.debug(f"Perplexity Antwort erhalten (Modell: {model_name})")
        return text

    # --- intern (für Tests überschreibbar) ---

    def _post(self, payload: dict) -> dict:
        request = urllib.request.Request(
            self.url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None
        try:
            with urllib.request.build_opener(NoRedirect()).open(request, timeout=REQUEST_TIMEOUT) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise ProviderError(f"Perplexity-Fehler (HTTP {e.code}).") from None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise ProviderError('Perplexity nicht erreichbar.') from None
        except json.JSONDecodeError as e:
            raise ProviderError("Perplexity lieferte keine gültige JSON-Antwort.") from e

    @staticmethod
    def _parse_response(data: dict) -> str:
        try:
            from providers.base import valid_text
            if data.get('error'):
                raise ProviderError('Perplexity meldet einen Fehler.')
            text = valid_text(data["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError, AttributeError) as e:
            raise ProviderError("Unerwartetes Antwortformat von Perplexity.") from e
        if not text:
            raise ProviderError("Perplexity hat eine leere Antwort geliefert.")

        urls = [u for u in (data.get("citations") or []) if isinstance(u, str)]
        if not urls:
            urls = [r.get("url") for r in (data.get("search_results") or [])
                    if isinstance(r, dict) and r.get("url")]
        if urls:
            lines = [f"[{i}] {u}" for i, u in enumerate(urls[:MAX_SOURCES], 1)]
            text += "\n\nQuellen:\n" + "\n".join(lines)
        return text
