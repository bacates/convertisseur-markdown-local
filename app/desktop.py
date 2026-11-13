"""Interface de bureau légère basée sur Tkinter, sans dépendance Qt."""

from __future__ import annotations

import ctypes
import mimetypes
import os
import queue
import shutil
import sys
import threading
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from app.conversion import (
    CONVERSIONS_DIR,
    ConversionError,
    MIME_BY_EXTENSION,
    SUPPORTED_EXTENSIONS,
    convert_path,
    convert_youtube_url,
    create_batch_dir,
    make_zip,
    save_conversion,
    validate_upload,
)


@dataclass
class Job:
    """Élément de la file d'attente : fichier local ou URL YouTube."""

    kind: str
    value: str
    name: str
    size: int = 0
    status: str = "pending"
    markdown: str = ""
    error: str = ""
    widgets: dict[str, object] | None = None


class DesktopApp:
    """Fenêtre native utilisant les widgets de Tk intégrés à Python."""

    WM_DROPFILES = 0x0233
    GWLP_WNDPROC = -4

    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Convertisseur local en Markdown")
        # Dimensionne la fenêtre selon l'écran et garde une marge pour la barre des tâches.
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        width = min(1080, max(760, screen_width - 64))
        height = min(760, max(520, screen_height - 80))
        x = max(0, (screen_width - width) // 2)
        y = max(0, (screen_height - height) // 2)
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        self.root.minsize(min(800, width), min(580, height))

        self.jobs: list[Job] = []
        self.events: queue.Queue[tuple] = queue.Queue()
        self.busy = False
        self.batch_dir: Path | None = None
        self.zip_path = ""
        self.dark_mode = self._system_prefers_dark()
        self.preview_job: int | None = None
        self._drop_callback = None
        self._old_wndproc = None
        self._window_handle = None

        self.style = ttk.Style(self.root)
        # Le thème clam permet de colorer les widgets de façon cohérente sur Windows.
        if "clam" in self.style.theme_names():
            self.style.theme_use("clam")
        self._build_ui()
        self._apply_theme()
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self.root.after(150, self._poll_worker)
        self.root.after(300, self._enable_file_drop)

    @staticmethod
    def _system_prefers_dark() -> bool:
        """Lit le réglage de couleurs Windows, avec un mode clair par défaut."""
        if os.name != "nt":
            return False
        try:
            import winreg

            key_path = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                return winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0
        except (OSError, ImportError):
            return False

    def _build_ui(self) -> None:
        """Construit une page unique défilante pour rester utilisable sur petit écran."""
        shell = ttk.Frame(self.root)
        shell.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(shell, highlightthickness=0, borderwidth=0)
        scrollbar = ttk.Scrollbar(shell, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.content = ttk.Frame(self.canvas, padding=(24, 18, 24, 20))
        self.content_window = self.canvas.create_window((0, 0), window=self.content, anchor="nw")
        self.content.bind("<Configure>", self._update_scroll_region)
        self.canvas.bind("<Configure>", self._resize_content)
        self.canvas.bind_all("<MouseWheel>", self._mouse_wheel)

        header = ttk.Frame(self.content)
        header.pack(fill="x", pady=(0, 12))
        self.brand = ttk.Label(header, text="M↓  MARKITDOWN LOCAL", style="Brand.TLabel")
        self.brand.pack(side="left")
        self.theme_button = ttk.Button(header, command=self._toggle_theme)
        self.theme_button.pack(side="right")

        ttk.Label(self.content, text="Convertisseur local en Markdown", style="Title.TLabel").pack(
            anchor="w"
        )
        ttk.Label(
            self.content,
            text="Convertissez vos documents sur cet appareil, sans navigateur ni service distant.",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(2, 15))

        self.drop_border = tk.Frame(self.content, height=112, padx=1, pady=1)
        self.drop_border.pack(fill="x", pady=(0, 10))
        self.drop_inner = tk.Frame(self.drop_border, height=110)
        self.drop_inner.pack(fill="both", expand=True)
        self.drop_inner.pack_propagate(False)
        self.drop_title = tk.Label(
            self.drop_inner,
            text="⇧  Glissez vos fichiers ici ou cliquez sur « Choisir des fichiers »",
            font=("Segoe UI", 12, "bold"),
        )
        self.drop_title.pack(expand=True, pady=(12, 0))
        self.drop_note = tk.Label(
            self.drop_inner,
            text="Traitement local · 100 Mo maximum par fichier · Déposez plusieurs fichiers à la fois",
            font=("Segoe UI", 9),
        )
        self.drop_note.pack(pady=(0, 16))

        file_controls = ttk.Frame(self.content)
        file_controls.pack(fill="x", pady=(0, 13))
        self.choose_button = ttk.Button(
            file_controls, text="Choisir des fichiers", style="Accent.TButton", command=self._choose_files
        )
        self.choose_button.pack(side="left")
        self.clear_button = ttk.Button(file_controls, text="Effacer la liste", command=self._clear_list)
        self.clear_button.pack(side="left", padx=(8, 0))

        youtube = ttk.Frame(self.content, style="Card.TFrame", padding=14)
        youtube.pack(fill="x", pady=(0, 12))
        youtube.columnconfigure(1, weight=1)
        ttk.Label(youtube, text="Transcription YouTube", style="Section.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 12)
        )
        self.youtube_url = ttk.Entry(youtube)
        self.youtube_url.insert(0, "https://www.youtube.com/watch?v=…")
        self.youtube_url.grid(row=0, column=1, sticky="ew", padx=(0, 10))
        self.youtube_button = ttk.Button(youtube, text="Convertir l’URL", command=self._add_youtube)
        self.youtube_button.grid(row=0, column=2, sticky="e")
        ttk.Label(
            youtube,
            text="La transcription YouTube nécessite Internet et n’est utilisée que pour cette URL.",
            style="Muted.TLabel",
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(8, 0))

        extensions = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        ttk.Label(
            self.content,
            text=f"Extensions acceptées par cette installation de MarkItDown : {extensions}",
            style="Muted.TLabel",
            wraplength=1030,
            justify="left",
        ).pack(fill="x", pady=(0, 14))

        list_header = ttk.Frame(self.content)
        list_header.pack(fill="x", pady=(0, 7))
        ttk.Label(list_header, text="Fichiers ajoutés", style="Section.TLabel").pack(side="left")
        self.count_label = ttk.Label(list_header, text="Aucun fichier", style="Muted.TLabel")
        self.count_label.pack(side="right")

        self.rows_frame = ttk.Frame(self.content)
        self.rows_frame.pack(fill="x", pady=(0, 10))
        self.empty_label = ttk.Label(
            self.rows_frame, text="Aucun fichier pour le moment.", style="Muted.TLabel", anchor="center"
        )
        self.empty_label.pack(fill="x", pady=18)

        actions = ttk.Frame(self.content)
        actions.pack(fill="x", pady=(0, 14))
        self.convert_button = ttk.Button(
            actions, text="Convertir", style="Accent.TButton", command=self._start_conversions
        )
        self.convert_button.pack(side="left")
        self.zip_button = ttk.Button(
            actions, text="Tout télécharger en ZIP", command=self._download_zip, state="disabled"
        )
        self.zip_button.pack(side="left", padx=(8, 0))
        self.location_label = ttk.Label(actions, text="", style="Muted.TLabel")
        self.location_label.pack(side="right")

        preview_header = ttk.Frame(self.content)
        preview_header.pack(fill="x", pady=(0, 7))
        ttk.Label(preview_header, text="Aperçu Markdown", style="Section.TLabel").pack(side="left")
        self.copy_preview_button = ttk.Button(
            preview_header, text="Copier l’aperçu", command=self._copy_preview
        )
        self.copy_preview_button.pack(side="right")
        self.save_preview_button = ttk.Button(
            preview_header, text="Télécharger l’aperçu", command=self._save_preview
        )
        self.save_preview_button.pack(side="right", padx=(0, 8))

        preview_wrap = ttk.Frame(self.content, style="Card.TFrame", padding=1)
        preview_wrap.pack(fill="both", expand=True, pady=(0, 12))
        self.preview_text = tk.Text(
            preview_wrap,
            height=12,
            wrap="word",
            undo=False,
            borderwidth=0,
            padx=12,
            pady=10,
            font=("Consolas", 10),
        )
        preview_scroll = ttk.Scrollbar(preview_wrap, orient="vertical", command=self.preview_text.yview)
        self.preview_text.configure(yscrollcommand=preview_scroll.set)
        preview_scroll.pack(side="right", fill="y")
        self.preview_text.pack(side="left", fill="both", expand=True)
        self.preview_text.insert("1.0", "Choisissez « Aperçu » après une conversion réussie.")

        ttk.Label(self.content, text="Erreurs", style="Section.TLabel").pack(anchor="w", pady=(0, 6))
        error_wrap = ttk.Frame(self.content, style="Card.TFrame", padding=1)
        error_wrap.pack(fill="x", pady=(0, 8))
        self.error_text = tk.Text(
            error_wrap,
            height=4,
            wrap="word",
            borderwidth=0,
            padx=10,
            pady=8,
            font=("Segoe UI", 9),
            state="disabled",
        )
        self.error_text.pack(fill="both", expand=True)
        ttk.Label(
            self.content,
            text="Les fichiers convertis sont enregistrés dans le dossier conversions, à côté de l’application.",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(2, 0))

    def _palette(self) -> dict[str, str]:
        if self.dark_mode:
            return {
                "bg": "#11151c", "panel": "#1b222d", "panel_alt": "#202a38",
                "text": "#edf1f7", "muted": "#a3adbd", "accent": "#8377f5",
                "accent_hover": "#7164e6", "border": "#313b4a", "input": "#161c25",
                "error": "#ff9999", "success": "#6fd0a5",
            }
        return {
            "bg": "#f4f6fa", "panel": "#ffffff", "panel_alt": "#eef1f7",
            "text": "#202636", "muted": "#697386", "accent": "#6558e8",
            "accent_hover": "#5649d7", "border": "#dfe4ed", "input": "#ffffff",
            "error": "#b42318", "success": "#168354",
        }

    def _apply_theme(self) -> None:
        """Applique une palette claire ou sombre cohérente aux widgets."""
        colors = self._palette()
        self.root.configure(background=colors["bg"])
        self.canvas.configure(background=colors["bg"])
        self.style.configure(".", background=colors["bg"], foreground=colors["text"], font=("Segoe UI", 10))
        self.style.configure("TFrame", background=colors["bg"])
        self.style.configure("Card.TFrame", background=colors["panel"])
        self.style.configure("TLabel", background=colors["bg"], foreground=colors["text"])
        self.style.configure("Card.TLabel", background=colors["panel"], foreground=colors["text"])
        self.style.configure("Brand.TLabel", font=("Segoe UI", 10, "bold"), foreground=colors["accent"])
        self.style.configure("Title.TLabel", font=("Segoe UI", 25, "bold"), foreground=colors["text"])
        self.style.configure("Section.TLabel", font=("Segoe UI", 12, "bold"), foreground=colors["text"])
        self.style.configure("Muted.TLabel", foreground=colors["muted"], font=("Segoe UI", 9))
        self.style.configure(
            "TButton", background=colors["panel"], foreground=colors["text"],
            bordercolor=colors["border"], padding=(11, 8), focusthickness=1,
        )
        self.style.map(
            "TButton",
            background=[("disabled", colors["panel_alt"]), ("active", colors["panel_alt"])],
            foreground=[("disabled", colors["muted"])],
        )
        self.style.configure(
            "Accent.TButton", background=colors["accent"], foreground="#ffffff",
            bordercolor=colors["accent"], padding=(14, 8), font=("Segoe UI", 10, "bold"),
        )
        self.style.map(
            "Accent.TButton",
            background=[("disabled", colors["panel_alt"]), ("active", colors["accent_hover"])],
            foreground=[("disabled", colors["muted"])],
        )
        self.style.configure(
            "TEntry", fieldbackground=colors["input"], foreground=colors["text"],
            insertcolor=colors["text"], bordercolor=colors["border"], padding=8,
        )
        self.style.configure(
            "Horizontal.TProgressbar", troughcolor=colors["panel_alt"],
            background=colors["accent"], bordercolor=colors["panel_alt"], thickness=6,
        )
        self.style.configure("Vertical.TScrollbar", background=colors["panel_alt"], troughcolor=colors["bg"])
        self.drop_border.configure(background=colors["border"])
        self.drop_inner.configure(background=colors["panel"])
        self.drop_title.configure(background=colors["panel"], foreground=colors["text"])
        self.drop_note.configure(background=colors["panel"], foreground=colors["muted"])
        self.preview_text.configure(background=colors["panel"], foreground=colors["text"], insertbackground=colors["text"])
        self.error_text.configure(background=colors["panel"], foreground=colors["error"], insertbackground=colors["text"])
        self.theme_button.configure(text="☀ Mode clair" if self.dark_mode else "☾ Mode sombre")
        for job in self.jobs:
            self._paint_job(job)

    def _toggle_theme(self) -> None:
        self.dark_mode = not self.dark_mode
        self._apply_theme()

    def _update_scroll_region(self, _event=None) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _resize_content(self, event) -> None:
        self.canvas.itemconfigure(self.content_window, width=event.width)

    def _mouse_wheel(self, event) -> None:
        if self.root.winfo_exists():
            self.canvas.yview_scroll(int(-event.delta / 120), "units")

    def _enable_file_drop(self) -> None:
        """Active WM_DROPFILES sous Windows sans ajouter de bibliothèque native."""
        if os.name != "nt":
            return
        try:
            self.root.update_idletasks()
            hwnd = self.root.winfo_id()
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            shell32 = ctypes.WinDLL("shell32", use_last_error=True)
            lresult = ctypes.c_ssize_t
            hwnd_type = ctypes.c_void_p
            self._wndproc_type = ctypes.WINFUNCTYPE(
                lresult, hwnd_type, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t
            )
            user32.SetWindowLongPtrW.argtypes = [hwnd_type, ctypes.c_int, hwnd_type]
            user32.SetWindowLongPtrW.restype = hwnd_type
            user32.CallWindowProcW.argtypes = [hwnd_type, hwnd_type, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
            user32.CallWindowProcW.restype = lresult
            shell32.DragAcceptFiles.argtypes = [hwnd_type, ctypes.c_int]
            shell32.DragQueryFileW.argtypes = [hwnd_type, ctypes.c_uint, ctypes.c_wchar_p, ctypes.c_uint]
            shell32.DragQueryFileW.restype = ctypes.c_uint
            shell32.DragFinish.argtypes = [hwnd_type]

            def window_proc(window, message, wparam, lparam):
                if message == self.WM_DROPFILES:
                    hdrop = hwnd_type(wparam)
                    count = shell32.DragQueryFileW(hdrop, 0xFFFFFFFF, None, 0)
                    paths = []
                    for index in range(count):
                        length = shell32.DragQueryFileW(hdrop, index, None, 0)
                        buffer = ctypes.create_unicode_buffer(length + 1)
                        shell32.DragQueryFileW(hdrop, index, buffer, length + 1)
                        paths.append(buffer.value)
                    shell32.DragFinish(hdrop)
                    if paths:
                        self.root.after(0, lambda dropped=paths: self._add_files(dropped))
                    return 0
                return user32.CallWindowProcW(
                    self._old_wndproc, window, message, wparam, lparam
                )

            self._drop_callback = self._wndproc_type(window_proc)
            self._window_handle = hwnd_type(hwnd)
            shell32.DragAcceptFiles(self._window_handle, 1)
            self._old_wndproc = user32.SetWindowLongPtrW(
                self._window_handle, self.GWLP_WNDPROC, ctypes.cast(self._drop_callback, hwnd_type)
            )
            if not self._old_wndproc:
                raise ctypes.WinError(ctypes.get_last_error())
            self._user32 = user32
            self._shell32 = shell32
        except Exception:
            # Le bouton de sélection reste disponible même si Windows refuse le dépôt.
            self._drop_callback = None
            self._old_wndproc = None

    def _restore_file_drop(self) -> None:
        if self._old_wndproc and self._window_handle:
            try:
                self._shell32.DragAcceptFiles(self._window_handle, 0)
                self._user32.SetWindowLongPtrW(
                    self._window_handle, self.GWLP_WNDPROC, self._old_wndproc
                )
            except Exception:
                pass
            self._old_wndproc = None
            self._drop_callback = None

    def _choose_files(self) -> None:
        paths = filedialog.askopenfilenames(
            parent=self.root,
            title="Choisir des fichiers",
            filetypes=[("Tous les fichiers", "*.*")],
        )
        self._add_files(list(paths))

    def _add_files(self, paths: list[str]) -> None:
        if self.busy:
            return
        known = {job.value for job in self.jobs if job.kind == "file"}
        for value in paths:
            try:
                source = Path(value)
                if not source.is_file() or str(source) in known:
                    continue
                job = Job("file", str(source), source.name, source.stat().st_size)
                self._add_job(job)
                known.add(str(source))
            except OSError as exc:
                self._append_error(f"{Path(value).name} : fichier illisible ({exc.__class__.__name__}).")
        self._update_controls()

    def _add_youtube(self) -> None:
        url = self.youtube_url.get().strip()
        if not url or url == "https://www.youtube.com/watch?v=…":
            messagebox.showinfo("URL requise", "Collez d’abord une URL YouTube.", parent=self.root)
            return
        self._add_job(Job("youtube", url, f"YouTube · {url}"))
        self.youtube_url.delete(0, "end")
        self._update_controls()
        self._start_conversions()

    def _add_job(self, job: Job) -> None:
        self.empty_label.pack_forget()
        card = ttk.Frame(self.rows_frame, style="Card.TFrame", padding=(12, 10))
        card.pack(fill="x", pady=4)
        card.columnconfigure(0, weight=3)
        card.columnconfigure(1, weight=2)
        card.columnconfigure(2, weight=0)

        name = ttk.Label(card, text=job.name, style="Card.TLabel", font=("Segoe UI", 10, "bold"))
        name.grid(row=0, column=0, sticky="w")
        ext = "URL YouTube" if job.kind == "youtube" else (Path(job.name).suffix.upper() or "Fichier")
        size_text = self._format_size(job.size) if job.size else ""
        details = ttk.Label(card, text=f"{ext}  ·  {size_text}".strip(" ·"), style="Muted.TLabel")
        details.grid(row=1, column=0, sticky="w", pady=(3, 0))

        status = ttk.Label(card, text="En attente", style="Card.TLabel")
        status.grid(row=0, column=1, sticky="w", padx=(14, 4))
        progress = ttk.Progressbar(card, mode="determinate", maximum=100, value=0, length=150)
        progress.grid(row=1, column=1, sticky="ew", padx=(14, 4), pady=(6, 0))

        actions = ttk.Frame(card, style="Card.TFrame")
        actions.grid(row=0, column=2, rowspan=2, sticky="e", padx=(12, 0))
        preview = ttk.Button(actions, text="Aperçu", command=lambda i=len(self.jobs): self._show_preview(i), state="disabled")
        save = ttk.Button(actions, text="Télécharger", command=lambda i=len(self.jobs): self._save_job(i), state="disabled")
        copy = ttk.Button(actions, text="Copier", command=lambda i=len(self.jobs): self._copy_job(i), state="disabled")
        preview.pack(side="left", padx=(0, 5))
        save.pack(side="left", padx=(0, 5))
        copy.pack(side="left")

        job.widgets = {
            "card": card, "name": name, "details": details, "status": status,
            "progress": progress, "preview": preview, "save": save, "copy": copy,
        }
        self.jobs.append(job)
        self._paint_job(job)
        self._update_controls()

    def _paint_job(self, job: Job) -> None:
        if not job.widgets:
            return
        colors = self._palette()
        status = job.widgets["status"]
        status.configure(foreground=colors["success"] if job.status == "success" else colors["error"] if job.status == "error" else colors["text"])

    @staticmethod
    def _format_size(size: int) -> str:
        if size >= 1024 * 1024:
            return f"{size / (1024 * 1024):.1f} Mo"
        if size >= 1024:
            return f"{size / 1024:.0f} Ko"
        return f"{size} octets"

    def _update_controls(self) -> None:
        count = len(self.jobs)
        self.count_label.configure(text=f"{count} élément{'s' if count != 1 else ''}")
        can_run = any(job.status in {"pending", "error"} for job in self.jobs)
        self.convert_button.configure(state="disabled" if self.busy or not can_run else "normal")
        self.choose_button.configure(state="disabled" if self.busy else "normal")
        self.clear_button.configure(state="disabled" if self.busy or not count else "normal")
        self.youtube_button.configure(state="disabled" if self.busy else "normal")
        self.zip_button.configure(state="normal" if self.zip_path and not self.busy else "disabled")

    def _start_conversions(self) -> None:
        if self.busy:
            return
        pending = [(index, job) for index, job in enumerate(self.jobs) if job.status in {"pending", "error"}]
        if not pending:
            return
        if self.batch_dir is None:
            try:
                _batch_id, self.batch_dir = create_batch_dir()
            except OSError as exc:
                messagebox.showerror("Dossier inaccessible", f"Impossible de créer le dossier de conversions : {exc}", parent=self.root)
                return
        self.busy = True
        self.zip_path = ""
        self.errors_clear()
        self.location_label.configure(text="Conversion en cours…")
        self._update_controls()
        worker = threading.Thread(target=self._convert_items, args=(pending, self.batch_dir), daemon=True)
        worker.start()

    def _convert_items(self, pending: list[tuple[int, Job]], batch_dir: Path) -> None:
        succeeded = False
        for index, job in pending:
            self.events.put(("started", index))
            try:
                if job.kind == "youtube":
                    filename, markdown = convert_youtube_url(job.value)
                    size = len(markdown.encode("utf-8"))
                else:
                    source = Path(job.value)
                    try:
                        size = source.stat().st_size
                    except OSError as exc:
                        raise ConversionError("Le fichier est illisible ou inaccessible.") from exc
                    guessed_mime = mimetypes.guess_type(source.name)[0]
                    accepted = MIME_BY_EXTENSION.get(source.suffix.lower(), set())
                    mime = guessed_mime if guessed_mime in accepted else next(iter(accepted), "")
                    validate_upload(source.name, mime, size)
                    filename, markdown = convert_path(source.name, source, mime, size)
                _conversion_id, output = save_conversion(batch_dir, filename, markdown)
                succeeded = True
                result = {
                    "status": "success", "filename": filename, "size": size,
                    "markdown": markdown, "output_path": str(output),
                }
            except ConversionError as exc:
                result = {"status": "error", "error": str(exc)}
            except Exception as exc:
                result = {"status": "error", "error": f"Conversion impossible ({exc.__class__.__name__})."}
            self.events.put(("finished", index, result))

        archive_path = ""
        if succeeded:
            archive = batch_dir / "conversions.zip"
            try:
                make_zip(batch_dir, archive)
                archive_path = str(archive)
            except OSError as exc:
                self.events.put(("error", f"Impossible de créer l’archive ZIP ({exc.__class__.__name__})."))
        self.events.put(("done", archive_path, str(batch_dir)))

    def _poll_worker(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == "started":
                    index = event[1]
                    job = self.jobs[index]
                    job.status = "running"
                    job.widgets["status"].configure(text="Conversion en cours…")
                    job.widgets["progress"].configure(mode="indeterminate")
                    job.widgets["progress"].start(10)
                    self._paint_job(job)
                elif kind == "finished":
                    self._finish_job(event[1], event[2])
                elif kind == "error":
                    self._append_error(event[1])
                elif kind == "done":
                    self.zip_path = event[1]
                    self.batch_dir = Path(event[2])
                    self.busy = False
                    self.location_label.configure(text=f"Enregistré dans : {self.batch_dir}")
                    self._update_controls()
        except queue.Empty:
            pass
        if self.root.winfo_exists():
            self.root.after(120, self._poll_worker)

    def _finish_job(self, index: int, result: dict) -> None:
        job = self.jobs[index]
        progress = job.widgets["progress"]
        progress.stop()
        progress.configure(mode="determinate", value=100 if result["status"] == "success" else 0)
        if result["status"] == "success":
            job.status = "success"
            job.name = result["filename"]
            job.size = result["size"]
            job.markdown = result["markdown"]
            job.widgets["name"].configure(text=job.name)
            kind = "URL YouTube" if job.kind == "youtube" else (Path(job.name).suffix.upper() or "Fichier")
            job.widgets["details"].configure(text=f"{kind}  ·  {self._format_size(job.size)}")
            job.widgets["status"].configure(text="Conversion réussie")
            for key in ("preview", "save", "copy"):
                job.widgets[key].configure(state="normal")
        else:
            job.status = "error"
            job.error = result["error"]
            job.widgets["status"].configure(text="Erreur")
            self._append_error(f"{job.name} : {job.error}")
        self._paint_job(job)

    def _show_preview(self, index: int) -> None:
        job = self.jobs[index]
        self.preview_job = index
        self.preview_text.configure(state="normal")
        self.preview_text.delete("1.0", "end")
        self.preview_text.insert("1.0", job.markdown)
        self.canvas.yview_moveto(1.0)

    def _copy_job(self, index: int) -> None:
        self._copy_text(self.jobs[index].markdown)

    def _copy_preview(self) -> None:
        text = self.preview_text.get("1.0", "end-1c")
        if text.strip():
            self._copy_text(text)

    def _copy_text(self, text: str) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.root.update_idletasks()
        self.location_label.configure(text="Markdown copié dans le presse-papiers.")

    def _save_job(self, index: int) -> None:
        job = self.jobs[index]
        self._save_markdown(job.name, job.markdown)

    def _save_preview(self) -> None:
        if self.preview_job is None:
            return
        self._save_job(self.preview_job)

    def _save_markdown(self, filename: str, markdown: str) -> None:
        target = filedialog.asksaveasfilename(
            parent=self.root,
            title="Enregistrer le Markdown",
            defaultextension=".md",
            initialfile=f"{Path(filename).stem or 'conversion'}.md",
            filetypes=[("Fichier Markdown", "*.md")],
        )
        if target:
            try:
                Path(target).write_text(markdown, encoding="utf-8")
                self.location_label.configure(text=f"Fichier enregistré : {target}")
            except OSError as exc:
                messagebox.showerror("Enregistrement impossible", str(exc), parent=self.root)

    def _download_zip(self) -> None:
        if not self.zip_path:
            return
        target = filedialog.asksaveasfilename(
            parent=self.root,
            title="Enregistrer l’archive ZIP",
            defaultextension=".zip",
            initialfile="conversions.zip",
            filetypes=[("Archive ZIP", "*.zip")],
        )
        if target:
            try:
                shutil.copy2(self.zip_path, target)
                self.location_label.configure(text=f"Archive enregistrée : {target}")
            except OSError as exc:
                messagebox.showerror("Enregistrement impossible", str(exc), parent=self.root)

    def _append_error(self, text: str) -> None:
        self.error_text.configure(state="normal")
        self.error_text.insert("end", text.rstrip() + "\n")
        self.error_text.see("end")
        self.error_text.configure(state="disabled")

    def errors_clear(self) -> None:
        self.error_text.configure(state="normal")
        self.error_text.delete("1.0", "end")
        self.error_text.configure(state="disabled")

    def _clear_list(self) -> None:
        if self.busy:
            return
        self.jobs.clear()
        for child in self.rows_frame.winfo_children():
            if child is not self.empty_label:
                child.destroy()
        self.empty_label.pack(fill="x", pady=18)
        self.preview_job = None
        self.preview_text.configure(state="normal")
        self.preview_text.delete("1.0", "end")
        self.preview_text.insert("1.0", "Choisissez « Aperçu » après une conversion réussie.")
        self.errors_clear()
        self.batch_dir = None
        self.zip_path = ""
        self.location_label.configure(text="")
        self._update_controls()

    def _close(self) -> None:
        if self.busy:
            messagebox.showinfo(
                "Conversion en cours",
                "Attendez la fin des conversions avant de fermer l’application.",
                parent=self.root,
            )
            return
        self._restore_file_drop()
        self.root.destroy()

    def run(self) -> int:
        self.root.mainloop()
        return 0


def main() -> int:
    """Point d’entrée de l’application portable."""
    try:
        return DesktopApp().run()
    except tk.TclError as exc:
        # Une erreur d’interface Tk remonte un message simple au lieu d’un plantage silencieux.
        try:
            messagebox.showerror("Démarrage impossible", str(exc))
        except tk.TclError:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
