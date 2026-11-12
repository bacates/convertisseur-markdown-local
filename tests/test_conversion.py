"""Tests unitaires des contrôles de conversion."""

import pytest

from app import conversion


def test_conversion_fichier_texte(tmp_path, monkeypatch):
    """Un texte UTF-8 produit du Markdown et laisse le dossier temporaire propre."""
    monkeypatch.setattr(conversion, "CONVERSIONS_DIR", tmp_path / "conversions")
    filename, markdown = conversion.convert_bytes("bonjour.txt", "Bonjour le monde !".encode(), "text/plain")
    assert filename == "bonjour.txt"
    assert "Bonjour le monde !" in markdown
    assert not (tmp_path / "conversions" / ".tmp").exists()


def test_fichier_non_pris_en_charge():
    """Une extension inconnue reçoit le message français prévu."""
    with pytest.raises(conversion.ConversionError, match="Format non pris en charge par MarkItDown"):
        conversion.convert_bytes("programme.exe", b"contenu", "application/octet-stream")


def test_rejette_mime_incompatible():
    with pytest.raises(conversion.ConversionError, match="MIME"):
        conversion.validate_upload("image.png", "application/pdf", 10)


def test_rejette_fichier_trop_volumineux():
    with pytest.raises(conversion.ConversionError, match="100 Mo"):
        conversion.validate_upload("document.txt", "text/plain", conversion.MAX_FILE_SIZE + 1)
