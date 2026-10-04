"""Task-/Bereichspolicies als Daten; ausschließlich CLS entscheidet über Fallback-Reife."""
from copy import deepcopy
from tools.safety import PermissionDenied

MODES = ('NEVER', 'FALLBACK', 'ALLOWED')
ALL_AVAILABLE = 'ALL_AVAILABLE'
PROVIDER_FIELDS = {'preferred_providers', 'required_capability', 'selected_provider', 'local_only', 'allow_external'}
KNOWLEDGE_SOURCES = (
    'CLS_KNOWLEDGE', 'PROJECT_KNOWLEDGE', 'EXPERIENCE', 'DOCUMENTATION',
    'EXTERNAL_RESEARCH', 'OTHER_RELEVANT_KNOWLEDGE',
)
SOURCE_LABELS = dict(zip(KNOWLEDGE_SOURCES, (
    'CLS Knowledge', 'Projektwissen', 'Experience', 'Dokumentation',
    'Externe Recherche', 'Sonstige relevante Quellen',
)))


class PolicyDenied(PermissionDenied):
    """Eine fachliche Task-Regel verweigert einen Aufruf (keine Tool-Berechtigung)."""


def _selection(value, field):
    if value is None or (field == 'knowledge_sources' and value == ALL_AVAILABLE):
        return ALL_AVAILABLE if field == 'knowledge_sources' else None
    if not isinstance(value, list) or any(not isinstance(v, str) or not v.strip() for v in value):
        raise ValueError(f'{field} muss eine Liste sein.')
    result = list(dict.fromkeys(v.strip() for v in value))
    if field == 'knowledge_sources' and set(result) - set(KNOWLEDGE_SOURCES):
        raise ValueError('Unbekannte Wissensquelle.')
    return result


def _provider_options(policy, partial=False):
    from capabilities.registry import CAPABILITIES
    values = {'preferred_providers': [], 'required_capability': None, 'selected_provider': None,
              'local_only': False, 'allow_external': True}
    values.update({k: policy[k] for k in PROVIDER_FIELDS if k in policy})
    values['preferred_providers'] = _selection(values['preferred_providers'], 'preferred_providers') or []
    if values['required_capability'] is not None and values['required_capability'] not in CAPABILITIES:
        raise ValueError('Unbekannte erforderliche Capability.')
    selected = values['selected_provider']
    if selected is not None and (not isinstance(selected, str) or not selected.strip()):
        raise ValueError('Ungültige manuelle Provider-Auswahl.')
    for key in ('local_only', 'allow_external'):
        if not isinstance(values[key], bool):
            raise ValueError(f'{key} muss ein Boolean sein.')
    return {k: v for k, v in values.items() if not partial or k in policy}


def normalize(policy):
    """None bleibt Legacy. {} ist eine neue Policy mit FALLBACK / ALL_AVAILABLE."""
    if policy is None:
        return None
    if not isinstance(policy, dict) or set(policy) - ({'mode', 'allowed_providers', 'knowledge_sources', 'areas'} | PROVIDER_FIELDS):
        raise ValueError('Ungültige Task-Policy.')
    result = {'mode': policy.get('mode', 'FALLBACK'),
              'allowed_providers': _selection(policy.get('allowed_providers'), 'allowed_providers'),
              'knowledge_sources': _selection(policy.get('knowledge_sources'), 'knowledge_sources'), 'areas': {}}
    result.update(_provider_options(policy))
    if result['mode'] not in MODES:
        raise ValueError('Unbekannter KI-Modus.')
    areas = policy.get('areas', {})
    if not isinstance(areas, dict) or len(areas) > 20:
        raise ValueError('Bereiche müssen eine Zuordnung mit höchstens 20 Einträgen sein.')
    for name, rule in areas.items():
        if not isinstance(name, str) or not name.strip() or len(name) > 80:
            raise ValueError('Bereich benötigt einen Namen (max. 80 Zeichen).')
        key = name.strip().casefold()
        if key in result['areas'] or not isinstance(rule, dict) or set(rule) - ({'mode', 'allowed_providers', 'knowledge_sources'} | PROVIDER_FIELDS):
            raise ValueError('Ungültige oder doppelte Bereichsregel.')
        clean = {}
        if 'mode' in rule:
            if rule['mode'] not in MODES:
                raise ValueError('Unbekannter KI-Modus im Bereich.')
            clean['mode'] = rule['mode']
        for field in ('allowed_providers', 'knowledge_sources'):
            if field in rule:
                clean[field] = _selection(rule[field], field)
        clean.update(_provider_options(rule, partial=True))
        result['areas'][key] = clean
    return result


def effective(task):
    policy = normalize(task.get('ai_policy'))
    if policy is None:
        return {'mode': 'ALLOWED', 'allowed_providers': None, 'knowledge_sources': ALL_AVAILABLE, **_provider_options({})}
    area = task.get('policy_area')
    if not area:
        return {k: deepcopy(v) for k, v in policy.items() if k != 'areas'}
    rule = policy['areas'].get(area, {})
    return {'mode': rule.get('mode', policy['mode']),
            'allowed_providers': deepcopy(rule.get('allowed_providers', policy['allowed_providers'])),
            # Explizite Vorgabe: nicht gesetztes Bereichswissen bleibt ALL_AVAILABLE.
            'knowledge_sources': deepcopy(rule.get('knowledge_sources', ALL_AVAILABLE)),
            **{key: deepcopy(rule.get(key, policy[key])) for key in PROVIDER_FIELDS}}


def source_allowed(task, source):
    selection = effective(task)['knowledge_sources']
    return selection == ALL_AVAILABLE or source in selection


def check_ai(task, provider):
    policy = effective(task)
    if not provider.enabled or not provider.is_available():
        raise PolicyDenied('Provider ist deaktiviert oder nicht konfiguriert.')
    parent = task.get('ai_policy') or {}
    if not provider.is_local and (policy['local_only'] or not policy['allow_external'] or
                                 parent.get('local_only') or parent.get('allow_external') is False):
        raise PolicyDenied('Externe Provider sind für diesen Task gesperrt.')
    if policy['selected_provider'] and provider.name != policy['selected_provider']:
        raise PolicyDenied('Manuelle Provider-Auswahl erlaubt keinen anderen Provider.')
    if policy['required_capability'] and policy['required_capability'] not in provider.get_capabilities():
        raise PolicyDenied('Provider besitzt die erforderliche Capability nicht.')
    if policy['mode'] == 'NEVER':
        raise PolicyDenied('AI call blocked by task policy: NEVER.')
    if policy['allowed_providers'] is not None and provider.name not in policy['allowed_providers']:
        raise PolicyDenied(f'AI call blocked by task policy: Provider {provider.name} ist nicht erlaubt.')
    if task.get('ai_policy') is None and not (task.get('external') or provider.is_local):
        raise PolicyDenied('AI call blocked by task policy: externe KI ist nicht freigegeben (Legacy).')
    if policy['mode'] == 'FALLBACK' and not (task.get('local_assessment') or {}).get('exhausted'):
        raise PolicyDenied('AI call blocked by task policy: lokale Möglichkeiten noch nicht ausgeschöpft.')


def file_source(path):
    from pathlib import Path
    return 'DOCUMENTATION' if Path(path).suffix.casefold() in ('.md', '.txt', '.rst', '.pdf', '.docx', '.markdown') else 'PROJECT_KNOWLEDGE'
