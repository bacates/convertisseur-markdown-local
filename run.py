"""Démarre l'application uniquement sur l'interface loopback locale."""

import threading
import webbrowser

import uvicorn

if __name__ == "__main__":
    # Ouvre l'interface après le démarrage du serveur, sans bloquer Uvicorn.
    threading.Timer(1.2, lambda: webbrowser.open("http://127.0.0.1:8000")).start()
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False)
