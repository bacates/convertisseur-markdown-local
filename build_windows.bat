@echo off
setlocal
cd /d "%~dp0"
title Creation de l'application Windows

if not exist ".venv-markitdown\Scripts\python.exe" (
    echo Environnement Python introuvable. Lancez d'abord demarrer.bat.
    goto build_error
)

echo Verification et installation de PyInstaller...
".venv-markitdown\Scripts\python.exe" -m pip install -r "%~dp0requirements-build.txt"
if errorlevel 1 goto build_error

echo Construction de l'application. Cette operation peut prendre plusieurs minutes...
".venv-markitdown\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onedir --console --name ConvertisseurMarkdown --hidden-import app.main --collect-all markitdown --collect-all magika --collect-all uvicorn --collect-all python_multipart --add-data "app\templates;app\templates" --add-data "app\static;app\static" run.py
if errorlevel 1 goto build_error

echo.
echo Creation terminee :
echo %~dp0dist\ConvertisseurMarkdown\ConvertisseurMarkdown.exe
echo Copiez tout le dossier dist\ConvertisseurMarkdown pour deplacer l'application.
pause
goto end

:build_error
echo.
echo La creation a echoue. Le detail de l'erreur est affiche ci-dessus.
pause

:end
endlocal
