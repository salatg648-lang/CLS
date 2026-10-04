"""Groq, OpenRouter und CometAPI über ihre Chat-Completions-Schnittstelle."""
import json
import http.client
import urllib.error
import urllib.request
from copy import deepcopy

from config.providers import PROVIDER_CONFIG
from config.settings import REQUEST_TIMEOUT
from providers.base import BaseProvider, ProviderError, ProviderTurn, ToolCall, valid_text, validate_turn


class OpenAICompatibleProvider(BaseProvider):
    capabilities = ['general_reasoning', 'research', 'coding']

    def __init__(self, name, api_key='', *, base_url=None):
        self.name = name
        self.display_name = {'groq': 'Groq', 'openrouter': 'OpenRouter', 'cometapi': 'CometAPI'}[name]
        self.api_key = api_key
        self.url = base_url or PROVIDER_CONFIG[name]['base_url']

    def is_available(self):
        return bool(self.api_key and self.model_for('default'))

    def model_for(self, capability):
        return self.configured_model(capability, '')

    def supports_tool_calls(self):
        return True

    def _post(self, payload):
        if not self.api_key:
            raise ProviderError(f'{self.display_name}: API-Key fehlt.')
        if not payload['model']:
            raise ProviderError(f'{self.display_name}: Modell fehlt.')
        request = urllib.request.Request(self.url, data=json.dumps(payload).encode(),
            headers={'Authorization': 'Bearer ' + self.api_key, 'Content-Type': 'application/json'}, method='POST')
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None
        try:
            with urllib.request.build_opener(NoRedirect()).open(request, timeout=REQUEST_TIMEOUT) as response:
                return json.loads(response.read(2_000_000))
        except urllib.error.HTTPError as exc:
            # Bodies/URLs können Keys, Prompts oder Provider-interne Daten enthalten.
            raise ProviderError(f'{self.display_name}: HTTP {exc.code}.') from None
        except (OSError, ValueError, http.client.HTTPException) as exc:
            raise ProviderError(f'{self.display_name}: Anfrage fehlgeschlagen ({type(exc).__name__}).') from None

    def tool_chat(self, messages, tools, model=None):
        converted = []
        for message in messages:
            if message.get('native', {}).get('provider') == self.name:
                converted.append(deepcopy(message['native']['message']))
            elif message['role'] == 'tool':
                converted.append({'role': 'tool', 'tool_call_id': message['call_id'],
                                  'content': json.dumps(message['result'], ensure_ascii=False)})
            elif message.get('native'):
                raise ProviderError('Nativer Verlauf eines anderen Providers ist nicht übertragbar.')
            else:
                converted.append({'role': message['role'], 'content': message.get('content') or ''})
        payload = {'model': model or self.model_for('default'), 'messages': converted, 'stream': False}
        if tools:
            payload['tools'] = [{'type': 'function', 'function': definition} for definition in tools]
        data = self._post(payload)
        try:
            if not isinstance(data, dict) or data.get('error'):
                raise ValueError('Providerfehler')
            choice = data['choices'][0]
            if choice.get('finish_reason') in ('length', 'content_filter', 'error'):
                raise ValueError('Unvollständige Antwort')
            message = choice['message']
            calls = []
            for call in message.get('tool_calls') or []:
                if call['type'] != 'function':
                    raise ValueError('Unbekannter Tool-Typ')
                calls.append(ToolCall(call['id'], call['function']['name'], json.loads(call['function']['arguments'])))
            turn = ProviderTurn(message.get('content') or '', calls,
                                {'provider': self.name, 'message': message})
            return validate_turn(turn)
        except (KeyError, IndexError, TypeError, ValueError, AttributeError):
            raise ProviderError(f'{self.display_name}: Ungültige Chat-Completions-Antwort.') from None

    def chat(self, messages, model=None):
        turn = self.tool_chat(messages, [], model)
        if turn.calls:
            raise ProviderError('Unerwartete Tool-Aufrufe in einer Textantwort.')
        return valid_text(turn.text)
