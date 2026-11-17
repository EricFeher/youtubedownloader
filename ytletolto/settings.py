"""A felhasználó utolsó beállításainak megőrzése (mentési mappa, formátum, minőség)."""

from __future__ import annotations

import ctypes
import json
import locale
import os
import re
import subprocess
import sys
from pathlib import Path

DEFAULTS: dict = {
    "language": "system",
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
    # A korábbi mappanév őrzi meg a már elmentett felhasználói beállításokat.
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
    settings["language"] = normalize_language(settings["language"])
    if not settings["output_dir"] or not Path(settings["output_dir"]).is_dir():
        settings["output_dir"] = str(default_output_dir())
    return settings


def normalize_language(value: object) -> str:
    return value if isinstance(value, str) and value in {"hu", "en"} else "system"


def system_locale() -> str | None:
    """Read the user's display language, rather than Windows' regional format."""
    try:
        if sys.platform == "win32":
            language_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            return locale.windows_locale.get(language_id)
        if sys.platform == "darwin":
            result = subprocess.run(["defaults", "read", "-g", "AppleLanguages"],
                                    capture_output=True, text=True, timeout=2, check=True)
            match = re.search(r"[a-zA-Z]{2,3}(?:[-_][a-zA-Z0-9]+)*", result.stdout)
            if match:
                return match[0]
        else:
            for name in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
                if os.environ.get(name):
                    return os.environ[name].split(":")[0]
        return locale.getlocale()[0]
    except (AttributeError, OSError, ValueError, subprocess.SubprocessError):
        return None


def resolve_language(value: object) -> str:
    preference = normalize_language(value)
    if preference != "system":
        return preference
    code = (system_locale() or "").replace("_", "-").split("-")[0].split(".")[0].lower()
    return code if code in {"hu", "en"} else "en"


def save(settings: dict, path: Path | None = None) -> None:
    path = path or settings_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({k: settings[k] for k in DEFAULTS if k in settings}, indent=2), encoding="utf-8")
    except OSError:
        pass  # A beállítások mentése kényelmi funkció, hiba esetén csendben kihagyjuk.
