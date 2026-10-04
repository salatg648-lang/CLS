"""
Gemini Provider — allgemeine Fragen, Recherche, Dokumentation.

FIX (v0.2): Früher wurde nur die letzte User-Nachricht gesendet — System-Prompt,
Long-Term-Fakten und Verlauf gingen verloren. Jetzt gehen System-Instruction
und kompletter Verlauf mit.

Nutzt client.models.generate_content (stabile API im google-genai SDK).
Das SDK wird erst beim Start geladen: fehlt es, ist der Provider nur "nicht
verfügbar", die App läuft weiter.
"""

from typing import Optional

from providers.base import BaseProvider, ProviderError, split_system, ProviderTurn, ToolCall, valid_text
from config.agent import STEP_TIMEOUT
import uuid
from config.models import MODEL_BY_CAPABILITY
from infrastructure.config import GEMINI_API_KEY
from infrastructure.logger import get_logger

logger = get_logger(__name__)


class GeminiProvider(BaseProvider):
    name = "gemini"
    display_name = "Gemini"
    capabilities = ["general_reasoning", "research"]

    def __init__(self, api_key: str = GEMINI_API_KEY):
        self.client = None
        self._types = None

        if not api_key:
            logger.warning("GEMINI_API_KEY nicht gesetzt — Gemini nicht verfügbar.")
            return
        try:
            from google import genai
            from google.genai import types
        except ImportError:
            logger.warning("Paket 'google-genai' fehlt (pip install google-genai).")
            return

        self._types = types
        self.client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=STEP_TIMEOUT * 1000))
        logger.info("Gemini Provider initialisiert")

    def model_for(self, capability: str) -> Optional[str]:
        models = MODEL_BY_CAPABILITY["gemini"]
        return self.configured_model(capability, models.get(capability, models["default"]))

    def chat(self, messages: list[dict], model: Optional[str] = None) -> str:
        if not self.client:
            raise ProviderError("Gemini ist nicht konfiguriert (API-Key oder Paket fehlt).")

        model_name = model or self.model_for("default")
        system, history = split_system(messages)
        if not history:
            raise ProviderError("Keine User-Nachricht zum Senden.")

        t = self._types
        contents = [
            t.Content(
                role="user" if m["role"] == "user" else "model",
                parts=[t.Part(text=m["content"])],
            )
            for m in history
        ]
        config = t.GenerateContentConfig(system_instruction=system) if system else None

        try:
            response = self.client.models.generate_content(
                model=model_name, contents=contents, config=config
            )
        except Exception as e:
            logger.error('Gemini API-Anfrage fehlgeschlagen (%s)', type(e).__name__)
            raise ProviderError('Gemini-Anfrage fehlgeschlagen.') from None

        text = valid_text(getattr(response, "text", None))
        if not text:
            raise ProviderError("Gemini hat eine leere Antwort geliefert.")
        logger.debug(f"Gemini Antwort erhalten (Modell: {model_name})")
        return text

    def is_available(self) -> bool:
        return self.client is not None

    def supports_tool_calls(self) -> bool:
        return True

    def supports_streaming(self) -> bool:
        return True

    def tool_chat(self, messages, tools, model=None):
        if not self.client:
            raise ProviderError("Gemini ist nicht konfiguriert.")
        t = self._types
        contents = []
        native_ids = {part.get('function_call', {}).get('id')
                      for m in messages if m.get('native', {}).get('provider') == self.name
                      for part in m['native']['content'].get('parts', [])
                      if part.get('function_call', {}).get('id')}
        system = "\n".join(m['content'] for m in messages if m['role'] == 'system')
        for m in messages:
            if m['role'] == 'system':
                continue
            if m.get('native') and m['native'].get('provider') == self.name:
                contents.append(t.Content.model_validate(m['native']['content']))
            elif m['role'] == 'tool':
                part = t.Part(function_response=t.FunctionResponse(
                    id=m.get('call_id') if m.get('call_id') in native_ids else None, name=m['name'], response={'result': m['result']}))
                if contents and contents[-1].role == 'user' and any(p.function_response for p in contents[-1].parts):
                    contents[-1].parts.append(part)
                else:
                    contents.append(t.Content(role='user', parts=[part]))
            else:
                contents.append(t.Content(role='model' if m['role'] == 'assistant' else 'user',
                                          parts=[t.Part(text=m.get('content') or 'Weiter.')]))
        try:
            response = self.client.models.generate_content(
                model=model or self.model_for('default'), contents=contents,
                config=t.GenerateContentConfig(system_instruction=system,
                    tools=[t.Tool(function_declarations=[t.FunctionDeclaration(name=d['name'], description=d['description'],
                        parameters_json_schema=d['parameters']) for d in tools])],
                    automatic_function_calling=t.AutomaticFunctionCallingConfig(disable=True)))
            content = response.candidates[0].content
            calls, texts = [], []
            for part in content.parts or []:
                if part.function_call:
                    call = part.function_call
                    calls.append(ToolCall(call.id or uuid.uuid4().hex, call.name, dict(call.args or {})))
                elif part.text and not part.thought:
                    texts.append(part.text)
            if not calls and not texts:
                raise ProviderError('Gemini hat eine leere Antwort geliefert.')
            return ProviderTurn('\n'.join(texts), calls,
                {'provider': self.name, 'content': content.model_dump(mode='json', exclude_none=True)})
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(f'Gemini Tool-Aufruf fehlgeschlagen: {type(exc).__name__}') from exc
