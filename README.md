# YT Letöltő

Asztali alkalmazás YouTube-videók letöltéséhez **videóként** (MP4, MKV vagy WebM) vagy **hangként** (MP3, M4A, Opus vagy WAV), a lehető legjobb minőségben.
Nem kell hozzá szerver: egyetlen program, ami a gépeden fut, de a felülete egy modern weboldalt idéz.

- **Videó (MP4)**: a legjobb elérhető képminőség (akár 4K/60 fps) a legjobb hangsávval összefűzve.
  Választható felbontáskorlát (2160p…480p).
- **Videó fájlformátum**: MP4 (alapértelmezett, mindenhol lejátszható), MKV (bármilyen kodek, a legjobb
  Opus hangsávval) vagy WebM (VP9/AV1 + Opus; ha egy videónál nincs ilyen sáv, MKV lesz belőle, borítókép nélkül).
- **Kompatibilis mód**: H.264 + AAC, ami minden lejátszón és tévén megy, de a YouTube-on legfeljebb 1080p.
  Kapcsold be, ha egy régebbi lejátszó nem játssza le a legjobb minőségű (VP9/AV1) fájlt.
- **Csak hang**: borítóképpel és metaadatokkal (cím, előadó).
  - **MP3** (alapértelmezett): 320 kbps, mindenhol lejátszható.
  - **M4A** és **Opus**: a YouTube eredeti AAC, illetve Opus sávja újrakódolás nélkül, tehát minőségvesztés nélkül.
    Az Opus a legjobb elérhető hangminőség.
  - **WAV**: tömörítetlen, vágó- és DJ-programokhoz, borítókép nélkül. Nem szól jobban a forrásnál, csak nagyobb.
- Link beillesztése után előnézet: borítókép, cím, csatorna, hossz és a legjobb elérhető felbontás.
- **Letöltési sor**: letöltés közben is hozzáadhatsz újabb linkeket, a program egymás után tölti le őket.
  Egyszerre több linket is beilleszthetsz (pl. soronként egyet), ezek egy kattintással a sorba kerülnek.
  Minden elemnek saját folyamatjelzője van, a futó letöltés megszakítható, a sikertelen újrapróbálható.
  Ugyanaz a link ugyanabban a formátumban nem kerül kétszer a sorba.
- Lejátszási lista letöltése, folyamatjelző sebességgel és hátralévő idővel.
- Megjegyzi a mentési mappát és az utoljára választott beállításokat.
- A MediaMinds arculatában készült: sötét felület, zöld színátmenet, Outfit betűtípus és MediaMinds logó.

## Használat Windows-on

Töltsd le a [Releases](../../releases) oldalról (vagy a legutóbbi *Windows build* futás artifactjai közül):

- `YTLetolto-windows.zip`: csomagold ki, és indítsd a `YTLetolto\YTLetolto.exe`-t. **Ez indul gyorsabban.**
- `YTLetolto.exe`: egyetlen fájl, de minden indításkor kicsomagolja magát, ezért pár másodperccel lassabban indul.

Az ffmpeg és a Deno benne van a csomagban, semmit nem kell külön telepíteni. A felülethez a Microsoft Edge
WebView2 kell, ami Windows 11-en és a frissített Windows 10-eken már gyárilag fent van.
Mivel a program nincs digitálisan aláírva, a Windows SmartScreen első indításkor figyelmeztethet:
*További információ → Futtatás mindenképp*.

## Fejlesztés

Python 3.10+ szükséges, valamint `ffmpeg` és `deno` a PATH-on.

```sh
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt   # Windows: .venv\Scripts\pip
.venv/bin/python main.py
.venv/bin/python -m pytest
```

macOS-en: `brew install ffmpeg deno`.

## Futtatható állomány készítése

```sh
python build.py             # dist/YTLetolto/ mappa
python build.py --onefile   # dist/YTLetolto.exe egyetlen fájlként
```

Windows-on a `build.py` automatikusan letölti az ffmpeg-et és a Deno-t a `vendor/` mappába, és beépíti őket.
A PyInstaller nem tud keresztfordítani, ezért Windows-os `.exe` csak Windows-on készülhet. Erre való a
`.github/workflows/build-windows.yml`: minden `main`-re pusholáskor felépíti, `v*` tagnél Release-t is készít.

## Hogyan működik

- A felület sima HTML/CSS/JS (`ytletolto/web/`), amit a [pywebview](https://pywebview.flowrl.com/) a rendszer saját
  böngészőmotorjával jelenít meg egy natív ablakban (Windows: Edge WebView2, macOS: WebKit). A JS a
  `window.pywebview.api`-n keresztül hívja a Python `Api` osztályát (`ytletolto/app.py`). Hosztolt
  backend nem kell, minden a gépeden fut.
- A betűtípus (Outfit, SIL Open Font License) a csomagban van (`ytletolto/web/fonts/`), így internet nélkül is
  ugyanúgy néz ki.
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) végzi a letöltést; az ffmpeg fűzi össze a videót a hanggal, és ez készíti az MP3-at.
- A YouTube-hoz a yt-dlp-nek JavaScript futtatókörnyezet (Deno) kell, enélkül csak korlátozott formátumok érhetők el.
- Ha a letöltés egy napon hirtelen elromlik, általában a YouTube változott: frissítsd a yt-dlp-t
  (`pip install -U "yt-dlp[default]"`), és építsd újra a programot.

Csak olyan tartalmat tölts le, amihez jogod van.
