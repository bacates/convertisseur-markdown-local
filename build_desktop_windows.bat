@echo off
setlocal
cd /d "%~dp0"
title Construction de l'application native

if not exist ".venv-markitdown\Scripts\python.exe" (
    echo Environnement Python introuvable. Lancez d'abord demarrer.bat.
    goto build_error
)

echo Installation/verifications des dependances de bureau...
".venv-markitdown\Scripts\python.exe" -m pip install -r "%~dp0requirements-desktop.txt"
if errorlevel 1 goto build_error

if not exist "%~dp0dist\ConvertisseurMarkdownPortable" mkdir "%~dp0dist\ConvertisseurMarkdownPortable"

echo Construction du coeur de l'application sans Qt. Cette operation peut prendre quelques minutes...
".venv-markitdown\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onedir --console --name ConvertisseurMarkdownCore --distpath "%~dp0dist\ConvertisseurMarkdownPortable" --workpath "%~dp0build\PortableCore" --specpath "%~dp0build\PortableCore" --hidden-import app.desktop --exclude-module PySide6 --exclude-module shiboken6 --exclude-module PySide2 --exclude-module PyQt5 --exclude-module PyQt6 --collect-all markitdown --collect-all magika "%~dp0run_desktop.py"
if errorlevel 1 goto build_error

echo Creation du lanceur silencieux...
".venv-markitdown\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --windowed --name ConvertisseurMarkdownDesktop --distpath "%~dp0dist\ConvertisseurMarkdownPortable" --workpath "%~dp0build\PortableLauncher" --specpath "%~dp0build\PortableLauncher" "%~dp0launch_portable.py"
if errorlevel 1 goto build_error

echo.
echo Creation terminee :
echo %~dp0dist\ConvertisseurMarkdownPortable\ConvertisseurMarkdownDesktop.exe
echo Copiez tout le dossier dist\ConvertisseurMarkdownPortable pour deplacer l'application.
pause
goto end

:build_error
echo.
echo La creation a echoue. Le detail de l'erreur est affiche ci-dessus.
pause

:end
endlocal
