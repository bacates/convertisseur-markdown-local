"""Fonctions locales de conversion et de stockage des résultats."""

from __future__ import annotations

import mimetypes
import re
import shutil
import sys
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from markitdown import MarkItDown

BASE_DIR = (
    Path(sys.executable).resolve().parent
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parent.parent
)
CONVERSIONS_DIR = BASE_DIR / "conversions"
MAX_FILE_SIZE = 100 * 1024 * 1024

# Formats annoncés comme pris en charge par la bibliothèque Microsoft.
# Audio et vidéo sont volontairement exclus : leur transcription intégrée
# peut appeler un service distant. YouTube est également traité à part.
SUPPORTED_EXTENSIONS = {
    ".pdf", ".pptx", ".docx", ".xlsx", ".xls", ".csv", ".json",
    ".xml", ".html", ".htm", ".txt", ".md", ".markdown", ".epub",
    ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif",
    ".tiff", ".zip", ".eml", ".msg", ".rtf",
}

MIME_BY_EXTENSION = {
    ".pdf": {"application/pdf", "application/x-pdf"},
    ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    ".xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
    ".pptx": {"application/vnd.openxmlformats-officedocument.presentationml.presentation"},
    ".xls": {"application/vnd.ms-excel", "application/x-ole-storage"},
    ".csv": {"text/csv", "application/csv", "text/plain"},
    ".json": {"application/json", "text/json", "text/plain"},
    ".xml": {"application/xml", "text/xml", "text/plain"},
    ".html": {"text/html", "application/xhtml+xml"},
    ".htm": {"text/html", "application/xhtml+xml"},
    ".txt": {"text/plain"}, ".md": {"text/markdown", "text/plain"},
    ".markdown": {"text/markdown", "text/plain"},
    ".epub": {"application/epub+zip", "application/zip"},
    ".jpg": {"image/jpeg"}, ".jpeg": {"image/jpeg"},
    ".png": {"image/png"}, ".webp": {"image/webp"},
    ".gif": {"image/gif"}, ".bmp": {"image/bmp", "image/x-ms-bmp"},
    ".tif": {"image/tiff"}, ".tiff": {"image/tiff"},
    ".zip": {"application/zip", "application/x-zip-compressed"},
    ".eml": {"message/rfc822", "text/plain"},
    ".msg": {"application/vnd.ms-outlook", "application/octet-stream"},
    ".rtf": {"application/rtf", "text/rtf", "text/plain"},
}


class ConversionError(Exception):
    """Erreur compréhensible à afficher pour un fichier donné."""


def safe_filename(name: str) -> str:
    """Réduit le nom à un nom de fichier sans chemin ni caractères dangereux."""
    leaf = Path(name.replace("\\", "/")).name
    safe = re.sub(r"[^\w.() -]", "_", leaf, flags=re.UNICODE).strip(" .")
    return safe[:180] or "fichier"


def validate_upload(filename: str, content_type: str, size: int) -> str:
    """Valide extension, taille et type MIME déclaré par le navigateur."""
    extension = Path(filename).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise ConversionError("Format non pris en charge par MarkItDown")
    if size > MAX_FILE_SIZE:
        raise ConversionError("Fichier trop volumineux : la limite est de 100 Mo.")
    mime = (content_type or "").split(";", 1)[0].strip().lower()
    allowed = MIME_BY_EXTENSION.get(extension, set())
    # Les navigateurs peuvent omettre le MIME ; octet-stream est accepté,
    # mais une déclaration précise incompatible est rejetée.
    if mime and mime != "application/octet-stream" and mime not in allowed:
        raise ConversionError("Le type MIME du fichier ne correspond pas à son extension.")
    return extension


def convert_bytes(filename: str, data: bytes, content_type: str = "") -> tuple[str, str]:
    """Convertit un fichier en mémoire et retourne son nom sûr et son Markdown."""
    safe_name = safe_filename(filename)
    validate_upload(safe_name, content_type, len(data))
    CONVERSIONS_DIR.mkdir(parents=True, exist_ok=True)
    temp_dir = CONVERSIONS_DIR / ".tmp"
    temp_dir.mkdir(exist_ok=True)
    temp_path = temp_dir / f"{uuid.uuid4().hex}{Path(safe_name).suffix.lower()}"
    try:
        temp_path.write_bytes(data)
        return convert_path(safe_name, temp_path, content_type, len(data))
    finally:
        temp_path.unlink(missing_ok=True)
        try:
            temp_dir.rmdir()
        except OSError:
            pass


def convert_path(filename: str, source_path: Path, content_type: str, size: int) -> tuple[str, str]:
    """Convertit un fichier temporaire existant sans le charger en mémoire."""
    safe_name = safe_filename(filename)
    validate_upload(safe_name, content_type, size)
    if size == 0:
        raise ConversionError("Le fichier est vide ou illisible.")
    try:
        result = MarkItDown().convert(str(source_path))
        markdown = result.text_content
        if not isinstance(markdown, str):
            raise ConversionError("MarkItDown n’a pas retourné de contenu Markdown.")
        return safe_name, markdown
    except ConversionError:
        raise
    except Exception as exc:
        raise ConversionError(f"Échec de conversion : {exc.__class__.__name__}.") from exc


def convert_youtube_url(url: str) -> tuple[str, str]:
    """Récupère le titre et la transcription d'une URL YouTube autorisée."""
    parsed = urlparse(url.strip())
    hostname = (parsed.hostname or "").lower()
    domaines_autorises = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}
    if parsed.scheme != "https" or hostname not in domaines_autorises:
        raise ConversionError("Saisissez une URL HTTPS de youtube.com ou youtu.be.")
    try:
        result = MarkItDown().convert(url.strip())
        markdown = result.text_content
        if not isinstance(markdown, str) or not markdown.strip():
            raise ConversionError("Aucune transcription n’a été trouvée pour cette vidéo.")
        title = result.title or "transcription-youtube"
        return safe_filename(title) + ".md", markdown
    except ConversionError:
        raise
    except Exception as exc:
        detail = str(exc).strip().replace("\n", " ")
        if "youtube-transcript-api" in detail.lower() or "dependency" in detail.lower():
            raise ConversionError("La dépendance de transcription YouTube manque. Relancez demarrer.bat pour l’installer.") from exc
        if detail:
            raise ConversionError(f"Impossible de récupérer la transcription : {detail[:400]}") from exc
        raise ConversionError(f"Impossible de récupérer la transcription ({exc.__class__.__name__}).") from exc


def save_conversion(batch_dir: Path, filename: str, markdown: str) -> tuple[str, Path]:
    """Écrit une conversion avec identifiant et nom de fichier sûr."""
    conversion_id = uuid.uuid4().hex
    stem = Path(filename).stem or "conversion"
    output = batch_dir / f"{safe_filename(stem)}-{conversion_id[:8]}.md"
    output.write_text(markdown, encoding="utf-8")
    return conversion_id, output


def create_batch_dir() -> tuple[str, Path]:
    """Crée un dossier de lot horodaté sans écraser les lots précédents."""
    CONVERSIONS_DIR.mkdir(parents=True, exist_ok=True)
    batch_id = uuid.uuid4().hex
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    batch_dir = CONVERSIONS_DIR / f"{timestamp}_{batch_id[:8]}"
    batch_dir.mkdir(parents=True, exist_ok=False)
    return batch_id, batch_dir


def make_zip(batch_dir: Path, zip_path: Path) -> None:
    """Archive uniquement les fichiers Markdown réussis du lot."""
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for markdown_file in sorted(batch_dir.glob("*.md")):
            archive.write(markdown_file, markdown_file.name)
