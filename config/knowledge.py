"""
Knowledge-Konfiguration (Phase 3).

Reine Daten: Trust-Levels, Quellen-Typen, Limits. Die Logik liegt in knowledge/.
"""

# Trust-Levels (Reihenfolge = Verlässlichkeit, oben am höchsten)
TRUST_LEVELS = ("CONFIRMED", "SUPPORTED", "UNCERTAIN", "CONFLICTING", "OUTDATED", "CANDIDATE")

TRUST_LABELS = {
    "CONFIRMED": "BESTÄTIGT",
    "SUPPORTED": "GESICHERT",
    "UNCERTAIN": "UNSICHER",
    "CONFLICTING": "WIDERSPRÜCHLICH",
    "OUTDATED": "VERALTET",
    "CANDIDATE": "KANDIDAT (ungeprüft)",
}

# Kleiner Bonus beim Sortieren der Suchergebnisse
TRUST_SEARCH_BONUS = {
    "CONFIRMED": 0.3, "SUPPORTED": 0.2, "CONFLICTING": 0.1,
    "UNCERTAIN": 0.05, "CANDIDATE": 0.0, "OUTDATED": -0.5,
}

# Quellen-Typen (Provenance)
SOURCE_TYPES = ("user", "document", "ai_provider", "web", "system", "experience")

# Start-Trust je nach Herkunft. AI-Antworten sind NIE automatisch Wissen (Candidate).
DEFAULT_TRUST_BY_SOURCE = {
    "user": "CONFIRMED",
    "document": "SUPPORTED",
    "system": "SUPPORTED",
    "ai_provider": "CANDIDATE",
    "web": "CANDIDATE",
    "experience": "CANDIDATE",
}

# Eintrags-Arten
KINDS = ("fact", "answer", "chunk", "strategy")

# --- Kontext (was darf in den AI-Prompt?) ---
CONTEXT_TRUST_LEVELS = ("CONFIRMED", "SUPPORTED", "UNCERTAIN", "CONFLICTING")
# Strategien benötigen später ein eigenes Verifikations-Gate, zusätzlich zum Trust.
CONTEXT_KINDS = ("fact", "answer", "chunk")
MAX_KNOWLEDGE_IN_CONTEXT = 5
MAX_CHARS_PER_ENTRY_IN_CONTEXT = 700
MAX_PROJECT_INSTRUCTIONS_CHARS = 1500

# --- Controlled Learning ---
AUTO_CANDIDATES = True
AUTO_CANDIDATE_CAPABILITIES = ("research", "web_search")
AUTO_CANDIDATE_MIN_CHARS = 200
AUTO_CANDIDATE_MAX_CHARS = 6000

# --- Conflict Detection ---
CONFLICT_MIN_SIMILARITY = 0.6     # Wort-Überlappung, ab der zwei Einträge "vom selben Thema" sind
CONFLICT_MAX_CHARS = 800          # längere Texte (Dokument-Chunks etc.) werden nicht geprüft
CONFLICT_CANDIDATES_LIMIT = 15

# --- Ingestion ---
CHUNK_SIZE = 1200
CHUNK_OVERLAP = 150
MAX_INGEST_FILE_MB = 20
MAX_CHUNKS_PER_DOCUMENT = 500
TEXT_EXTENSIONS = (".txt", ".md", ".markdown", ".rst", ".log", ".csv", ".json",
                   ".py", ".java", ".kt", ".js", ".ts", ".html", ".css", ".xml",
                   ".yml", ".yaml", ".toml", ".ini", ".gradle", ".properties")
DOCUMENT_EXTENSIONS = (".pdf", ".docx")

# Selektiver Task-/Provider-Kontext (Zeichen, keine geschätzten Tokens).
CONTEXT_MAX_ENTRIES = 8
CONTEXT_ENTRY_CHARS = 700
CONTEXT_MAX_CHARS = 10000  # einschließlich Herkunft/Referenzen
CONTEXT_RETRIEVAL_LIMIT = 100
CONTEXT_MAX_AGE_DAYS = 365  # Aktualität ungeprüft, keine automatische Abwertung
PROVIDER_REQUEST_MAX_CHARS = 40000
TOOL_CONTEXT_CHARS = 1200
