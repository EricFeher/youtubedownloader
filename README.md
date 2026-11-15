# Media Minds Downloader

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
- Lejátszási lista letöltése: pipával kijelölhetők a letöltendő elemek, és elemenként választható, hogy **videó** (alapértelmezett)
  vagy **csak hang** legyen belőle; „Mind videó” / „Mind hang” gombbal egyszerre is átállítható. A fájlok a lista
  nevű mappába kerülnek, az eredeti sorszámukkal. Listához tartozó videó linkjénél a „Teljes lejátszási lista”
  kapcsolóval érhető el.
- **Részlet letöltése**: a videó elejét és végét egy kétfogantyús csúszkán jelölheted ki; a zöld sáv mutatja
  a letöltendő részt. A fogantyúk a nyílbillentyűkkel másodpercenként, Shift + nyíllal 10 másodpercenként
  mozgathatók; a „Teljes videó” visszaállítja az egész felvételt. Videónál és csak hangnál is működik.
- **Playlist szerkesztése**: kattints a lista egyik videójára. A lista alatti közös szerkesztőben annak
  adatai, minősége, formátuma és időtartománya jelenik meg; a választásokat videónként megőrzi.
  A pipa ettől függetlenül a letöltésbe kerülő elemeket jelöli. Az egyforma beállítású elemek közös
  letöltési menetbe kerülnek, és megtartják a playlist mappáját és eredeti sorszámait.
  A kivágott fájl nevében a kezdő- és végidő is szerepel.
  A pontos videóvágás újrakódolással jár (MP4/MKV: H.264 + AAC; WebM: VP9 + Opus), ezért több időt
  igényelhet. Részletletöltésnél a folyamatjelző a feldolgozás végét várja; a Megszakítás az ffmpeg-et is leállítja.
  Élő adásnál és ismeretlen hosszúságú videónál nincs csúszka.
- Folyamatjelző sebességgel és hátralévő idővel, megszakítás.
- Megjegyzi a mentési mappát és az utoljára választott beállításokat.
- **Alkalmazásfrissítés**: induláskor és óránként ellenőrzi a GitHub legújabb stabil kiadását.
  Új verziónál zöld értesítés jelenik meg. A lábléc **Frissítések és újdonságok** gombjával bármikor
  ellenőrizhetsz, és az alkalmazásban elolvashatod a kiadási megjegyzéseket (patch notes).
  A csomagolt Windows-változatokban a **Frissítés letöltése**, majd az **Újraindítás és frissítés**
  gombbal telepíthetsz; a beállítások és a letöltött videók megmaradnak. Az újraindítás a letöltési sor
  befejezése után érhető el. A hálózati hibák újrapróbálhatók, a videóletöltést nem akadályozzák.
- A MediaMinds arculatában készült: sötét felület, zöld színátmenet, Outfit betűtípus és MediaMinds logó.

## Használat Windows-on

Töltsd le a [Releases](../../releases) oldalról (vagy a legutóbbi *Windows build* futás artifactjai közül):

- `MediaMindsDownloader-windows.zip`: csomagold ki, és indítsd a `Media Minds Downloader\Media Minds Downloader.exe`-t. **Ez indul gyorsabban.**
- `Media.Minds.Downloader.exe`: egyetlen fájl, de minden indításkor kicsomagolja magát, ezért pár másodperccel lassabban indul.

Az ffmpeg és a Deno benne van a csomagban, semmit nem kell külön telepíteni. A felülethez a Microsoft Edge
WebView2 kell, ami Windows 11-en és a frissített Windows 10-eken már gyárilag fent van.
A korábbi, aláíratlan kiadásoknál a Windows SmartScreen figyelmeztethet. Az aláírással készülő
kiadásoknál is megjelenhet figyelmeztetés, amíg a program és a kiadó megfelelő reputációt nem szerez.
A digitális aláírás az EXE **Tulajdonságok → Digitális aláírások** lapján ellenőrizhető.

Az alkalmazáson belüli frissítéshez a program mappájának írhatónak kell lennie (például a saját
Letöltések mappádban). A ZIP-es változat ZIP-es, az egyfájlos változat EXE-s kiadással frissül.
A régi, frissítő nélküli kiadást egyszer még kézzel kell lecserélni az első, frissítőt tartalmazó verzióra.
Fejlesztői futtatásnál és macOS-en a verzióellenőrzés és a kiadási megjegyzések érhetők el.

## Fejlesztés

Python 3.10+ szükséges, valamint `ffmpeg` és `deno` a PATH-on.

```sh
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt   # Windows: .venv\Scripts\pip
.venv/bin/python -m playwright install chromium
.venv/bin/python main.py
.venv/bin/python -m pytest
```

macOS-en: `brew install ffmpeg deno`.

## Futtatható állomány készítése

```sh
python build.py             # dist/Media Minds Downloader/ mappa
python build.py --onefile   # dist/Media Minds Downloader.exe egyetlen fájlként
```

macOS-en a build a `dist/Media Minds Downloader.app` alkalmazást is elkészíti:

```sh
open "dist/Media Minds Downloader.app"
```

Finderből indítva is megtalálja a Homebrew-val telepített ffmpeg-et és Denót.

Windows-on a `build.py` automatikusan letölti az ffmpeg-et és a Deno-t a `vendor/` mappába, és beépíti őket.
A PyInstaller nem tud keresztfordítani, ezért Windows-os `.exe` csak Windows-on készülhet. Erre való a
`.github/workflows/build-windows.yml`: csak `v*` tag pusholásakor indul. Lefuttatja a teszteket,
felépíti és ellenőrzi a Windows-csomagokat, majd a taghez GitHub Release-t készít a ZIP-pel és az EXE-vel.
A kiadás előtt mindkét saját EXE-t a SignPath szolgáltatással aláírja, majd ellenőrzi az aláírást
és az időbélyeget. Hiányzó konfiguráció vagy sikertelen aláírás esetén nem tesz közzé release-t.
Az éles aláíráshoz előbb el kell végezni a [Windows-aláírás beállítását](docs/windows-signing.md).
Az alkalmazás verzióját és frissítési forrását a build a tagből (`vX.Y.Z`) és a GitHub repositoryból
írja a csomagba; helyi buildnél a `python build.py --version 1.1.0` kapcsolóval adható meg.
Forrásból futtatva az alapverziót a `ytletolto/_build.py` tárolja.

A workflow automatikus kiadási megjegyzéseket készít. A GitHub Release leírását szerkesztve saját,
például magyar patch notes adható meg; az alkalmazás ezt jeleníti meg szövegként. A frissítő csak
közzétett, stabil kiadást telepít, a megfelelő asset GitHub által megadott SHA-256 lenyomatával.
Hiányzó vagy eltérő lenyomat esetén nem cseréli le a programot. A segédfolyamat kilépés után cseréli
az EXE-t és ZIP-es kiadásnál az `_internal` mappát, hiba esetén visszaállítja a mentett fájlokat.
Más, a program mellé mentett fájlokhoz nem nyúl. A sikertelen telepítés részleteit a program mappáján
belüli `.mm-update-*/update-error.txt` őrzi. Ez hordozható csomagfrissítés: az új csomagot tölti le,
nem különbségi javítócsomagot. Nincs külön frissítőszerver vagy hozzáférési token.

Új verzió kiadásához a kiadandó `main` commiton (például a frissítőt bevezető kiadásnál):

```sh
git tag v1.1.0
git push origin v1.1.0
```

## Code signing policy

Az aláírási integráció elő van készítve; a SignPath-fiók és az éles aláírás engedélyezése külön
beállítást igényel. A szolgáltatói jóváhagyásig a projekt nem állítja, hogy SignPath Foundation
tanúsítvánnyal rendelkezik. A beállítás, a jogosultságok és a kiadási ellenőrzések részletei:
[Windows-aláírás](docs/windows-signing.md).

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
