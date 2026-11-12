"""Démarre l'application uniquement sur l'interface loopback locale."""

import os
import threading
import webbrowser

import uvicorn

if __name__ == "__main__":
    # Ouvre l'interface après le démarrage du serveur, sauf en mode de diagnostic.
    if os.environ.get("MARKITDOWN_NO_BROWSER") != "1":
        threading.Timer(1.2, lambda: webbrowser.open("http://127.0.0.1:8000")).start()
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False)
