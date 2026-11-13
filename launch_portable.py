"""Lanceur léger sans Qt pour l’application de bureau portable."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path


def _message(text: str, title: str = "Convertisseur local en Markdown") -> None:
    """Affiche une boîte de dialogue Windows sans dépendance graphique externe."""
    if os.name == "nt":
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, text, title, 0x10)


def main() -> int:
    """Démarre le cœur de l’application en masquant uniquement sa console."""
    portable_dir = (
        Path(sys.executable).resolve().parent
        if getattr(sys, "frozen", False)
        else Path(__file__).resolve().parent
    )
    core = portable_dir / "ConvertisseurMarkdownCore" / "ConvertisseurMarkdownCore.exe"
    if not core.is_file():
        _message(
            "Le composant de l’application est introuvable.\n"
            "Extrayez tout le contenu du dossier portable avant de démarrer l’application."
        )
        return 1

    env = os.environ.copy()
    env["MARKITDOWN_PORTABLE_HOME"] = str(portable_dir)
    log_path = portable_dir / "demarrage.log"
    try:
        with log_path.open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                [str(core)],
                cwd=portable_dir,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            # Laisse le cœur démarrer assez longtemps pour remonter une erreur.
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                code = process.poll()
                if code is not None:
                    if code != 0:
                        _message(
                            "L’application n’a pas pu démarrer.\n"
                            f"Consultez le journal créé ici :\n{log_path}"
                        )
                    return code
                time.sleep(0.2)
        return 0
    except OSError as exc:
        _message(f"Impossible de démarrer l’application :\n{exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
