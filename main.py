"""Belépési pont – a PyInstaller is ezt a fájlt csomagolja.

`--check`: ablak nyitása nélkül ellenőrzi, hogy az ffmpeg, a JS futtatókörnyezet és a
felület motorja megtalálható-e (a build ellenőrzéséhez). Kilépési kód: 0 = rendben, 1 = hiányzik valami.
"""

import sys


def check() -> int:
    from pathlib import Path

    from ytletolto import updater
    from ytletolto.downloader import find_tools

    tools = find_tools()
    updater.version_tuple(updater.VERSION)
    update_ok = (Path(updater.__file__).parent / "install_update.ps1").is_file()
    if getattr(sys, "frozen", False):
        update_ok = update_ok and updater.FLAVOR in updater.ASSETS
    try:
        # A felület motorja is betölthető-e (Windows-on: pythonnet + WebView2 DLL-ek).
        from ytletolto.app import WEB_DIR
        from webview.guilib import initialize

        initialize()
        ui = "OK" if (WEB_DIR / "index.html").is_file() else "HIBA: hiányzik a web mappa"
    except Exception as e:  # noqa: BLE001
        ui = f"HIBA: {e}"
    ok = bool(tools.ffmpeg_dir and tools.js_runtimes) and ui == "OK" and update_ok
    report = (f"ffmpeg: {tools.ffmpeg_dir}\njs: {tools.js_runtimes}\nui: {ui}\n"
              f"version: {updater.VERSION}\npackage: {updater.FLAVOR}\nupdater: {'OK' if update_ok else 'HIÁNYZIK'}\n"
              f"{'OK' if ok else 'HIÁNYZIK'}\n")
    # Ablakos (--windowed) Windows-buildben nincs stdout, ezért fájlba is írjuk.
    if len(sys.argv) > 2:
        with open(sys.argv[2], "w", encoding="utf-8") as f:
            f.write(report)
    elif sys.stdout:
        print(report, end="")
    return 0 if ok else 1


if __name__ == "__main__":
    import multiprocessing

    multiprocessing.freeze_support()
    if "--check" in sys.argv[1:2]:
        sys.exit(check())

    from ytletolto.app import main

    main()
