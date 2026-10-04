"""
Modell-Namen für die verschiedenen Provider.

Zentrale Stelle: Wenn ein Provider ein neues Modell veröffentlicht,
ändert sich nur diese Datei. Keine Modellnamen im restlichen Code!

HINWEIS: Bitte die Namen gegen die aktuelle Provider-Doku prüfen.
Ein falscher Name führt zu einer Fehlermeldung des Providers (kein Absturz).
"""

GEMINI_MODELS = {
    "flash": "gemini-3.8-flash",   # schnell, Standard
    "pro": "gemini-3.8-pro",       # komplexere Aufgaben
}

PERPLEXITY_MODELS = {
    "sonar": "sonar",                          # Standard, Web-Suche
    "sonar_pro": "sonar-pro",                  # komplexer
    "sonar_reasoning": "sonar-reasoning-pro",  # Deep Reasoning
}

OLLAMA_MODELS = {  # Phase 5
    "default": "qwen3:8b",
    "coder": "qwen3:8b",
}

# Welches Modell nutzt ein Provider für welche Capability?
# Fehlt ein Eintrag, gilt "default".
MODEL_BY_CAPABILITY = {
    "gemini": {
        "default": GEMINI_MODELS["flash"],
        "research": GEMINI_MODELS["pro"],
    },
    "perplexity": {
        "default": PERPLEXITY_MODELS["sonar"],
        "coding": PERPLEXITY_MODELS["sonar_pro"],
        "web_search": PERPLEXITY_MODELS["sonar"],
    },
}

MODEL_BY_CAPABILITY["ollama"] = {"default": OLLAMA_MODELS["default"], "coding": OLLAMA_MODELS["coder"]}
