"""GitHub release checks and verified, staged Windows portable updates."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

from . import APP_NAME
from ._build import FLAVOR, REPOSITORY, VERSION

ASSETS = {"onefile": f"{APP_NAME}.exe", "onedir": "MediaMindsDownloader-windows.zip"}
MAX_PACKAGE_SIZE = 2 * 1024**3


def version_tuple(value: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", value)
    if not match:
        raise ValueError("A kiadás verziója nem érvényes (vX.Y.Z szükséges).")
    return tuple(int(part) for part in match.groups())


def _release_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    return (parsed.scheme == "https" and parsed.netloc == "github.com"
            and parsed.path.startswith(f"/{REPOSITORY}/releases/download/")
            and not parsed.query and not parsed.fragment)


def _get(url: str):
    return urllib.request.urlopen(urllib.request.Request(url, headers={
        "User-Agent": f"MediaMindsDownloader/{VERSION}",
        "Accept": "application/vnd.github+json" if url.startswith("https://api.github.com/") else "application/octet-stream",
    }), timeout=30)


def extract_package(archive_path: Path, destination: Path) -> Path:
    """Only accept the known folder bundle, without links or escaping paths."""
    with zipfile.ZipFile(archive_path) as archive:
        total = 0
        for member in archive.infolist():
            parts = member.filename.replace("\\", "/").split("/")
            if (parts[0] != APP_NAME or any(p in {"..", "."} or ":" in p for p in parts)
                    or (member.external_attr >> 16) & 0o170000 == 0o120000):
                raise ValueError("A frissítési csomag nem biztonságos útvonalat tartalmaz.")
            total += member.file_size
            if total > MAX_PACKAGE_SIZE:
                raise ValueError("A kicsomagolt frissítés túl nagy.")
        archive.extractall(destination)
    bundle = destination / APP_NAME
    exe = bundle / f"{APP_NAME}.exe"
    if not exe.is_file() or not (bundle / "_internal").is_dir():
        raise ValueError("Hiányos Windows-frissítési csomag.")
    with exe.open("rb") as source:
        if source.read(2) != b"MZ":
            raise ValueError("Érvénytelen Windows-programfájl.")
    return bundle


class Updater:
    def __init__(self, emit=lambda state: None):
        self._emit = emit
        self._lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._closed = threading.Event()
        self._release: dict | None = None
        self._stage: Path | None = None
        self._payload: Path | None = None
        self._state = {
            "current_version": VERSION, "status": "idle", "available": False,
            "supported": sys.platform == "win32" and bool(getattr(sys, "frozen", False)) and FLAVOR in ASSETS,
            "version": "", "notes": "", "published_at": "", "progress": None, "error": "",
        }

    def snapshot(self) -> dict:
        with self._state_lock:
            return dict(self._state)

    def _set(self, **changes) -> dict:
        with self._state_lock:
            self._state.update(changes)
            state = dict(self._state)
        self._emit(state)
        return state

    def check(self) -> dict:
        if not self._lock.acquire(blocking=False):
            return self.snapshot()
        try:
            if self.snapshot()["status"] in {"ready", "installing"}:
                return self.snapshot()
            self._set(status="checking", error="")
            try:
                with _get(f"https://api.github.com/repos/{REPOSITORY}/releases/latest") as response:
                    raw = response.read(2 * 1024**2 + 1)
                if len(raw) > 2 * 1024**2:
                    raise ValueError("Túl nagy kiadási leírás.")
                release = json.loads(raw)
                if release.get("draft") or release.get("prerelease"):
                    raise ValueError("Ez nem stabil kiadás.")
                version = release["tag_name"]
                available = version_tuple(version) > version_tuple(VERSION)
                self._release = release
                return self._set(status="available" if available else "current", available=available,
                                 version=version.removeprefix("v"), notes=str(release.get("body") or "Ehhez a kiadáshoz még nincs kiadási megjegyzés."),
                                 published_at=str(release.get("published_at") or ""))
            except urllib.error.HTTPError as exc:
                message = "Még nincs közzétett kiadás." if exc.code == 404 else "A kiadások most nem érhetők el. Próbáld újra később."
                return self._set(status="error", error=message)
            except Exception:  # Network and malformed release data must not interrupt downloads.
                return self._set(status="error", error="Nem sikerült ellenőrizni a frissítést. Ellenőrizd az internetkapcsolatot, majd próbáld újra.")
        finally:
            self._lock.release()

    def download(self) -> dict:
        if not self._lock.acquire(blocking=False):
            return self.snapshot()
        try:
            state = self.snapshot()
            if state["status"] in {"ready", "installing"}:
                return state
            if not state["supported"] or not state["available"] or not self._release:
                return self._set(error="Ehhez a példányhoz nincs telepíthető frissítés.")
            self._set(status="downloading", progress=0, error="")
            try:
                asset = next((a for a in self._release.get("assets", []) if a["name"] == ASSETS[FLAVOR] and a.get("state") == "uploaded"), None)
                if not asset:
                    raise ValueError("A kiadás még nem tartalmaz ehhez a változathoz frissítési csomagot. Próbáld újra később.")
                url, digest, size = asset["browser_download_url"], asset.get("digest", ""), asset["size"]
                if not _release_url(url) or not re.fullmatch(r"sha256:[a-fA-F0-9]{64}", digest or ""):
                    raise ValueError("A kiadásból hiányzik az ellenőrzött frissítési csomag.")
                if not isinstance(size, int) or not 0 < size <= MAX_PACKAGE_SIZE:
                    raise ValueError("Érvénytelen frissítési csomagméret.")
                self._cleanup()
                # Same volume and writable location, outside the files being replaced.
                self._stage = Path(tempfile.mkdtemp(prefix=".mm-update-", dir=Path(sys.executable).resolve().parent))
                package = self._stage / "package"
                hasher, received, last_progress = hashlib.sha256(), 0, -1
                with _get(url) as response, package.open("wb") as output:
                    while chunk := response.read(1024 * 1024):
                        if self._closed.is_set():
                            raise ValueError("A frissítés letöltése megszakadt.")
                        received += len(chunk)
                        if received > size:
                            raise ValueError("A csomag mérete nem egyezik a kiadással.")
                        output.write(chunk)
                        hasher.update(chunk)
                        progress = int(received * 100 / size)
                        if progress != last_progress:
                            self._set(progress=progress)
                            last_progress = progress
                if received != size or hasher.hexdigest() != digest[7:].lower():
                    raise ValueError("A letöltött frissítés ellenőrzése sikertelen. Próbáld újra.")
                if FLAVOR == "onedir":
                    self._payload = extract_package(package, self._stage / "payload")
                else:
                    with package.open("rb") as source:
                        if source.read(2) != b"MZ":
                            raise ValueError("Érvénytelen Windows-programfájl.")
                    self._payload = self._stage / "payload"
                    self._payload.mkdir()
                    package.replace(self._payload / Path(sys.executable).name)
                if self._closed.is_set():
                    raise ValueError("A frissítés letöltése megszakadt.")
                return self._set(status="ready", progress=100)
            except Exception as exc:
                self._cleanup()
                message = str(exc) if isinstance(exc, ValueError) else "A frissítés letöltése nem sikerült. Ellenőrizd a kapcsolatot, a szabad helyet és a mappa írhatóságát."
                return self._set(status="error", error=message, progress=None)
        finally:
            self._lock.release()

    def launch_installer(self) -> None:
        with self._lock:
            if self.snapshot()["status"] != "ready" or not self._stage or not self._payload:
                raise ValueError("Előbb töltsd le a frissítést.")
            exe = Path(sys.executable).resolve()
            # The onedir archive has a fixed executable name; allow a renamed local exe.
            bundled_exe = self._payload / f"{APP_NAME}.exe"
            if FLAVOR == "onedir" and exe.name != bundled_exe.name and bundled_exe.exists():
                bundled_exe.replace(self._payload / exe.name)
            config = {
                "target": str(exe.parent), "payload": str(self._payload), "stage": str(self._stage),
                "exe": exe.name, "names": [exe.name] + (["_internal"] if FLAVOR == "onedir" else []),
                "pids": [os.getpid()] + ([os.getppid()] if FLAVOR == "onefile" else []),
            }
            (self._stage / "update.json").write_text(json.dumps(config), encoding="utf-8")
            script = self._stage / "install.ps1"
            script.write_text((Path(__file__).parent / "install_update.ps1").read_text(encoding="utf-8"), encoding="utf-8-sig")
            powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
            subprocess.Popen([str(powershell), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                             creationflags=subprocess.CREATE_NO_WINDOW, close_fds=True)
            self._set(status="installing", error="")

    def _cleanup(self) -> None:
        if self._stage:
            shutil.rmtree(self._stage, ignore_errors=True)
        self._stage = self._payload = None

    def close(self) -> None:
        self._closed.set()
        # Never remove a helper's payload; an in-flight download observes _closed.
        if self._lock.acquire(blocking=False):
            try:
                if self.snapshot()["status"] != "installing":
                    self._cleanup()
            finally:
                self._lock.release()
