"""Asztali ablak (pywebview): a felület HTML/CSS/JS, a logika Python.

A pywebview a rendszer saját böngészőmotorját használja (Windows: Edge WebView2,
macOS: WebKit), így nem kell külön szerver vagy böngésző. A JS a `window.pywebview.api`
objektumon keresztül hívja az `Api` metódusait; a Python az eseményeket
`window.app.onEvent(...)` hívással küldi vissza.
"""

from __future__ import annotations

import ctypes
import dataclasses
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import webview
from yt_dlp.utils import DownloadError

from . import settings as settings_store
from .downloader import (
    AUDIO_FORMATS,
    VIDEO_CONTAINERS,
    Downloader,
    DownloadRequest,
    Event,
    Finished,
    Mode,
    Progress,
    find_tools,
    probe,
)

APP_TITLE = "YT Letöltő"
WEB_DIR = Path(__file__).resolve().parent / "web"
PROGRESS_INTERVAL = 0.1  # mp – ennél sűrűbben nem frissítjük a folyamatjelzőt


class Api:
    """A felület által hívható metódusok. Csak a nyilvános metódusok látszanak JS-ből."""

    def __init__(self) -> None:
        self._window: webview.Window | None = None
        self._tools = find_tools()
        self._settings = settings_store.load()
        self._downloader: Downloader | None = None
        self._lock = threading.Lock()
        self._last_progress = 0.0

    def attach(self, window: webview.Window) -> None:
        self._window = window

    # --- JS-ből hívható ----------------------------------------------------

    def init(self) -> dict:
        return {
            "settings": self._settings,
            "ffmpeg": bool(self._tools.ffmpeg_dir),
            "js_runtime": bool(self._tools.js_runtimes),
        }

    def probe(self, url: str) -> dict:
        try:
            return {"ok": True, "info": dataclasses.asdict(probe(url.strip(), self._tools))}
        except DownloadError as e:
            return {"ok": False, "error": _short_error(str(e))}
        except Exception as e:  # noqa: BLE001 - a felületnek minden hibáról tudnia kell
            return {"ok": False, "error": str(e)}

    def paste(self) -> str:
        return read_clipboard()

    def choose_folder(self) -> str | None:
        if not self._window:
            return None
        result = self._window.create_file_dialog(
            webview.FileDialog.FOLDER, directory=self._settings["output_dir"]
        )
        if not result:
            return None
        folder = result[0] if isinstance(result, (list, tuple)) else result
        self.save_settings({"output_dir": folder})
        return folder

    def open_folder(self) -> None:
        open_path(Path(self._settings["output_dir"]))

    def reveal(self, path: str) -> None:
        reveal_file(Path(path))

    def save_settings(self, changes: dict) -> None:
        self._settings.update({k: v for k, v in changes.items() if k in settings_store.DEFAULTS})
        settings_store.save(self._settings)

    def start(self, options: dict) -> dict:
        url = (options.get("url") or "").strip()
        if not url:
            return {"ok": False, "error": "Adj meg egy linket."}

        with self._lock:
            if self._downloader:
                return {"ok": False, "error": "Már fut egy letöltés."}
            quality = options.get("quality", "best")
            container = options.get("container")
            if container not in VIDEO_CONTAINERS:
                container = VIDEO_CONTAINERS[0]
            audio_format = options.get("audio_format")
            if audio_format not in AUDIO_FORMATS:
                audio_format = AUDIO_FORMATS[0]
            request = DownloadRequest(
                url=url,
                output_dir=Path(self._settings["output_dir"]),
                mode=Mode(options.get("mode", "video")),
                max_height=None if quality == "best" else int(quality),
                compatible=bool(options.get("compatible")),
                playlist=bool(options.get("playlist")),
                container=container,
                audio_format=audio_format,
            )
            self.save_settings(
                {
                    "mode": request.mode.value,
                    "quality": quality,
                    "compatible": request.compatible,
                    "container": container,
                    "audio_format": audio_format,
                }
            )
            self._downloader = Downloader(self._emit, self._tools)
            threading.Thread(target=self._run, args=(self._downloader, request), daemon=True).start()
        return {"ok": True}

    def cancel(self) -> None:
        with self._lock:
            if self._downloader:
                self._downloader.cancel()

    # --- Belső -------------------------------------------------------------

    def _run(self, downloader: Downloader, request: DownloadRequest) -> None:
        try:
            downloader.run(request)
        finally:
            with self._lock:
                self._downloader = None

    def _emit(self, event: Event) -> None:
        if isinstance(event, Progress) and event.percent != 100.0:
            now = time.monotonic()
            if now - self._last_progress < PROGRESS_INTERVAL:
                return
            self._last_progress = now
        if not self._window:
            return
        payload = {"type": type(event).__name__.lower(), **dataclasses.asdict(event)}
        if isinstance(event, Finished):
            payload["files"] = list(event.files)
        self._window.evaluate_js(f"window.app && window.app.onEvent({json.dumps(payload)})")

    def on_closing(self) -> None:
        self.cancel()


# --- Rendszerfunkciók --------------------------------------------------------


def open_path(path: Path) -> None:
    if sys.platform == "win32":
        os.startfile(path)  # noqa: S606 - a felhasználó saját mappája
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def reveal_file(path: Path) -> None:
    """Megnyitja a fájlt tartalmazó mappát, és kijelöli benne a fájlt."""
    if not path.exists():
        open_path(path.parent)
    elif sys.platform == "win32":
        subprocess.Popen(["explorer", "/select,", str(path)])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(path)])
    else:
        open_path(path.parent)


def read_clipboard() -> str:
    try:
        if sys.platform == "win32":
            return _read_clipboard_windows()
        if sys.platform == "darwin":
            return subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=2).stdout.strip()
        return subprocess.run(
            ["xclip", "-selection", "clipboard", "-o"], capture_output=True, text=True, timeout=2
        ).stdout.strip()
    except Exception:  # noqa: BLE001 - üres vagy nem szöveges vágólap
        return ""


def _read_clipboard_windows() -> str:
    CF_UNICODETEXT = 13
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    user32.GetClipboardData.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    if not user32.OpenClipboard(None):
        return ""
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return ""
        pointer = kernel32.GlobalLock(handle)
        try:
            return ctypes.wstring_at(pointer).strip() if pointer else ""
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def _short_error(message: str) -> str:
    message = message.removeprefix("ERROR: ").strip()
    if "[youtube]" in message and ":" in message:
        message = message.split(":", 2)[-1].strip()
    return message or "Nem sikerült lekérni a videó adatait."


def main() -> None:
    api = Api()
    window = webview.create_window(
        APP_TITLE,
        url=str(WEB_DIR / "index.html"),
        js_api=api,
        width=820,
        height=900,
        min_size=(600, 700),
        background_color="#242424",
    )
    api.attach(window)
    window.events.closing += api.on_closing
    webview.start(private_mode=True)
