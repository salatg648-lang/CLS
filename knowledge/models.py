"""Gemeinsame Helfer für Knowledge: Text-Normalisierung, Tokens, Zeilen → Dicts."""

import hashlib
import json
import re
from urllib.parse import urlparse

STOPWORDS = frozenset("""
der die das den dem des ein eine einen einem einer eines und oder aber auch als wie was wer wo wann
warum wieso ist sind war waren wird werden wurde wurden hat haben hatte hatten kann können konnte
soll sollen muss müssen mit von zu zum zur bei nach vor auf aus für über unter durch gegen ohne um
im in an am ich du er sie es wir ihr mich mir dich dir sich mein dein sein ihr unser euer man nur noch
schon sehr mehr viel dass wenn dann denn doch mal bitte
the a an and or but is are was were be been to of in on at for with from by it this that these those
what who how why when where do does did can could should would will
""".split())

NEGATIONS = frozenset("nicht kein keine keinen keinem keiner nie niemals not never no ohne".split())


def normalize(text: str) -> str:
    return " ".join((text or "").lower().split())


def content_hash(text: str) -> str:
    return hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()


def words(text: str) -> list[str]:
    """Nur Buchstaben-Wörter (Unicode), klein geschrieben."""
    return re.findall(r"[^\W\d_]+", (text or "").lower())


def sig_words(text: str) -> set[str]:
    """Bedeutungstragende Wörter (ohne Stopwörter/Verneinungen, min. 3 Zeichen)."""
    return {w for w in words(text) if len(w) >= 3 and w not in STOPWORDS and w not in NEGATIONS}


def numbers(text: str) -> set[str]:
    return set(re.findall(r"\d+(?:[.,]\d+)*", text or ""))


def query_tokens(text: str) -> list[str]:
    """Suchbegriffe (Wörter und Zahlen, ohne Stopwörter), Reihenfolge erhalten, ohne Duplikate."""
    seen, out = set(), []
    for t in re.findall(r"\w+", (text or "").lower()):
        if len(t) >= 2 and t not in STOPWORDS and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def domain_of(url: str) -> str:
    host = urlparse(url or "").netloc.lower()
    return host[4:] if host.startswith("www.") else host


def tags_to_text(tags) -> str:
    return ", ".join(t.strip() for t in (tags or []) if t and t.strip())


def tags_from_text(text: str) -> list[str]:
    return [t.strip() for t in (text or "").split(",") if t.strip()]


def entry_from_row(row: dict) -> dict:
    e = dict(row)
    e["tags"] = tags_from_text(e.get("tags", ""))
    e['strategy'] = json.loads(e.get('strategy', '{}'))
    e.pop("rank", None)
    return e
