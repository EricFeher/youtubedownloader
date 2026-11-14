"""A felhasználó utolsó beállításainak megőrzése (mentési mappa, formátum, minőség)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

DEFAULTS: dict = {
    "output_dir": "",
    "mode": "video",
    "quality": "best",
    "compatible": False,
    "container": "mp4",
    "audio_format": "mp3",
}


def settings_path() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "YTLetolto" / "settings.json"


def default_output_dir() -> Path:
    downloads = Path.home() / "Downloads"
    return downloads if downloads.is_dir() else Path.home()


def load(path: Path | None = None) -> dict:
    path = path or settings_path()
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        stored = {}
    settings = {**DEFAULTS, **{k: v for k, v in stored.items() if k in DEFAULTS}}
    if not settings["output_dir"] or not Path(settings["output_dir"]).is_dir():
        settings["output_dir"] = str(default_output_dir())
    return settings


def save(settings: dict, path: Path | None = None) -> None:
    path = path or settings_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({k: settings[k] for k in DEFAULTS if k in settings}, indent=2), encoding="utf-8")
    except OSError:
        pass  # A beállítások mentése kényelmi funkció, hiba esetén csendben kihagyjuk.
