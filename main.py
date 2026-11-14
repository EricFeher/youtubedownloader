"""Belépési pont – a PyInstaller is ezt a fájlt csomagolja.

`--check`: grafikus felület nélkül ellenőrzi, hogy az ffmpeg és a JS futtatókörnyezet
megtalálható-e (a build ellenőrzéséhez). Kilépési kód: 0 = rendben, 1 = hiányzik valami.
"""

import sys


def check() -> int:
    from ytletolto.downloader import find_tools

    tools = find_tools()
    ok = bool(tools.ffmpeg_dir and tools.js_runtimes)
    report = f"ffmpeg: {tools.ffmpeg_dir}\njs: {tools.js_runtimes}\n{'OK' if ok else 'HIÁNYZIK'}\n"
    # Ablakos (--windowed) Windows-buildben nincs stdout, ezért fájlba is írjuk.
    if len(sys.argv) > 2:
        with open(sys.argv[2], "w", encoding="utf-8") as f:
            f.write(report)
    elif sys.stdout:
        print(report, end="")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--check" in sys.argv[1:2]:
        sys.exit(check())

    from ytletolto.gui import main

    main()
