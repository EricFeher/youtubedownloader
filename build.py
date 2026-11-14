"""Futtatható állomány készítése PyInstallerrel.

Windows-on letölti az ffmpeg-et és a Deno-t a `vendor/` mappába, és beépíti őket,
így a kész programhoz semmit nem kell külön telepíteni. Más rendszeren a csomag a
rendszerre telepített ffmpeg-et és Deno-t használja.

    python build.py             # dist/YTLetolto/YTLetolto.exe (mappa, gyors indulás)
    python build.py --onefile   # dist/YTLetolto.exe (egyetlen fájl, lassabb indulás)
"""

from __future__ import annotations

import argparse
import io
import os
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

import PyInstaller.__main__

ROOT = Path(__file__).resolve().parent
VENDOR = ROOT / "vendor"
APP_NAME = "YTLetolto"

# A yt-dlp csapat ffmpeg buildje, YouTube-hoz szükséges javításokkal.
FFMPEG_WIN_URL = (
    "https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl-shared.zip"
)
DENO_WIN_URL = "https://github.com/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip"


def download_zip(url: str) -> zipfile.ZipFile:
    print(f"Letöltés: {url}")
    with urllib.request.urlopen(url) as response:  # noqa: S310 - fix https URL-ek
        return zipfile.ZipFile(io.BytesIO(response.read()))


def fetch_windows_tools() -> None:
    VENDOR.mkdir(exist_ok=True)

    if not (VENDOR / "ffmpeg.exe").is_file():
        with download_zip(FFMPEG_WIN_URL) as archive:
            # A shared build: ffmpeg.exe, ffprobe.exe és a közös DLL-ek a bin/ mappában.
            for member in archive.namelist():
                path = Path(member)
                if path.parent.name == "bin" and path.suffix in {".exe", ".dll"} and path.name != "ffplay.exe":
                    (VENDOR / path.name).write_bytes(archive.read(member))

    if not (VENDOR / "deno.exe").is_file():
        with download_zip(DENO_WIN_URL) as archive:
            (VENDOR / "deno.exe").write_bytes(archive.read("deno.exe"))


def vendor_binaries() -> list[str]:
    if not VENDOR.is_dir():
        return []
    files = sorted(p for p in VENDOR.iterdir() if p.is_file() and not p.name.startswith("."))
    return [f"{p}{os.pathsep}." for p in files]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--onefile", action="store_true", help="egyetlen .exe a mappa helyett")
    parser.add_argument("--no-fetch", action="store_true", help="ne töltse le az ffmpeg-et és a Deno-t")
    args = parser.parse_args()

    if sys.platform == "win32" and not args.no_fetch:
        fetch_windows_tools()

    shutil.rmtree(ROOT / "build", ignore_errors=True)

    pyinstaller_args = [
        str(ROOT / "main.py"),
        "--name", APP_NAME,
        "--windowed",
        "--noconfirm",
        "--clean",
        "--onefile" if args.onefile else "--onedir",
        "--add-data", f"{ROOT / 'ytletolto' / 'web'}{os.pathsep}ytletolto/web",
        "--distpath", str(ROOT / "dist"),
        "--workpath", str(ROOT / "build"),
        "--specpath", str(ROOT / "build"),
    ]
    icon = ROOT / "assets" / ("icon.ico" if sys.platform == "win32" else "icon.png")
    if icon.is_file():
        pyinstaller_args += ["--icon", str(icon)]
    for binary in vendor_binaries():
        pyinstaller_args += ["--add-binary", binary]

    PyInstaller.__main__.run(pyinstaller_args)


if __name__ == "__main__":
    main()
