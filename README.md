# YT Letöltő

Asztali alkalmazás YouTube-videók letöltéséhez **MP4 videóként** vagy **MP3 hangként**, a lehető legjobb minőségben.
Nem kell hozzá szerver: egyetlen program, ami a gépeden fut.

- **Videó (MP4)**: a legjobb elérhető képminőség (akár 4K/60 fps) a legjobb hangsávval összefűzve.
  Választható felbontáskorlát (2160p…480p).
- **Kompatibilis mód**: H.264 + AAC, ami minden lejátszón és tévén megy, de a YouTube-on legfeljebb 1080p.
  Kapcsold be, ha egy régebbi lejátszó nem játssza le a legjobb minőségű (VP9/AV1) fájlt.
- **Csak hang (MP3)**: a legjobb hangsávból 320 kbps MP3, borítóképpel és metaadatokkal (cím, előadó).
- Lejátszási lista letöltése (opcionális), folyamatjelző, megszakítás.

## Használat Windows-on

Töltsd le a [Releases](../../releases) oldalról (vagy a legutóbbi *Windows build* futás artifactjai közül):

- `YTLetolto-windows.zip`: csomagold ki, és indítsd a `YTLetolto\YTLetolto.exe`-t. **Ez indul gyorsabban.**
- `YTLetolto.exe`: egyetlen fájl, de minden indításkor kicsomagolja magát, ezért pár másodperccel lassabban indul.

Az ffmpeg és a Deno benne van a csomagban, semmit nem kell külön telepíteni.
Mivel a program nincs digitálisan aláírva, a Windows SmartScreen első indításkor figyelmeztethet:
*További információ → Futtatás mindenképp*.

## Fejlesztés

Python 3.10+ szükséges (tkinter-rel), valamint `ffmpeg` és `deno` a PATH-on.

```sh
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt   # Windows: .venv\Scripts\pip
.venv/bin/python main.py
.venv/bin/python -m pytest
```

macOS-en: `brew install python-tk@3.14 ffmpeg deno`.

## Futtatható állomány készítése

```sh
python build.py             # dist/YTLetolto/ mappa
python build.py --onefile   # dist/YTLetolto.exe egyetlen fájlként
```

Windows-on a `build.py` automatikusan letölti az ffmpeg-et és a Deno-t a `vendor/` mappába, és beépíti őket.
A PyInstaller nem tud keresztfordítani, ezért Windows-os `.exe` csak Windows-on készülhet. Erre való a
`.github/workflows/build-windows.yml`: minden `main`-re pusholáskor felépíti, `v*` tagnél Release-t is készít.

## Hogyan működik

- [yt-dlp](https://github.com/yt-dlp/yt-dlp) végzi a letöltést; az ffmpeg fűzi össze a videót a hanggal, és ez készíti az MP3-at.
- A YouTube-hoz a yt-dlp-nek JavaScript futtatókörnyezet (Deno) kell, enélkül csak korlátozott formátumok érhetők el.
- Ha a letöltés egy napon hirtelen elromlik, általában a YouTube változott: frissítsd a yt-dlp-t
  (`pip install -U "yt-dlp[default]"`), és építsd újra a programot.

Csak olyan tartalmat tölts le, amihez jogod van.
