# Convertisseur local en Markdown

Application web locale en français pour convertir des fichiers avec [Microsoft MarkItDown](https://github.com/microsoft/markitdown). Les fichiers sont traités sur le PC et enregistrés dans le dossier `conversions/`. Le serveur écoute uniquement sur `127.0.0.1` ; aucun compte ni base de données n'est utilisé.

## Installation

Python 3.11 à 3.14 est requis. Python 3.13 ou 3.14 est recommandé sous Windows. La version de MarkItDown utilisée ici (0.1.5 ou supérieure) évite l'ancienne contrainte Windows d'ONNX Runtime.

Si Python 3.14 n'est pas encore installé sous Windows, installez-le avec WinGet, puis fermez et rouvrez PowerShell :

```powershell
winget install Python.Python.3.14
py --list
```

```bash
python -m venv .venv
```

Activez l'environnement selon votre système :

```powershell
# Windows
.venv\Scripts\activate
```

```bash
# Linux / macOS
source .venv/bin/activate
```

Installez les dépendances :

```bash
pip install -r requirements.txt
```

## Lancement

Sous Windows, vous pouvez simplement double-cliquer sur `demarrer.bat`. Au premier lancement, le script crée l'environnement virtuel et installe les dépendances (une connexion Internet est nécessaire pour cette installation initiale). Ensuite, il démarre le serveur et ouvre automatiquement le navigateur. Gardez la fenêtre noire ouverte pendant l'utilisation ; fermez-la ou faites `Ctrl+C` dans cette fenêtre pour arrêter l'application.

Pour lancer manuellement ou sous Linux/macOS :

```bash
python run.py
```

Ouvrez ensuite <http://127.0.0.1:8000> dans votre navigateur. Arrêtez le serveur avec `Ctrl+C` dans la fenêtre du terminal.

## Créer l'exécutable Windows

Après avoir lancé une première fois `demarrer.bat` et installé les dépendances, double-cliquez sur `build_windows.bat`. Le script crée `dist/ConvertisseurMarkdown/ConvertisseurMarkdown.exe` ainsi que ses fichiers nécessaires. Pour démarrer l'application, exécutez ce `.exe` ; le navigateur s'ouvre automatiquement. Gardez le dossier `ConvertisseurMarkdown` entier lorsque vous copiez ou distribuez l'application. Les sorties sont enregistrées dans `conversions/` à côté de l'exécutable. Le premier build télécharge PyInstaller si nécessaire.

## Utilisation

Déposez un ou plusieurs fichiers dans la zone d'import ou cliquez sur **Choisir des fichiers**, puis cliquez sur **Convertir**. Chaque fichier passe en conversion successivement ; l'état de chaque élément, son aperçu, les commandes de copie et le téléchargement `.md` apparaissent dans la liste. Le bouton ZIP rassemble les conversions réussies du lot. Le panneau inférieur affiche les erreurs rencontrées.

Un PDF, DOCX ou EPUB peut être importé comme n'importe quel autre fichier : sélectionnez-le, puis lancez **Convertir**. Pour une image JPG, PNG, WEBP, GIF, BMP ou TIFF, procédez de la même façon. La qualité du résultat dépend du contenu et des capacités des dépendances installées ; une image contenant du texte peut ne produire que ses métadonnées si aucun OCR local compatible n'est disponible.

Les sorties sont conservées dans `conversions/AAAA-MM-JJ_HH-MM-SS_uuid/`. Chaque Markdown y est accompagné de l'archive ZIP du lot. Les fichiers temporaires sont supprimés après chaque tentative. La limite est de 100 Mo par fichier.

## Formats et confidentialité

La page récupère la liste des extensions exposées par l'application via `GET /api/supported-extensions`. La liste couvre les formats courants reconnus par MarkItDown : PDF, Word, Excel, PowerPoint, CSV, JSON, XML, HTML, texte, Markdown, EPUB, images et quelques formats conteneurs/courriel. Les extensions de formats optionnels peuvent être présentes même si la dépendance propre au format n'est pas disponible ; l'erreur correspondante sera montrée sans interrompre les autres conversions.

La transcription des fichiers audio est désactivée : le convertisseur audio de MarkItDown utilise un service de reconnaissance vocale en ligne. La conversion YouTube est activée séparément et contacte YouTube uniquement lorsque vous soumettez une URL, pour récupérer sa transcription publique ; la vidéo n'est pas téléchargée. Les fichiers sélectionnés dans la zone d'import restent convertis localement. L'application n'embarque aucune police distante et n'effectue aucun appel réseau externe en dehors de la conversion YouTube demandée.

Les documents protégés par mot de passe, corrompus, illisibles ou très complexes peuvent échouer ou perdre une partie de leur mise en page. Les PDF scannés et images avec texte nécessitent un moteur OCR local compatible ; sans celui-ci, MarkItDown ne peut généralement pas reconstituer le texte de l'image.

## Tests unitaires

```bash
pytest
```

## API locale

- `GET /` : interface
- `POST /api/convert` : conversion séquentielle d'un ou plusieurs fichiers (`multipart/form-data`, champ `files`)
- `GET /api/download/{conversion_id}` : téléchargement Markdown
- `GET /api/download-zip/{conversion_id}` : archive ZIP du lot
- `GET /api/preview/{conversion_id}` : contenu Markdown
- `GET /api/supported-extensions` : extensions et limites déclarées
