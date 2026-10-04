"""
Allgemeine Einstellungen für CLS.
 
Einzige Quelle für App-/UI-/Memory-Einstellungen.
(Früher waren Werte hier UND in infrastructure/config.py doppelt.)
"""
 
APP_NAME = "CLS"
APP_VERSION = "0.6.0"
USER_NAME = "Robin"
 
# Sprache / Ton
LANGUAGE = "de"
CASUAL_MODE = True  # "du"-Form
 
# Theme
THEME = "dark"         # "dark" | "light" | "system"
COLOR_THEME = "blue"   # CustomTkinter Color Theme
 
# Fenster
WINDOW_SIZE = "1000x650"
WINDOW_MIN_SIZE = (760, 520)
 
# Memory
MAX_CONVERSATION_MESSAGES = 50  # Rolling Window
 
# Netzwerk
REQUEST_TIMEOUT = 60  # Sekunden pro AI-Anfrage
 
# Logging
LOG_LEVEL = "DEBUG"
LOG_MAX_BYTES = 1_000_000
LOG_BACKUP_COUNT = 3