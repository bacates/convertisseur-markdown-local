"""Application de bureau native pour MarkItDown (sans navigateur ni serveur web)."""

from __future__ import annotations

import mimetypes
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QSettings, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QGuiApplication, QPalette
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QTableWidget, QTableWidgetItem, QTextBrowser, QVBoxLayout, QWidget,
    QHeaderView, QAbstractItemView,
)

from app.conversion import (
    CONVERSIONS_DIR, ConversionError, MIME_BY_EXTENSION, SUPPORTED_EXTENSIONS,
    convert_path, convert_youtube_url, create_batch_dir, make_zip,
    save_conversion, validate_upload,
)


@dataclass
class Job:
    """Élément de la file d'attente : fichier local ou lien YouTube."""

    kind: str
    value: str
    name: str
    size: int = 0
    status: str = "pending"
    markdown: str = ""
    conversion_id: str = ""
    output_path: str = ""
    error: str = ""


class DropZone(QFrame):
    """Zone native qui accepte les fichiers déposés depuis l'explorateur."""

    files_dropped = Signal(list)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("DropZone")
        self.setAcceptDrops(True)
        self.setMinimumHeight(155)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(7)
        icon = QLabel("⇧")
        icon.setObjectName("dropIcon")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title = QLabel("Déposez vos fichiers ici")
        title.setObjectName("dropTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle = QLabel("ou sélectionnez-les avec le bouton ci-dessous · 100 Mo maximum par fichier")
        subtitle.setObjectName("muted")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon)
        layout.addWidget(title)
        layout.addWidget(subtitle)

    def dragEnterEvent(self, event) -> None:  # noqa: N802 - nom Qt
        if event.mimeData().hasUrls() and any(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:  # noqa: N802 - nom Qt
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        self.files_dropped.emit(paths)
        event.acceptProposedAction()


class ConversionWorker(QThread):
    """Traite la file hors du fil graphique, un élément après l'autre."""

    item_started = Signal(int)
    item_progress = Signal(int, int)
    item_finished = Signal(int, dict)
    all_finished = Signal(str, str)

    def __init__(self, jobs: list[tuple[int, Job]], batch_id: str, batch_dir: Path):
        super().__init__()
        self.jobs = jobs
        self.batch_id = batch_id
        self.batch_dir = batch_dir

    def run(self) -> None:
        succeeded = False
        for row, job in self.jobs:
            self.item_started.emit(row)
            try:
                if job.kind == "youtube":
                    filename, markdown = convert_youtube_url(job.value)
                    size = len(markdown.encode("utf-8"))
                else:
                    source = Path(job.value)
                    size = source.stat().st_size
                    guessed_mime = mimetypes.guess_type(source.name)[0]
                    extension = source.suffix.lower()
                    accepted_mimes = MIME_BY_EXTENSION.get(extension, set())
                    mime = guessed_mime if guessed_mime in accepted_mimes else next(iter(accepted_mimes), "")
                    validate_upload(source.name, mime, size)
                    filename, markdown = convert_path(source.name, source, mime, size)

                conversion_id, output = save_conversion(self.batch_dir, filename, markdown)
                succeeded = True
                result = {
                    "status": "success", "filename": filename, "size": size,
                    "conversion_id": conversion_id, "output_path": str(output),
                    "markdown": markdown,
                }
            except ConversionError as exc:
                result = {"status": "error", "error": str(exc)}
            except Exception as exc:
                result = {"status": "error", "error": f"Conversion impossible ({exc.__class__.__name__})."}
            self.item_finished.emit(row, result)

        zip_path = ""
        if succeeded:
            archive = self.batch_dir / "conversions.zip"
            make_zip(self.batch_dir, archive)
            zip_path = str(archive)
        self.all_finished.emit(self.batch_id, zip_path)


class MainWindow(QMainWindow):
    """Fenêtre native du convertisseur local."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Convertisseur local en Markdown")
        self.resize(1120, 900)
        self.setMinimumSize(800, 660)
        self.settings = QSettings("MarkItDownLocal", "Convertisseur")
        self.jobs: list[Job] = []
        self.row_widgets: dict[int, dict[str, QWidget]] = {}
        self.batch_id: str | None = None
        self.batch_dir: Path | None = None
        self.zip_path = ""
        self.worker: ConversionWorker | None = None

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(30, 20, 30, 22)
        root.setSpacing(15)

        header = QHBoxLayout()
        brand = QLabel("M↓  MarkItDown local")
        brand.setObjectName("brand")
        self.theme_toggle = QCheckBox("Mode sombre")
        self.theme_toggle.setChecked(self._initial_dark_mode())
        self.theme_toggle.toggled.connect(self._apply_theme)
        header.addWidget(brand)
        header.addStretch(1)
        header.addWidget(self.theme_toggle)
        root.addLayout(header)

        intro = QVBoxLayout()
        intro.setSpacing(3)
        title = QLabel("Convertisseur local en Markdown")
        title.setObjectName("title")
        subtitle = QLabel("Transformez vos documents sans navigateur ni service distant.")
        subtitle.setObjectName("muted")
        intro.addWidget(title)
        intro.addWidget(subtitle)
        root.addLayout(intro)

        self.drop_zone = DropZone()
        self.drop_zone.files_dropped.connect(self.add_files)
        root.addWidget(self.drop_zone)

        controls = QHBoxLayout()
        self.choose_button = QPushButton("Choisir des fichiers")
        self.choose_button.clicked.connect(self.choose_files)
        self.clear_button = QPushButton("Effacer la liste")
        self.clear_button.clicked.connect(self.clear_list)
        controls.addWidget(self.choose_button)
        controls.addWidget(self.clear_button)
        controls.addStretch(1)
        root.addLayout(controls)

        youtube = QFrame()
        youtube.setObjectName("Card")
        youtube_layout = QHBoxLayout(youtube)
        youtube_layout.setContentsMargins(15, 10, 15, 10)
        youtube_info = QVBoxLayout()
        youtube_title = QLabel("Transcription YouTube")
        youtube_title.setObjectName("sectionTitle")
        youtube_note = QLabel("Récupération de la transcription publique via Internet à votre demande.")
        youtube_note.setObjectName("muted")
        youtube_info.addWidget(youtube_title)
        youtube_info.addWidget(youtube_note)
        self.youtube_url = QLineEdit()
        self.youtube_url.setObjectName("youtubeInput")
        self.youtube_url.setPlaceholderText("https://www.youtube.com/watch?v=…")
        self.youtube_button = QPushButton("Convertir l’URL")
        self.youtube_button.clicked.connect(self.add_youtube)
        youtube_layout.addLayout(youtube_info, 1)
        youtube_layout.addWidget(self.youtube_url, 2)
        youtube_layout.addWidget(self.youtube_button)
        root.addWidget(youtube)

        formats = QLabel("Formats : " + " · ".join(sorted(SUPPORTED_EXTENSIONS)))
        formats.setObjectName("muted")
        formats.setWordWrap(True)
        root.addWidget(formats)

        list_title = QHBoxLayout()
        title_files = QLabel("Fichiers ajoutés")
        title_files.setObjectName("sectionTitle")
        self.count_label = QLabel("Aucun fichier")
        self.count_label.setObjectName("muted")
        list_title.addWidget(title_files)
        list_title.addWidget(self.count_label)
        list_title.addStretch(1)
        root.addLayout(list_title)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Fichier", "Type / taille", "État", "Actions"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(False)
        self.table.setShowGrid(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        root.addWidget(self.table, 3)

        actions = QHBoxLayout()
        self.convert_button = QPushButton("Convertir la file")
        self.convert_button.setObjectName("PrimaryButton")
        self.convert_button.clicked.connect(self.start_conversions)
        self.zip_button = QPushButton("Tout télécharger en ZIP")
        self.zip_button.setEnabled(False)
        self.zip_button.clicked.connect(self.download_zip)
        actions.addWidget(self.convert_button)
        actions.addWidget(self.zip_button)
        actions.addStretch(1)
        root.addLayout(actions)

        preview_header = QHBoxLayout()
        preview_title = QLabel("Aperçu Markdown")
        preview_title.setObjectName("sectionTitle")
        self.copy_preview_button = QPushButton("Copier l’aperçu")
        self.copy_preview_button.clicked.connect(self.copy_preview)
        preview_header.addWidget(preview_title)
        preview_header.addStretch(1)
        preview_header.addWidget(self.copy_preview_button)
        root.addLayout(preview_header)

        self.preview = QTextBrowser()
        self.preview.setOpenExternalLinks(False)
        self.preview.setMarkdown("*Choisissez « Aperçu » sur une conversion réussie.*")
        self.preview.setMinimumHeight(150)
        root.addWidget(self.preview, 2)

        self.errors = QPlainTextEdit()
        self.errors.setReadOnly(True)
        self.errors.setMaximumHeight(75)
        self.errors.setPlaceholderText("Les erreurs de conversion apparaîtront ici.")
        root.addWidget(self.errors)

        footer = QLabel("Les fichiers locaux restent sur cet appareil. Seule la conversion YouTube utilise Internet.")
        footer.setObjectName("muted")
        root.addWidget(footer)
        self.setCentralWidget(central)
        self._apply_theme(self.theme_toggle.isChecked())

    def _initial_dark_mode(self) -> bool:
        saved = self.settings.value("dark_mode", None)
        if saved is not None:
            return str(saved).lower() in {"true", "1"}
        return QApplication.palette().color(QPalette.ColorRole.Window).lightness() < 128

    def _apply_theme(self, dark: bool) -> None:
        self.settings.setValue("dark_mode", dark)
        if dark:
            bg, card, text, muted, line, accent = "#11141d", "#1b1f2b", "#eef0f8", "#9ca5ba", "#303545", "#8e82ff"
        else:
            bg, card, text, muted, line, accent = "#f4f6fa", "#ffffff", "#1b1e2b", "#757d91", "#e3e7ef", "#6557e8"
        self.setStyleSheet(f"""
            QWidget {{ color: {text}; background: {bg}; font-family: 'Segoe UI'; font-size: 13px; }}
            QMainWindow {{ background: {bg}; }}
            QLabel#brand {{ font-size: 14px; font-weight: 700; }}
            QLabel#title {{ font-size: 27px; font-weight: 750; }}
            QLabel#sectionTitle {{ font-size: 15px; font-weight: 700; }}
            QLabel#muted {{ color: {muted}; font-size: 11px; }}
            QLabel#dropIcon {{ color: {accent}; font-size: 26px; font-weight: 700; }}
            QLabel#dropTitle {{ font-size: 16px; font-weight: 650; }}
            QFrame#Card {{ background: {card}; border: 1px solid {line}; border-radius: 14px; }}
            QFrame#DropZone {{ background: {card}; border: 2px dashed {accent}; border-radius: 17px; }}
            QPushButton {{ background: {card}; border: 1px solid {line}; border-radius: 9px; padding: 8px 13px; font-weight: 600; }}
            QPushButton:hover {{ border-color: {accent}; color: {accent}; }}
            QPushButton:disabled {{ color: {muted}; }}
            QPushButton#PrimaryButton {{ background: {accent}; border: 1px solid {accent}; color: white; padding-left: 20px; padding-right: 20px; }}
            QTableWidget, QTextBrowser, QPlainTextEdit {{ background: {card}; border: 1px solid {line}; border-radius: 10px; selection-background-color: {accent}; }}
            QHeaderView::section {{ background: {bg}; border: none; border-bottom: 1px solid {line}; padding: 8px; color: {muted}; font-size: 11px; font-weight: 650; }}
            QTableWidget::item {{ padding: 6px; border-bottom: 1px solid {line}; }}
            QProgressBar {{ background: {bg}; border: 1px solid {line}; border-radius: 5px; height: 16px; text-align: center; font-size: 10px; }}
            QProgressBar::chunk {{ background: {accent}; border-radius: 4px; }}
            QCheckBox {{ color: {muted}; spacing: 7px; }}
        """)

    def choose_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Choisir des fichiers", "", "Tous les fichiers (*)")
        self.add_files(paths)

    def add_files(self, paths: list[str]) -> None:
        known = {job.value for job in self.jobs if job.kind == "file"}
        for path in paths:
            source = Path(path)
            if not source.is_file() or str(source) in known:
                continue
            job = Job("file", str(source), source.name, source.stat().st_size)
            self._add_job(job)
            known.add(str(source))
        self._update_count()

    def add_youtube(self) -> None:
        url = self.youtube_url.text().strip()
        if not url:
            QMessageBox.information(self, "URL requise", "Collez d’abord une URL YouTube.")
            return
        job = Job("youtube", url, f"YouTube · {url}")
        self._add_job(job)
        self.youtube_url.clear()
        self._update_count()
        self.start_conversions()

    def _add_job(self, job: Job) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.jobs.append(job)
        name = QTableWidgetItem(job.name)
        name.setToolTip(job.value)
        self.table.setItem(row, 0, name)
        kind = "URL YouTube" if job.kind == "youtube" else (Path(job.name).suffix.upper() or "Fichier")
        size = f"{job.size / (1024 * 1024):.1f} Mo" if job.size else ""
        self.table.setItem(row, 1, QTableWidgetItem(f"{kind}  ·  {size}".strip(" ·")))

        status_widget = QWidget()
        status_layout = QVBoxLayout(status_widget)
        status_layout.setContentsMargins(0, 3, 0, 3)
        status_label = QLabel("En attente")
        progress = QProgressBar()
        progress.setRange(0, 100)
        progress.setValue(0)
        progress.setTextVisible(False)
        progress.setMaximumHeight(7)
        status_layout.addWidget(status_label)
        status_layout.addWidget(progress)
        self.table.setCellWidget(row, 2, status_widget)

        actions = QWidget()
        action_layout = QHBoxLayout(actions)
        action_layout.setContentsMargins(0, 0, 0, 0)
        preview_button = QPushButton("Aperçu")
        save_button = QPushButton("Télécharger")
        copy_button = QPushButton("Copier")
        preview_button.setEnabled(False)
        save_button.setEnabled(False)
        copy_button.setEnabled(False)
        preview_button.clicked.connect(lambda _=False, r=row: self.show_preview(r))
        save_button.clicked.connect(lambda _=False, r=row: self.save_markdown(r))
        copy_button.clicked.connect(lambda _=False, r=row: self.copy_markdown(r))
        for button in (preview_button, save_button, copy_button):
            action_layout.addWidget(button)
        self.row_widgets[row] = {
            "status": status_label, "progress": progress,
            "preview": preview_button, "save": save_button, "copy": copy_button,
        }
        self.table.setCellWidget(row, 3, actions)
        self.table.setRowHeight(row, 57)

    def _update_count(self) -> None:
        count = len(self.jobs)
        self.count_label.setText(f"{count} élément{'s' if count != 1 else ''}")
        self.clear_button.setEnabled(count > 0 and (self.worker is None or not self.worker.isRunning()))
        self.convert_button.setEnabled(any(job.status in {"pending", "error"} for job in self.jobs) and (self.worker is None or not self.worker.isRunning()))

    def clear_list(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            return
        self.jobs.clear()
        self.row_widgets.clear()
        self.table.setRowCount(0)
        self.errors.clear()
        self.preview.clear()
        self.batch_id = None
        self.batch_dir = None
        self.zip_path = ""
        self.zip_button.setEnabled(False)
        self._update_count()

    def start_conversions(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            return
        pending = [(row, job) for row, job in enumerate(self.jobs) if job.status in {"pending", "error"}]
        if not pending:
            return
        if self.batch_id is None:
            self.batch_id, self.batch_dir = create_batch_dir()
        assert self.batch_dir is not None
        self.errors.clear()
        self.worker = ConversionWorker(pending, self.batch_id, self.batch_dir)
        self.worker.item_started.connect(self._item_started)
        self.worker.item_progress.connect(self._item_progress)
        self.worker.item_finished.connect(self._item_finished)
        self.worker.all_finished.connect(self._all_finished)
        self.worker.finished.connect(self._worker_thread_finished)
        self.convert_button.setEnabled(False)
        self.choose_button.setEnabled(False)
        self.youtube_button.setEnabled(False)
        self.clear_button.setEnabled(False)
        self.worker.start()

    def _item_started(self, row: int) -> None:
        self.jobs[row].status = "running"
        self.row_widgets[row]["status"].setText("Conversion en cours…")
        progress = self.row_widgets[row]["progress"]
        progress.setRange(0, 0)
        progress.setTextVisible(False)

    def _item_progress(self, row: int, value: int) -> None:
        progress = self.row_widgets[row]["progress"]
        progress.setRange(0, 100)
        progress.setValue(value)

    def _item_finished(self, row: int, result: dict) -> None:
        job = self.jobs[row]
        job.status = result["status"]
        if job.status == "success":
            job.name = result["filename"]
            job.size = result["size"]
            job.conversion_id = result["conversion_id"]
            job.output_path = result["output_path"]
            job.markdown = result["markdown"]
            self.table.item(row, 0).setText(job.name)
            details = "URL YouTube" if job.kind == "youtube" else (Path(job.name).suffix.upper() or "Fichier")
            self.table.item(row, 1).setText(f"{details}  ·  {job.size / (1024 * 1024):.1f} Mo")
            self.row_widgets[row]["status"].setText("Conversion réussie")
            self.row_widgets[row]["progress"].setRange(0, 100)
            self.row_widgets[row]["progress"].setValue(100)
            for key in ("preview", "save", "copy"):
                self.row_widgets[row][key].setEnabled(True)
        else:
            job.error = result["error"]
            job.status = "error"
            self.row_widgets[row]["status"].setText("Erreur")
            self.row_widgets[row]["progress"].setRange(0, 100)
            self.row_widgets[row]["progress"].setValue(0)
            self.errors.appendPlainText(f"{job.name} : {job.error}")

    def _all_finished(self, batch_id: str, zip_path: str) -> None:
        self.batch_id = batch_id
        self.zip_path = zip_path or self.zip_path
        self.zip_button.setEnabled(bool(self.zip_path))
        self.choose_button.setEnabled(True)
        self.youtube_button.setEnabled(True)
        self._update_count()
        if self.zip_path:
            self.statusBar().showMessage(f"Conversions enregistrées dans {self.batch_dir}", 9000)

    def _worker_thread_finished(self) -> None:
        # Détruire le QThread seulement après son arrêt effectif.
        if self.worker is not None:
            self.worker.deleteLater()
            self.worker = None
        self._update_count()

    def show_preview(self, row: int) -> None:
        job = self.jobs[row]
        self.preview.setMarkdown(job.markdown)
        self.preview.setFocus()

    def copy_markdown(self, row: int) -> None:
        QApplication.clipboard().setText(self.jobs[row].markdown)
        self.statusBar().showMessage("Markdown copié dans le presse-papiers.", 3000)

    def copy_preview(self) -> None:
        text = self.preview.toMarkdown()
        if text.strip():
            QApplication.clipboard().setText(text)
            self.statusBar().showMessage("Aperçu copié dans le presse-papiers.", 3000)

    def save_markdown(self, row: int) -> None:
        job = self.jobs[row]
        target, _ = QFileDialog.getSaveFileName(self, "Télécharger le Markdown", f"{Path(job.name).stem}.md", "Markdown (*.md)")
        if target:
            Path(target).write_text(job.markdown, encoding="utf-8")
            self.statusBar().showMessage(f"Fichier enregistré : {target}", 5000)

    def download_zip(self) -> None:
        if not self.zip_path:
            return
        target, _ = QFileDialog.getSaveFileName(self, "Télécharger l’archive ZIP", "conversions.zip", "Archive ZIP (*.zip)")
        if target:
            shutil.copy2(self.zip_path, target)
            self.statusBar().showMessage(f"Archive enregistrée : {target}", 5000)

    def closeEvent(self, event) -> None:  # noqa: N802 - nom Qt
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.information(self, "Conversion en cours", "Attendez la fin de la conversion avant de fermer l’application.")
            event.ignore()
            return
        event.accept()


def main() -> int:
    """Point d'entrée de l'application native."""
    QApplication.setOrganizationName("MarkItDownLocal")
    QApplication.setApplicationName("Convertisseur en Markdown")
    application = QApplication(sys.argv)
    application.setStyle("Fusion")
    window = MainWindow()
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
