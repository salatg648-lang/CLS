"""Tool-Berechtigungen, Datenschutzstufen und exakt freigegebene Befehle (Phase 4–6)."""

# Berechtigungsstufen
PERMISSIONS = {
    "read": "auto",      # auto, confirm, never
    "write": "confirm",
    "delete": "confirm",
    "execute": "confirm",
    "network": "confirm",
}

# Privacy Policy Stufen (Phase 4+)
PRIVACY_LEVELS = [
    "LOCAL_ONLY",              # Datei bleibt lokal, nicht an AI schicken
    "SAFE_FOR_EXTERNAL",       # Darf an externe AI geschickt werden
    "USER_CONFIRMATION_REQUIRED",  # User muss zustimmen
    "BLOCKED",                 # Gar nicht verarbeiten
]

# Sensible Dateien, die niemals an externe AIs geschickt werden dürfen
SENSITIVE_FILES = [".env", "*.key", "*.pem", "credentials*", "secrets*"]

# Exakte Befehle statt Shell-/Argument-Whitelist. Projektcode wird ausgeführt:
# Die Bestätigung gilt nur für den einzelnen Aufruf, niemals für den ganzen Task.
COMMANDS = {
    "python_tests": {"argv": ["{python}", "-m", "unittest", "discover", "-s", "tests", "-v"], "kind": "test"},
    "python_build": {"argv": ["{python}", "-m", "compileall", "-q", "-x", r"(^|[/\\])(\.venv|venv|\.git)([/\\]|$)", "."], "kind": "build"},
}
