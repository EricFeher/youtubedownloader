"""Futtatható állomány készítése PyInstallerrel.

Windows-on letölti az ffmpeg-et és a Deno-t a `vendor/` mappába, és beépíti őket,
így a kész programhoz semmit nem kell külön telepíteni. Más rendszeren a csomag a
rendszerre telepített ffmpeg-et és Deno-t használja.

    python build.py             # dist/Media Minds Downloader/ (mappa, gyors indulás)
    python build.py --onefile   # dist/Media Minds Downloader.exe (egyetlen fájl, lassabb indulás)
"""

from __future__ import annotations

import argparse
import io
import os
import re
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

import PyInstaller.__main__

from ytletolto import APP_NAME
from ytletolto._build import REPOSITORY, VERSION
from ytletolto.updater import version_tuple

ROOT = Path(__file__).resolve().parent
VENDOR = ROOT / "vendor"

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


def windows_version_file(version: str) -> Path:
    """Set the PE metadata required by the release signing policy."""
    parts = version_tuple(version)
    if any(part > 65535 for part in parts):
        raise ValueError("A Windows-verzió részei legfeljebb 65535 értékűek lehetnek.")
    normalized = ".".join(map(str, parts))
    fixed_version = (*parts, 0)
    strings = {
        "CompanyName": "Media Minds",
        "FileDescription": APP_NAME,
        "FileVersion": normalized,
        "InternalName": APP_NAME,
        "OriginalFilename": f"{APP_NAME}.exe",
        "ProductName": APP_NAME,
        "ProductVersion": normalized,
    }
    entries = ",\n".join(f"        StringStruct({key!r}, {value!r})" for key, value in strings.items())
    path = ROOT / "build" / "windows-version.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "VSVersionInfo(\n"
        f"  ffi=FixedFileInfo(filevers={fixed_version!r}, prodvers={fixed_version!r},\n"
        "    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),\n"
        "  kids=[StringFileInfo([StringTable('040904B0', [\n"
        f"{entries}\n"
        "  ])]), VarFileInfo([VarStruct('Translation', [1033, 1200])])]\n"
        ")\n",
        encoding="utf-8",
    )
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--onefile", action="store_true", help="egyetlen .exe a mappa helyett")
    parser.add_argument("--no-fetch", action="store_true", help="ne töltse le az ffmpeg-et és a Deno-t")
    parser.add_argument("--version", default=os.environ.get("GITHUB_REF_NAME", VERSION), help="kiadási verzió (X.Y.Z vagy vX.Y.Z)")
    args = parser.parse_args()
    version_tuple(args.version)
    repository = os.environ.get("GITHUB_REPOSITORY", REPOSITORY)
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        parser.error("Érvénytelen GitHub repository.")

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
        "--add-data", f"{ROOT / 'ytletolto' / 'install_update.ps1'}{os.pathsep}ytletolto",
        "--distpath", str(ROOT / "dist"),
        "--workpath", str(ROOT / "build"),
        "--specpath", str(ROOT / "build"),
    ]
    if sys.platform == "win32":
        pyinstaller_args += ["--version-file", str(windows_version_file(args.version))]
    icon = ROOT / "assets" / ("icon.ico" if sys.platform == "win32" else "icon.png")
    if sys.platform == "darwin":
        pyinstaller_args += ["--osx-bundle-identifier", "hu.mediaminds.downloader"]
    if icon.is_file():
        pyinstaller_args += ["--icon", str(icon)]
    for binary in vendor_binaries():
        pyinstaller_args += ["--add-binary", binary]

    metadata = ROOT / "ytletolto" / "_build.py"
    original = metadata.read_bytes()
    try:
        metadata.write_text(
            f"VERSION = {args.version.removeprefix('v')!r}\n"
            f"FLAVOR = {'onefile' if args.onefile else 'onedir'!r}\n"
            f"REPOSITORY = {repository!r}\n", encoding="utf-8",
        )
        PyInstaller.__main__.run(pyinstaller_args)
    finally:
        metadata.write_bytes(original)


if __name__ == "__main__":
    main()
