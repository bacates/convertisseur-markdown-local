@echo off
setlocal
cd /d "%~dp0"
title Convertisseur local en Markdown
if not exist "%~dp0requirements.txt" goto missing_requirements

set "PYTHON_LAUNCHER="
py -3.14 --version >nul 2>&1 && set "PYTHON_LAUNCHER=py -3.14"
if not defined PYTHON_LAUNCHER py -3.13 --version >nul 2>&1 && set "PYTHON_LAUNCHER=py -3.13"
if not defined PYTHON_LAUNCHER py -3.12 --version >nul 2>&1 && set "PYTHON_LAUNCHER=py -3.12"
if not defined PYTHON_LAUNCHER py -3.11 --version >nul 2>&1 && set "PYTHON_LAUNCHER=py -3.11"

if not defined PYTHON_LAUNCHER goto no_python

if not exist ".venv-markitdown\Scripts\python.exe" (
    echo Preparation de l'environnement Python...
    %PYTHON_LAUNCHER% -m venv .venv-markitdown
    if errorlevel 1 goto setup_error
)

if not exist ".venv-markitdown\deps-installed-youtube" (
    echo Installation des composants necessaires. Cela peut prendre quelques minutes...
    ".venv-markitdown\Scripts\python.exe" -m pip install --upgrade pip
    if errorlevel 1 goto setup_error
    ".venv-markitdown\Scripts\python.exe" -m pip install -r "%~dp0requirements.txt"
    if errorlevel 1 goto setup_error
    type nul > ".venv-markitdown\deps-installed-youtube"
)

echo Demarrage de l'application...
".venv-markitdown\Scripts\python.exe" run.py
if errorlevel 1 goto start_error
goto end

:no_python
echo Python 3.11, 3.12, 3.13 ou 3.14 est requis.
echo Installez Python 3.14 depuis https://www.python.org/downloads/windows/ puis relancez ce fichier.
goto pause_end

:missing_requirements
echo Le fichier requirements.txt est introuvable a cote de demarrer.bat.
echo Gardez tous les fichiers du projet ensemble dans C:\Users\bacat\Markitdown.
goto pause_end

:setup_error
echo La preparation a echoue. Verifiez votre connexion Internet et relancez ce fichier.
goto pause_end

:start_error
echo L'application s'est arretee avec une erreur. Lisez le message ci-dessus.

:pause_end
pause

:end
endlocal
