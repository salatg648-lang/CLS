"""
Storage-Abstraktion — einheitliche Schnittstelle für Datenzugriff.

Phase 1-2: JSON-Dateien. Ab Phase 3: SQLite für strukturierte Daten.

Sicherheit:
- Schreiben ist atomar (temp-Datei + os.replace) → kein halb geschriebenes File.
- Ist eine JSON-Datei kaputt, wird sie als *.corrupt-<zeit> gesichert, bevor
  sie beim nächsten Speichern überschrieben wird. Kein stiller Datenverlust.
"""

import json
import os
import shutil
from datetime import datetime
from pathlib import Path

from infrastructure.logger import get_logger

logger = get_logger(__name__)


def load_json(filepath: Path) -> list | dict | None:
    """Lädt JSON. None, wenn die Datei fehlt oder nicht lesbar ist."""
    filepath = Path(filepath)
    if not filepath.exists():
        return None

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = filepath.with_name(f"{filepath.name}.corrupt-{stamp}")
        try:
            shutil.copy2(filepath, backup)
            logger.error(f"{filepath} nicht lesbar ({e}). Backup: {backup}")
        except Exception as copy_err:
            logger.error(f"{filepath} nicht lesbar ({e}); Backup fehlgeschlagen: {copy_err}")
        return None


def save_json(filepath: Path, data: list | dict) -> bool:
    """Speichert JSON atomar. True bei Erfolg."""
    filepath = Path(filepath)
    tmp = filepath.with_name(filepath.name + ".tmp")
    try:
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, filepath)
        return True
    except Exception as e:
        logger.error(f"Fehler beim Speichern von {filepath}: {e}")
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        return False
