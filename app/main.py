"""API FastAPI pour le convertisseur MarkItDown local."""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

from fastapi import Body, FastAPI, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.conversion import (
    CONVERSIONS_DIR, ConversionError, SUPPORTED_EXTENSIONS, convert_path,
    convert_youtube_url,
    create_batch_dir, make_zip, save_conversion, validate_upload,
)

ROOT = Path(__file__).resolve().parent
app = FastAPI(title="Convertisseur local en Markdown", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
_results: dict[str, Path] = {}
_batches: dict[str, Path] = {}


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    return HTMLResponse((ROOT / "templates" / "index.html").read_text(encoding="utf-8"))


@app.get("/api/supported-extensions")
async def supported_extensions() -> dict[str, object]:
    return {"extensions": sorted(SUPPORTED_EXTENSIONS), "max_file_size": 100 * 1024 * 1024,
            "local_only": True, "audio": False,
            "youtube": importlib.util.find_spec("youtube_transcript_api") is not None}


@app.post("/api/convert")
async def convert(files: list[UploadFile] = File(...), batch_id: str | None = None) -> JSONResponse:
    """Convertit les fichiers l'un après l'autre, en isolant chaque erreur."""
    if not files:
        raise HTTPException(status_code=400, detail="Sélectionnez au moins un fichier.")
    # Le navigateur peut fournir un UUID pour regrouper ses requêtes séquentielles
    # dans une seule archive ZIP. Seuls les lots créés par ce processus sont réutilisés.
    if batch_id and batch_id in _batches:
        batch_dir = _batches[batch_id]
    else:
        batch_id, batch_dir = create_batch_dir()
        _batches[batch_id] = batch_dir
    results = []
    for upload in files:
        filename = upload.filename or "fichier"
        # Lecture par morceaux pour appliquer la limite avant de charger tout
        # fichier démesuré en mémoire.
        CONVERSIONS_DIR.mkdir(parents=True, exist_ok=True)
        temp_dir = CONVERSIONS_DIR / ".tmp"
        temp_dir.mkdir(exist_ok=True)
        temp_path = temp_dir / f"{uuid.uuid4().hex}{Path(filename).suffix.lower()}"
        size = 0
        try:
            validate_upload(filename, upload.content_type or "", 0)
            with temp_path.open("wb") as temporary_file:
                while True:
                    chunk = await upload.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > 100 * 1024 * 1024:
                        raise ConversionError("Fichier trop volumineux : la limite est de 100 Mo.")
                    temporary_file.write(chunk)
            safe_name, markdown = convert_path(filename, temp_path, upload.content_type or "", size)
            conversion_id, output_path = save_conversion(batch_dir, safe_name, markdown)
            _results[conversion_id] = output_path
            results.append({"conversion_id": conversion_id, "filename": safe_name,
                            "status": "success", "size": size})
        except ConversionError as exc:
            results.append({"filename": Path(filename.replace("\\", "/")).name,
                            "status": "error", "size": size, "error": str(exc)})
        except Exception as exc:
            results.append({"filename": Path(filename.replace("\\", "/")).name,
                            "status": "error", "size": size,
                            "error": f"Fichier illisible ou corrompu ({exc.__class__.__name__})."})
        finally:
            temp_path.unlink(missing_ok=True)
            try:
                temp_dir.rmdir()
            except OSError:
                pass
            await upload.close()
    zip_path = batch_dir / "conversions.zip"
    if any(item["status"] == "success" for item in results):
        make_zip(batch_dir, zip_path)
    return JSONResponse({"batch_id": batch_id, "results": results})


@app.post("/api/convert-youtube")
async def convert_youtube(payload: dict = Body(...)) -> JSONResponse:
    """Convertit une URL YouTube autorisée en récupérant sa transcription."""
    url = payload.get("url", "")
    try:
        filename, markdown = await run_in_threadpool(convert_youtube_url, str(url))
    except ConversionError as exc:
        message = str(exc)
        status = 422 if "https" in message.lower() else 502
        raise HTTPException(status_code=status, detail=message) from exc
    requested_batch = payload.get("batch_id")
    if isinstance(requested_batch, str) and requested_batch in _batches:
        batch_id = requested_batch
        batch_dir = _batches[batch_id]
    else:
        batch_id, batch_dir = create_batch_dir()
        _batches[batch_id] = batch_dir
    conversion_id, output_path = save_conversion(batch_dir, filename, markdown)
    _results[conversion_id] = output_path
    make_zip(batch_dir, batch_dir / "conversions.zip")
    return JSONResponse({"batch_id": batch_id, "result": {
        "conversion_id": conversion_id, "filename": filename,
        "status": "success", "size": len(markdown.encode("utf-8")),
    }})


@app.get("/api/download/{conversion_id}")
async def download(conversion_id: str) -> FileResponse:
    path = _results.get(conversion_id)
    if not path or not path.is_file():
        raise HTTPException(status_code=404, detail="Conversion introuvable.")
    return FileResponse(path, media_type="text/markdown; charset=utf-8", filename=path.name)


@app.get("/api/download-zip/{conversion_id}")
async def download_zip(conversion_id: str) -> FileResponse:
    batch = _batches.get(conversion_id)
    path = batch / "conversions.zip" if batch else None
    if not path or not path.is_file():
        raise HTTPException(status_code=404, detail="Archive introuvable pour ce lot.")
    return FileResponse(path, media_type="application/zip", filename=f"conversions-{conversion_id[:8]}.zip")


@app.get("/api/preview/{conversion_id}")
async def preview(conversion_id: str) -> dict[str, str]:
    path = _results.get(conversion_id)
    if not path or not path.is_file():
        raise HTTPException(status_code=404, detail="Conversion introuvable.")
    return {"markdown": path.read_text(encoding="utf-8")}
