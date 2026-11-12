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

echo Construction de l'application native. Cette operation peut prendre quelques minutes...
".venv-markitdown\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onedir --windowed --name ConvertisseurMarkdownDesktop --hidden-import app.desktop --collect-all markitdown --collect-all magika run_desktop.py
if errorlevel 1 goto build_error

echo.
echo Creation terminee :
echo %~dp0dist\ConvertisseurMarkdownDesktop\ConvertisseurMarkdownDesktop.exe
echo Copiez tout le dossier dist\ConvertisseurMarkdownDesktop pour deplacer l'application.
pause
goto end

:build_error
echo.
echo La creation a echoue. Le detail de l'erreur est affiche ci-dessus.
pause

:end
endlocal
