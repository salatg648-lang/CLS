"""
Provider-Konfiguration.
 
Definiert, welche Provider aktiv sind und in welcher Reihenfolge
sie für eine Capability bevorzugt werden.
"""
 
# Welche Provider werden geladen? (Reihenfolge = Standard-Priorität)
ACTIVE_PROVIDERS = ["gemini", "perplexity", "groq", "openrouter", "cometapi", "ollama"]
 
PROVIDER_CONFIG = {
    "gemini": {
        "enabled": True,
        "api_key_env": "GEMINI_API_KEY",
    },
    "perplexity": {
        "enabled": True,   # Phase 2
        "api_key_env": "PERPLEXITY_API_KEY",
        "base_url": "https://api.perplexity.ai/chat/completions",
    },
    "ollama": {
        "enabled": False,  # Phase 5
        "host": "http://localhost:11434",
        "request_timeout": 180,  # Lokale Inferenz kann länger als ein Tool-Schritt dauern.
    },
    "groq": {"enabled": False, "api_key_env": "GROQ_API_KEY",
             "base_url": "https://api.groq.com/openai/v1/chat/completions"},
    "openrouter": {"enabled": False, "api_key_env": "OPENROUTER_API_KEY",
                   "base_url": "https://openrouter.ai/api/v1/chat/completions"},
    "cometapi": {"enabled": False, "api_key_env": "COMETAPI_API_KEY",
                 "base_url": "https://api.cometapi.com/v1/chat/completions"},
}
 
# Bevorzugte Provider pro Capability (der erste verfügbare gewinnt).
CAPABILITY_PREFERENCE = {
    "general_reasoning": ["gemini", "perplexity"],
    "research": ["gemini", "perplexity"],
    "web_search": ["perplexity", "gemini"],
    "coding": ["perplexity", "gemini"],
}