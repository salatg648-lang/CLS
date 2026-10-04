"""
Routing-Konfiguration (Phase 2).
 
Regeln, nach denen der Router aus Modus + Text eine Capability wählt.
Reine Daten — die Logik liegt in core/router.py.
"""
 
# Chat-Modi in der UI. "chat" = automatisches Routing anhand des Textes.
MODES = ("chat", "research", "coding")
 
# Modi mit fester Capability (überspringt die Keyword-Erkennung)
MODE_CAPABILITY = {
    "research": "research",
    "coding": "coding",
}
 
# Keyword-Erkennung im Modus "chat". Reihenfolge = Priorität.
# Patterns sind Regex (case-insensitive) — \b verhindert Treffer mitten im Wort.
KEYWORD_RULES = [
    ("coding", [
        r"```", r"\bcode\b", r"\bbug", r"\bfehler", r"\bexception", r"\btraceback",
        r"\bfunktion", r"\bklasse\b", r"\bpython\b", r"\bjava\b", r"\bjavascript\b",
        r"\bkotlin\b", r"\bcompil", r"\bbuild\b", r"\bgradle\b", r"\bmods?\b",
        r"\bfabric\b", r"\brefactor", r"\bimplementier", r"\bprogrammier", r"\bscript\b",
    ]),
    ("web_search", [
        r"\baktuell", r"\bneueste", r"\bnews\b", r"\bnachrichten\b", r"\bheute\b",
        r"\bgerade\b", r"\bpreis", r"\bkurs\b", r"\bwetter\b", r"\bim web\b",
        r"\bgoogl", r"\bquelle",
    ]),
    ("research", [
        r"\brecherchier", r"\bdokumentation\b", r"\bvergleich", r"\bunterschied\b",
        r"\bzusammenfassung\b", r"\bausführlich", r"\berklär",
    ]),
]
 
# Wenn für eine Capability kein Provider verfügbar ist: Ersatz-Capabilities.
CAPABILITY_FALLBACKS = {
    "coding": ["general_reasoning"],
    "web_search": ["research", "general_reasoning"],
    "research": ["general_reasoning"],
}
 
DEFAULT_CAPABILITY = "general_reasoning"