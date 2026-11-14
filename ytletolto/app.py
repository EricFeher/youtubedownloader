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
import time
from pathlib import Path

import webview
from yt_dlp.utils import DownloadError

from . import settings as settings_store
from .download_queue import (
    DownloadQueue,
    ItemEvent,
    QueueEvent,
    build_request,
    event_payload,
    extract_urls,
    is_playlist_url,
)
from .downloader import Downloader, Progress, find_tools, probe, split_by_mode

APP_TITLE = "YT Letöltő"
WEB_DIR = Path(__file__).resolve().parent / "web"
PROGRESS_INTERVAL = 0.1  # mp – ennél sűrűbben nem frissítjük a folyamatjelzőt


class Api:
    """A felület által hívható metódusok. Csak a nyilvános metódusok látszanak JS-ből."""

    def __init__(self) -> None:
        self._window: webview.Window | None = None
        self._tools = find_tools()
        self._settings = settings_store.load()
        self._queue = DownloadQueue(self._emit, lambda emit: Downloader(emit, self._tools))
        self._last_progress = 0.0

    def attach(self, window: webview.Window) -> None:
        self._window = window

    # --- JS-ből hívható ----------------------------------------------------

    def init(self) -> dict:
        return {
            "settings": self._settings,
            "ffmpeg": bool(self._tools.ffmpeg_dir),
            "js_runtime": bool(self._tools.js_runtimes),
            "queue": event_payload(self._queue.snapshot()),
        }

    def probe(self, url: str, playlist: bool = False) -> dict:
        try:
            return {"ok": True, "info": dataclasses.asdict(probe(url.strip(), self._tools, bool(playlist)))}
        except DownloadError as e:
            return {"ok": False, "error": _short_error(str(e))}
        except Exception as e:  # noqa: BLE001 - a felületnek minden hibáról tudnia kell
            return {"ok": False, "error": str(e)}

    def paste(self) -> str:
        return read_clipboard()

    def split_urls(self, text: str) -> list[str]:
        return extract_urls(text or "")

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

    def enqueue(self, options: dict) -> dict:
        """Sorba állítja a linkeket (`items`: url, és ha az előnézetből ismert: title, thumbnail, playlist).

        Ha a `playlist` hiányzik (pl. több beillesztett linknél), a link alakjából döntjük el.
        """
        output_dir = Path(self._settings["output_dir"])
        entries = []
        for entry in options.get("items") or []:
            url = str(entry.get("url") or "").strip()
            if not url:
                continue
            playlist = entry.get("playlist")
            playlist = is_playlist_url(url) if playlist is None else bool(playlist)
            request = build_request(url, options, output_dir, playlist)
            requests = split_by_mode(request, entry.get("selection"))
            if not requests:
                return {"ok": False, "error": "Jelölj ki legalább egy elemet a listában."}
            entries.extend((r, entry.get("title") or "", entry.get("thumbnail")) for r in requests)
        if not entries:
            return {"ok": False, "error": "Adj meg egy linket."}
        if not self._tools.ffmpeg_dir:
            return {"ok": False, "error": "Az ffmpeg nem található. Telepítsd, vagy használd a csomagolt alkalmazást."}

        added = sum(1 for item in self._queue.add_many(entries) if item)
        request = entries[-1][0]
        self.save_settings(
            {
                "mode": request.mode.value,
                "quality": str(request.max_height) if request.max_height else "best",
                "compatible": request.compatible,
                "container": request.container,
                "audio_format": request.audio_format,
            }
        )
        return {"ok": True, "added": added, "skipped": len(entries) - added}

    def cancel(self, item_id: int) -> bool:
        return self._queue.cancel(int(item_id))

    def remove(self, item_id: int) -> bool:
        return self._queue.remove(int(item_id))

    def retry(self, item_id: int) -> bool:
        return self._queue.retry(int(item_id))

    def clear_finished(self) -> int:
        return self._queue.clear_finished()

    # --- Belső -------------------------------------------------------------

    def _emit(self, event: QueueEvent) -> None:
        if isinstance(event, ItemEvent) and isinstance(event.event, Progress) and event.event.percent != 100.0:
            now = time.monotonic()
            if now - self._last_progress < PROGRESS_INTERVAL:
                return
            self._last_progress = now
        if not self._window:
            return
        self._window.evaluate_js(f"window.app && window.app.onEvent({json.dumps(event_payload(event))})")

    def on_closing(self) -> None:
        self._queue.shutdown()


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
