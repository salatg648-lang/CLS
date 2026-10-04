"""Lokales Ollama /api/chat mit nativen Tools. Keine Cloud-Modelle im Lokalmodus."""
import json
import http.client
import os
import urllib.request
from urllib.parse import urlparse
from providers.base import BaseProvider, ProviderError, ProviderTurn, ToolCall
from config.models import MODEL_BY_CAPABILITY
from config.providers import PROVIDER_CONFIG


class OllamaProvider(BaseProvider):
    name = 'ollama'
    display_name = 'Ollama (lokal)'
    capabilities = ['general_reasoning', 'research', 'coding', 'local_reasoning']
    is_local = True

    def __init__(self, host=None):
        self.host = (host or os.environ.get('OLLAMA_HOST') or PROVIDER_CONFIG['ollama']['host']).rstrip('/')
        if '://' not in self.host:
            self.host = 'http://' + self.host
        parsed = urlparse(self.host)
        if parsed.scheme != 'http' or parsed.hostname not in ('localhost', '127.0.0.1', '::1') or parsed.username:
            raise ValueError('Lokales Ollama benötigt eine HTTP-Loopback-Adresse.')

    def model_for(self, capability):
        models = MODEL_BY_CAPABILITY['ollama']
        return self.configured_model(capability, os.environ.get('OLLAMA_MODEL') or models.get(capability, models['default']))

    def is_available(self):
        # Konfiguriert, nicht zwingend erreichbar. Kein Netzwerk im UI-Thread.
        return True

    def supports_tool_calls(self):
        return True

    def _post(self, payload):
        model = payload['model']
        if 'cloud' in model.lower() or '/' in model:
            raise ProviderError('Cloud-/Remote-Modelle sind im lokalen Ollama-Provider gesperrt.')
        request = urllib.request.Request(self.host + '/api/chat',
            data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'}, method='POST')
        # Keine Redirects von loopback zu externen Diensten.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
            with opener.open(request, timeout=PROVIDER_CONFIG['ollama']['request_timeout']) as response:
                return json.loads(response.read(2_000_000))
        except (OSError, ValueError, http.client.HTTPException) as exc:
            raise ProviderError(f'Ollama nicht erreichbar oder ungültige Antwort: {type(exc).__name__}') from exc

    def tool_chat(self, messages, tools, model=None):
        converted = []
        for msg in messages:
            if msg.get('native', {}).get('provider') == self.name:
                converted.append(msg['native']['message'])
            elif msg['role'] == 'tool':
                converted.append({'role': 'tool', 'tool_name': msg['name'],
                                  'content': json.dumps(msg['result'], ensure_ascii=False)})
            else:
                converted.append({'role': msg['role'], 'content': msg.get('content') or ''})
        data = self._post({'model': model or self.model_for('default'), 'messages': converted,
                           'stream': False, 'think': False,
                           'tools': [{'type': 'function', 'function': d} for d in tools]})
        try:
            msg = data['message']
            calls = [ToolCall(str(i), c['function']['name'], c['function']['arguments'])
                     for i, c in enumerate(msg.get('tool_calls') or [])]
            text = msg.get('content') or ''
            if not text and not calls:
                raise ValueError('Leere Antwort')
            return ProviderTurn(text, calls, {'provider': self.name, 'message': msg})
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderError('Ungültige native Ollama-Antwort.') from exc

    def chat(self, messages, model=None):
        return self.tool_chat(messages, [], model).text
