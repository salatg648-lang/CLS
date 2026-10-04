"""
Knowledge Ingestion — Datei → Textstücke (Chunks) → Knowledge-Einträge.

Unterstützt: Textdateien (.txt, .md, Code, ...), .pdf (braucht 'pypdf'), .docx (ohne Zusatzpaket).
- Jeder Chunk wird ein Eintrag (Art 'chunk', Trust SUPPORTED, Quelle = Dokument + Teil-Nummer).
- Dieselbe Datei (gleicher Hash) wird im selben Projekt nicht doppelt importiert.
- Die Originaldatei wird nach data/knowledge/documents/ kopiert (große Dateien gehören in Dateien).
- Sensible Dateien (.env, *.key, ...) werden nie importiert (config/permissions.py).
- Alles oder nichts: bei einem Fehler wird nichts gespeichert.
"""

import fnmatch
import hashlib
import io
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from config import knowledge as cfg
from config.permissions import SENSITIVE_FILES
from infrastructure.database import Database, now
from infrastructure.logger import get_logger
from infrastructure.paths import KNOWLEDGE_DOCUMENTS
from knowledge.base import KnowledgeBase

logger = get_logger(__name__)

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_MAX_XML_BYTES = 50 * 1024 * 1024


# ----------------------------------------------------------------- Text-Extraktion

def extract_text(name: str, data: bytes) -> str:
    ext = Path(name).suffix.lower()
    if ext == ".pdf":
        return _extract_pdf(data)
    if ext == ".docx":
        return _extract_docx(data)
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def _extract_pdf(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as e:
        raise ValueError("PDF-Import braucht das Paket 'pypdf' (pip install pypdf).") from e
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ValueError("Das PDF ist verschlüsselt.")
        pages = [(page.extract_text() or "").strip() for page in reader.pages]
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"PDF konnte nicht gelesen werden: {e}") from e
    text = "\n\n".join(p for p in pages if p)
    if not text:
        raise ValueError("Im PDF wurde kein Text gefunden (evtl. gescannt — OCR gibt es noch nicht).")
    return text


def _extract_docx(data: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            info = z.getinfo("word/document.xml")
            if info.file_size > _MAX_XML_BYTES:
                raise ValueError("Die Word-Datei ist zu groß.")
            root = ET.fromstring(z.read("word/document.xml"))
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as e:
        raise ValueError(f"Word-Datei konnte nicht gelesen werden: {e}") from e
    paragraphs = []
    for p in root.iter(f"{_W}p"):
        text = "".join(t.text or "" for t in p.iter(f"{_W}t")).strip()
        if text:
            paragraphs.append(text)
    return "\n\n".join(paragraphs)


# ----------------------------------------------------------------- Chunking

def chunk_text(text: str, size: int = cfg.CHUNK_SIZE, overlap: int = cfg.CHUNK_OVERLAP) -> list[str]:
    """Teilt an Absätzen; zu lange Absätze werden mit Überlappung an Wortgrenzen geteilt."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text.replace("\r\n", "\n")) if p.strip()]
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        if len(para) > size:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(_split_long(para, size, overlap))
        elif current and len(current) + 2 + len(para) > size:
            chunks.append(current)
            current = para
        else:
            current = f"{current}\n\n{para}" if current else para
    if current:
        chunks.append(current)
    return chunks


def _split_long(text: str, size: int, overlap: int) -> list[str]:
    pieces, start = [], 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            space = text.rfind(" ", start + size // 2, end)
            if space > start:
                end = space
        piece = text[start:end].strip()
        if piece:
            pieces.append(piece)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return pieces


# ----------------------------------------------------------------- Ingestor

class Ingestor:
    def __init__(self, kb: KnowledgeBase, documents_dir: Path = KNOWLEDGE_DOCUMENTS):
        self.kb = kb
        self.db: Database = kb.db
        self.documents_dir = Path(documents_dir)

    def ingest_file(self, path, project_id: int | None = None, topic: str = "") -> dict:
        """
        Rückgabe: {"document": {...}, "chunks": n, "skipped": bool}
        Raises ValueError mit verständlicher Meldung.
        """
        p = Path(path)
        from tools.privacy import PrivacyPolicy
        from tools.safety import sensitive
        if sensitive(p.resolve()):
            raise ValueError('Diese sensible Datei darf nicht importiert werden.')
        PrivacyPolicy(self.db).check(p)
        if not p.is_file():
            raise ValueError(f"Datei nicht gefunden: {p}")
        name = p.name
        if any(fnmatch.fnmatch(name.lower(), pat.lower()) for pat in SENSITIVE_FILES):
            raise ValueError(f"'{name}' sieht nach einer sensiblen Datei aus (Schlüssel/Zugangsdaten) "
                             "und wird nicht importiert.")
        ext = p.suffix.lower()
        if ext not in cfg.TEXT_EXTENSIONS + cfg.DOCUMENT_EXTENSIONS:
            raise ValueError(f"Dateityp '{ext or 'ohne Endung'}' wird nicht unterstützt.")
        size = p.stat().st_size
        if size > cfg.MAX_INGEST_FILE_MB * 1024 * 1024:
            raise ValueError(f"Datei ist größer als {cfg.MAX_INGEST_FILE_MB} MB.")

        data = p.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        existing = self.db.query_one(
            "SELECT * FROM knowledge_documents WHERE sha256 = ? AND project_id IS ?", (digest, project_id))
        if existing:
            self.db.execute('INSERT OR IGNORE INTO document_origins VALUES (?,?)',
                            (existing['id'], str(p.resolve())))
            return {"document": existing, "chunks": 0, "skipped": True}

        text = extract_text(name, data)
        chunks = chunk_text(text)
        if not chunks:
            raise ValueError("Die Datei enthält keinen Text.")
        if len(chunks) > cfg.MAX_CHUNKS_PER_DOCUMENT:
            raise ValueError(f"Die Datei ist zu umfangreich ({len(chunks)} Teile, "
                             f"max. {cfg.MAX_CHUNKS_PER_DOCUMENT}). Bitte in kleinere Dateien aufteilen.")

        stored, created_file = self._store_copy(name, digest, data)
        try:
            doc = self._save_document(name, str(stored), digest, size, chunks,
                                      project_id, topic or p.stem, str(p.resolve()))
        except Exception:
            if created_file:
                stored.unlink(missing_ok=True)
            raise
        logger.info(f"Dokument importiert: {name} ({doc['chunk_count']} Teile)")
        return {"document": doc, "chunks": doc["chunk_count"], "skipped": False}

    def list_documents(self, project_id: int | None = None) -> list[dict]:
        if project_id is None:
            return self.db.query("SELECT * FROM knowledge_documents ORDER BY id DESC")
        return self.db.query("SELECT * FROM knowledge_documents WHERE project_id = ? ORDER BY id DESC",
                             (project_id,))

    def delete_document(self, doc_id: int) -> bool:
        doc = self.db.query_one("SELECT * FROM knowledge_documents WHERE id = ?", (doc_id,))
        if not doc:
            return False
        with self.db.transaction():
            self.db.execute("DELETE FROM knowledge_entries WHERE document_id = ?", (doc_id,))
            self.db.execute("DELETE FROM knowledge_documents WHERE id = ?", (doc_id,))
            still_used = self.db.query_one(
                "SELECT 1 AS x FROM knowledge_documents WHERE stored_path = ?", (doc["stored_path"],))
        if doc["stored_path"] and not still_used:
            self._safe_remove(Path(doc["stored_path"]))
        logger.info(f"Dokument gelöscht: {doc['filename']}")
        return True

    # --- intern ---

    def _save_document(self, name, stored_path, digest, size, chunks, project_id, topic, original_path) -> dict:
        with self.db.transaction():
            cur = self.db.execute(
                "INSERT INTO knowledge_documents(project_id, filename, stored_path, sha256, size_bytes, "
                "chunk_count, ingested_at) VALUES (?,?,?,?,?,?,?)",
                (project_id, name, stored_path, digest, size, 0, now()))
            doc_id = cur.lastrowid
            self.db.execute('INSERT INTO document_origins VALUES (?,?)', (doc_id, original_path))
            total, made = len(chunks), 0
            for i, chunk in enumerate(chunks, 1):
                result = self.kb.add_entry(
                    chunk, title=f"{name} · Teil {i}/{total}", topic=topic, source_type="document",
                    source_name=name, reference=f"Teil {i}/{total}", project_id=project_id,
                    kind="chunk", document_id=doc_id, check_conflicts=False)
                made += 1 if result["created"] else 0
            self.db.execute("UPDATE knowledge_documents SET chunk_count = ? WHERE id = ?", (made, doc_id))
        return self.db.query_one("SELECT * FROM knowledge_documents WHERE id = ?", (doc_id,))

    def _store_copy(self, name: str, digest: str, data: bytes) -> tuple[Path, bool]:
        safe = re.sub(r"[^\w.\-]+", "_", name)[:120] or "dokument"
        self.documents_dir.mkdir(parents=True, exist_ok=True)
        dest = self.documents_dir / f"{digest[:12]}_{safe}"
        if not dest.resolve().is_relative_to(self.documents_dir.resolve()):
            raise ValueError("Ungültiger Dateiname.")
        if dest.exists():
            return dest, False
        dest.write_bytes(data)
        return dest, True

    def _safe_remove(self, path: Path) -> None:
        try:
            if path.resolve().is_relative_to(self.documents_dir.resolve()):
                path.unlink(missing_ok=True)
        except OSError as e:
            logger.warning(f"Kopie konnte nicht gelöscht werden: {e}")
