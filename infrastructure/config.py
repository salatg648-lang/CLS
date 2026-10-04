"""
Lädt .env (API-Keys) und stellt sie bereit.

Alle anderen Einstellungen stehen in config/ (settings, models, providers).
Hier stehen bewusst KEINE Duplikate davon.
"""

import os
from dotenv import load_dotenv

from infrastructure.paths import ROOT
from config.settings import APP_NAME, APP_VERSION, USER_NAME  # noqa: F401 (Re-Export)

# Explizit die .env im Projekt-Root laden (nicht vom Arbeitsverzeichnis abhängig)
load_dotenv(ROOT / ".env")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY", "")


def provider_key(name, env_path=None):
    """Keys dynamisch lesen; Settings enthalten ausschließlich die Variable, nie den Wert."""
    from config.providers import PROVIDER_CONFIG
    from dotenv import dotenv_values
    variable = PROVIDER_CONFIG[name].get('api_key_env')
    if not variable:
        return ''
    values = dotenv_values(env_path or ROOT / '.env')
    return values.get(variable, os.getenv(variable, '')) or ''


def save_provider_key(name, value, env_path=None):
    from config.providers import PROVIDER_CONFIG
    from dotenv import set_key
    from pathlib import Path
    variable = PROVIDER_CONFIG[name].get('api_key_env')
    if not variable or not isinstance(value, str) or any(c in value for c in '\r\n\x00'):
        raise ValueError('Ungültiger API-Key.')
    path = Path(env_path or ROOT / '.env')
    if path.is_symlink():
        raise ValueError('.env darf kein symbolischer Link sein.')
    fd = os.open(path, os.O_CREAT | os.O_WRONLY, 0o600)
    os.close(fd)
    os.chmod(path, 0o600)
    set_key(str(path), variable, value.strip())
    os.chmod(path, 0o600)
