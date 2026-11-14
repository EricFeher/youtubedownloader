"""Asztali felület (CustomTkinter). A letöltés háttérszálon fut, az események sorban érkeznek."""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from .downloader import (
    VIDEO_QUALITIES,
    Downloader,
    DownloadRequest,
    Event,
    Finished,
    Log,
    Mode,
    Progress,
    Status,
)

APP_TITLE = "YT Letöltő"
POLL_MS = 100

MODE_LABELS = {"Videó (MP4)": Mode.VIDEO, "Csak hang (MP3)": Mode.AUDIO}


def icon_path() -> Path:
    base = Path(getattr(sys, "_MEIPASS", "")) if getattr(sys, "frozen", False) else Path(__file__).parent.parent / "assets"
    return base / "icon.ico"


def default_output_dir() -> Path:
    downloads = Path.home() / "Downloads"
    return downloads if downloads.is_dir() else Path.home()


def open_folder(path: Path) -> None:
    if sys.platform == "win32":
        os.startfile(path)  # noqa: S606 - a felhasználó saját mappája
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def format_speed(bps: float | None) -> str:
    if not bps:
        return ""
    for unit in ("B/s", "KB/s", "MB/s", "GB/s"):
        if bps < 1024:
            return f"{bps:.1f} {unit}"
        bps /= 1024
    return f"{bps:.1f} TB/s"


def format_eta(seconds: int | None) -> str:
    if seconds is None:
        return ""
    minutes, secs = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


class App(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("720x560")
        self.minsize(560, 480)
        if sys.platform == "win32" and icon_path().is_file():
            # A CustomTkinter induláskor a saját ikonját állítja be, ezt utána írjuk felül.
            self.after(250, lambda: self.iconbitmap(str(icon_path())))

        self._events: queue.Queue[Event] = queue.Queue()
        self._downloader: Downloader | None = None
        self._output_dir = default_output_dir()

        self._build_ui()
        self._on_mode_change(self.mode_var.get())
        self.after(POLL_MS, self._drain_events)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # --- Felépítés ---------------------------------------------------------

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=1)
        pad = {"padx": 16, "pady": (12, 0)}

        ctk.CTkLabel(self, text=APP_TITLE, font=ctk.CTkFont(size=22, weight="bold")).grid(
            row=0, column=0, sticky="w", **pad
        )

        # Link
        url_row = ctk.CTkFrame(self, fg_color="transparent")
        url_row.grid(row=1, column=0, sticky="ew", **pad)
        url_row.grid_columnconfigure(0, weight=1)
        self.url_entry = ctk.CTkEntry(url_row, placeholder_text="Illeszd be a YouTube linket…", height=36)
        self.url_entry.grid(row=0, column=0, sticky="ew")
        self.url_entry.bind("<Return>", lambda _e: self._start())
        ctk.CTkButton(url_row, text="Beillesztés", width=100, height=36, command=self._paste).grid(
            row=0, column=1, padx=(8, 0)
        )

        # Beállítások
        options = ctk.CTkFrame(self)
        options.grid(row=2, column=0, sticky="ew", **pad)
        options.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(options, text="Formátum").grid(row=0, column=0, sticky="w", padx=12, pady=(12, 6))
        self.mode_var = ctk.StringVar(value=next(iter(MODE_LABELS)))
        ctk.CTkSegmentedButton(
            options, values=list(MODE_LABELS), variable=self.mode_var, command=self._on_mode_change
        ).grid(row=0, column=1, sticky="w", padx=12, pady=(12, 6))

        ctk.CTkLabel(options, text="Minőség").grid(row=1, column=0, sticky="w", padx=12, pady=6)
        quality_row = ctk.CTkFrame(options, fg_color="transparent")
        quality_row.grid(row=1, column=1, sticky="w", padx=12, pady=6)
        self.quality_var = ctk.StringVar(value=next(iter(VIDEO_QUALITIES)))
        self.quality_menu = ctk.CTkOptionMenu(quality_row, values=list(VIDEO_QUALITIES), variable=self.quality_var)
        self.quality_menu.grid(row=0, column=0)
        self.compat_var = ctk.BooleanVar(value=False)
        self.compat_check = ctk.CTkCheckBox(
            quality_row, text="Kompatibilis mód (H.264, max. 1080p)", variable=self.compat_var
        )
        self.compat_check.grid(row=0, column=1, padx=(12, 0))
        self.audio_note = ctk.CTkLabel(quality_row, text="MP3, 320 kbps – a legjobb elérhető hangsávból")

        self.playlist_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            options, text="Teljes lejátszási lista letöltése (ha a link listát tartalmaz)", variable=self.playlist_var
        ).grid(row=2, column=1, sticky="w", padx=12, pady=6)

        ctk.CTkLabel(options, text="Mentés ide").grid(row=3, column=0, sticky="w", padx=12, pady=(6, 12))
        folder_row = ctk.CTkFrame(options, fg_color="transparent")
        folder_row.grid(row=3, column=1, sticky="ew", padx=12, pady=(6, 12))
        folder_row.grid_columnconfigure(0, weight=1)
        self.folder_label = ctk.CTkLabel(folder_row, text=str(self._output_dir), anchor="w")
        self.folder_label.grid(row=0, column=0, sticky="ew")
        ctk.CTkButton(folder_row, text="Tallózás…", width=90, command=self._choose_folder).grid(
            row=0, column=1, padx=(8, 0)
        )
        ctk.CTkButton(folder_row, text="Megnyitás", width=90, command=lambda: open_folder(self._output_dir)).grid(
            row=0, column=2, padx=(8, 0)
        )

        # Folyamat
        progress = ctk.CTkFrame(self, fg_color="transparent")
        progress.grid(row=3, column=0, sticky="ew", **pad)
        progress.grid_columnconfigure(0, weight=1)
        self.download_btn = ctk.CTkButton(
            progress, text="Letöltés", height=40, font=ctk.CTkFont(size=15, weight="bold"), command=self._start
        )
        self.download_btn.grid(row=0, column=0, sticky="ew")
        self.cancel_btn = ctk.CTkButton(
            progress, text="Mégse", height=40, width=100, fg_color="gray40", hover_color="gray30",
            state="disabled", command=self._cancel,
        )
        self.cancel_btn.grid(row=0, column=1, padx=(8, 0))
        self.progress_bar = ctk.CTkProgressBar(progress)
        self.progress_bar.set(0)
        self.progress_bar.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(12, 4))
        self.status_label = ctk.CTkLabel(progress, text="Készen áll.", anchor="w")
        self.status_label.grid(row=2, column=0, columnspan=2, sticky="ew")

        # Napló
        self.log_box = ctk.CTkTextbox(self, height=120, font=ctk.CTkFont(family="Consolas", size=12))
        self.log_box.grid(row=4, column=0, sticky="nsew", padx=16, pady=12)
        self.log_box.configure(state="disabled")
        self.log_box.tag_config("warning", foreground="#d39e00")
        self.log_box.tag_config("error", foreground="#e5534b")

    # --- Felhasználói műveletek --------------------------------------------

    def _paste(self) -> None:
        try:
            text = self.clipboard_get().strip()
        except Exception:  # noqa: BLE001 - üres vagy nem szöveges vágólap
            return
        self.url_entry.delete(0, "end")
        self.url_entry.insert(0, text)

    def _choose_folder(self) -> None:
        chosen = filedialog.askdirectory(initialdir=self._output_dir, title="Mentési mappa kiválasztása")
        if chosen:
            self._output_dir = Path(chosen)
            self.folder_label.configure(text=chosen)

    def _on_mode_change(self, label: str) -> None:
        if MODE_LABELS[label] is Mode.AUDIO:
            self.quality_menu.grid_remove()
            self.compat_check.grid_remove()
            self.audio_note.grid(row=0, column=0)
        else:
            self.audio_note.grid_remove()
            self.quality_menu.grid()
            self.compat_check.grid()

    def _start(self) -> None:
        if self._downloader:
            return
        url = self.url_entry.get().strip()
        if not url:
            self._set_status("Adj meg egy linket.")
            return

        request = DownloadRequest(
            url=url,
            output_dir=self._output_dir,
            mode=MODE_LABELS[self.mode_var.get()],
            max_height=VIDEO_QUALITIES[self.quality_var.get()],
            compatible=self.compat_var.get(),
            playlist=self.playlist_var.get(),
        )
        self._downloader = Downloader(self._events.put)
        self._set_busy(True)
        self.progress_bar.set(0)
        self._log(f"▶ {url}")
        threading.Thread(target=self._downloader.run, args=(request,), daemon=True).start()

    def _cancel(self) -> None:
        if self._downloader:
            self._downloader.cancel()
            self._set_status("Megszakítás…")
            self.cancel_btn.configure(state="disabled")

    def _on_close(self) -> None:
        if self._downloader:
            self._downloader.cancel()
        self.destroy()

    # --- Események ---------------------------------------------------------

    def _drain_events(self) -> None:
        try:
            while True:
                self._handle(self._events.get_nowait())
        except queue.Empty:
            pass
        self.after(POLL_MS, self._drain_events)

    def _handle(self, event: Event) -> None:
        match event:
            case Progress():
                if event.percent is not None:
                    self.progress_bar.set(event.percent / 100)
                parts = [f"[{event.item}]" if event.item else "", "Letöltés"]
                if event.percent is not None:
                    parts.append(f"{event.percent:.1f}%")
                if speed := format_speed(event.speed):
                    parts.append(f"· {speed}")
                if eta := format_eta(event.eta):
                    parts.append(f"· hátravan {eta}")
                self._set_status(" ".join(p for p in parts if p))
            case Status():
                self._set_status(event.text)
            case Log():
                self._log(event.text, event.level)
            case Finished():
                self._downloader = None
                self._set_busy(False)
                self._set_status(event.message)
                if event.ok:
                    self.progress_bar.set(1)
                    for path in event.files:
                        self._log(f"✔ {path}")
                else:
                    self._log(event.message, "error")

    def _set_busy(self, busy: bool) -> None:
        self.download_btn.configure(state="disabled" if busy else "normal")
        self.cancel_btn.configure(state="normal" if busy else "disabled")

    def _set_status(self, text: str) -> None:
        self.status_label.configure(text=text)

    def _log(self, text: str, level: str = "info") -> None:
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text + "\n", level if level != "info" else ())
        self.log_box.see("end")
        self.log_box.configure(state="disabled")


def main() -> None:
    ctk.set_appearance_mode("system")
    ctk.set_default_color_theme("blue")
    App().mainloop()
