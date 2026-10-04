"""
Pfad-Definitionen — Zentrale Stelle für alle Pfade.

Zweck: Verhindert hartcodierte Pfade überall im Code.
Jedes Modul importiert von hier, statt eigene Pfade zu bauen.
"""

import os
from pathlib import Path

# Projekt-Root (zwei Ebenen über dieser Datei)
ROOT = Path(__file__).resolve().parent.parent

# Daten-Verzeichnis
DATA = Path(os.environ["CLS_DATA_DIR"]).expanduser().resolve() if os.environ.get("CLS_DATA_DIR") else ROOT / "data"
LOGS = DATA / "logs"

# Memory-Dateien
CONVERSATION_FILE = DATA / "conversation.json"
LONGTERM_MEMORY_FILE = DATA / "longterm_memory.json"

# Prompts
PROMPTS = ROOT / "prompts"
KNOWLEDGE_PROMPT = PROMPTS / "knowledge.txt"
DEFAULT_PROMPT = PROMPTS / "default.txt"
CODING_PROMPT = PROMPTS / "coding.txt"
RESEARCH_PROMPT = PROMPTS / "research.txt"

# SQLite-Datenbank (Phase 3+): Knowledge, Projekte
DB_FILE = DATA / "cls.db"

# Knowledge Base (Phase 3+)
KNOWLEDGE = DATA / "knowledge"
KNOWLEDGE_DOCUMENTS = KNOWLEDGE / "documents"   # Kopien importierter Dateien

# Projects (Phase 3+)
PROJECTS = DATA / "projects"

# CLS darf nur in diesen Verzeichnissen lesen (Phase 4+ Security)
# Vorbereitet für spätere Tool-Sicherheit
ALLOWED_READ_DIRS = [DATA, KNOWLEDGE, PROJECTS]
ALLOWED_WRITE_DIRS = [DATA, KNOWLEDGE, PROJECTS]
