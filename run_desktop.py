"""Démarre la version native de bureau, sans ouvrir de navigateur."""

import ctypes
import os
import sys
from pathlib import Path


# En mode empaqueté, préférer explicitement les DLL du dossier livré avec
# l'application aux éventuelles versions de Qt installées ailleurs sur le PC.
_DLL_DIRECTORY_HANDLES = []
if getattr(sys, "frozen", False) and sys.platform == "win32":
    _bundle_root = Path(sys._MEIPASS)
    _dll_directories = [
        _bundle_root / "PySide6",
        _bundle_root / "shiboken6",
        _bundle_root,
    ]
    _existing_path = os.environ.get("PATH", "")
    for _directory in _dll_directories:
        if _directory.is_dir():
            _DLL_DIRECTORY_HANDLES.append(os.add_dll_directory(str(_directory)))
    os.environ["PATH"] = os.pathsep.join(
        [str(path) for path in _dll_directories if path.is_dir()]
        + ([_existing_path] if _existing_path else [])
    )
    # SetDllDirectory place le dossier Qt avant System32 dans la recherche
    # Windows, ce que PATH et AddDllDirectory seuls ne garantissent pas.
    _qt_dll_directory = _bundle_root / "PySide6"
    if _qt_dll_directory.is_dir():
        _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        _kernel32.SetDllDirectoryW.argtypes = [ctypes.c_wchar_p]
        _kernel32.SetDllDirectoryW.restype = ctypes.c_int
        if not _kernel32.SetDllDirectoryW(str(_qt_dll_directory)):
            raise ctypes.WinError(ctypes.get_last_error())

from app.desktop import main

if __name__ == "__main__":
    raise SystemExit(main())
