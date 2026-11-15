# Windows-kiadások digitális aláírása

A Windows workflow a SignPath GitHub Actions integrációját használja. Aláírásra kizárólag a
projekt két saját EXE-jét küldi el; az ffmpeg, a Deno és más beszállítói binárisok nem kapnak
a projekt nevében új aláírást. A ZIP-be már az aláírt alkalmazás kerül. A fájlnevek és a csomag
szerkezete változatlan, ezért az alkalmazáson belüli frissítés továbbra is ugyanazokat az
asseteket használja.

**Állapot:** az integráció önmagában nem jelent működő éles tanúsítványt. A szolgáltatói fiók,
a jóváhagyott signing policy és az alábbi GitHub-beállítások szükségesek. Ezek hiányában a
tagre induló workflow hibával leáll; nincs automatikus visszaesés aláíratlan release-re.
A helyi `python build.py` továbbra is aláíratlan fejlesztői buildet készít.

## 1. SignPath-hozzáférés

- Meglévő SignPath-előfizetés és saját tanúsítvány is használható.
- Ingyenes aláíráshoz a [SignPath Foundationnél kell jelentkezni](https://signpath.org/apply).
  A [feltételeik](https://signpath.org/terms) többek között OSI által elfogadott nyílt forrású
  licencet, karbantartott és már kiadott projektet, MFA-t és kiadásonként kézi aláírás-jóváhagyást
  írnak elő. Az elfogadás nem automatikus. A repó jelenleg nem tartalmaz projektlicencet;
  ennek kiválasztása és a forráskód jogosultjainak hozzájárulása külön döntés.
- A Foundation elfogadása után ki kell egészíteni a README **Code signing policy** részét
  az általuk kért szolgáltatói hivatkozásokkal, a committers/reviewers/approvers szerepkörök
  tényleges tagjaival, valamint a program valós hálózati működését leíró adatvédelmi tájékoztatóval.
  A program automatikusan GitHub-frissítéseket is ellenőriz, ezért nem helyes azt állítani,
  hogy kizárólag külön felhasználói kérésre létesít hálózati kapcsolatot.

Ne generálj saját aláírású éles tanúsítványt ehhez: azt a letöltők Windows-rendszere nem fogja
automatikusan megbízhatónak tekinteni. Privát kulcsot és tanúsítványjelszót ne tegyél a repóba.

## 2. SignPath-projekt és aláírási szabály

1. Hozz létre projektet a SignPathban, és kösd az `EricFeher/youtubedownloader` GitHub-repóhoz.
   Engedélyezd a GitHub.com Trusted Build System integrációt és a SignPath GitHub App hozzáférését
   ehhez a repóhoz a [SignPath útmutatója](https://docs.signpath.io/trusted-build-systems/github) szerint.
2. Hozz létre artifact configurationt a
   [`.github/signpath/artifact-configuration.xml`](../.github/signpath/artifact-configuration.xml)
   tartalmával. A fájl repóba helyezése nem importálja automatikusan a SignPathba.
   A gyökér egy GitHub Actions által készített ZIP, azon belül pontosan a két saját EXE van.
   Az XML a terméknevet és a kiadás verzióját is ellenőrzi.
3. Hozz létre **éles, Windows által megbízhatónak tekintett** Authenticode-tanúsítványt használó
   signing policyt. Engedélyezd az időbélyegzést. Teszttanúsítvánnyal a kiadás ellenőrzése elbukik.
   A forrásellenőrzési szabályokat korlátozd erre a repóra, a Windows workflow-ra és a kiadási tagekre.
4. Állítsd be a jogosult aláírás-jóváhagyókat; az API-token csak a szükséges submitter jogot kapja.

## 3. GitHub Actions-beállítások

A repó **Settings → Secrets and variables → Actions** oldalán:

| Típus | Név | Érték |
| --- | --- | --- |
| Secret | `SIGNPATH_API_TOKEN` | A SignPath submitter API-tokenje |
| Variable | `SIGNPATH_ORGANIZATION_ID` | A SignPath-szervezet azonosítója |
| Variable | `SIGNPATH_PROJECT_SLUG` | A SignPath-projekt slugja |
| Variable | `SIGNPATH_SIGNING_POLICY_SLUG` | Az éles signing policy slugja |
| Variable | `SIGNPATH_ARTIFACT_CONFIGURATION_SLUG` | Az importált artifact configuration slugja |

A tokent közvetlenül GitHub Secretként add meg, ne chatben és ne forrásfájlban.
Magántulajdonú repónál a SignPath-csomag előfizetési és hozzáférési feltételeit is ellenőrizni kell.

## 4. Egy kiadás menete és ellenőrzése

1. A szokásos `vX.Y.Z` tag indítja a workflow-t. A tesztek után elkészül mindkét Windows-build,
   az EXE-k PE-verzióadataiban ugyanazzal a terméknévvel és verzióval.
2. A két EXE `unsigned-windows-executables` néven ideiglenes GitHub Actions artifactba kerül
   egy napos megőrzéssel. Ez a SignPath eredetellenőrzéséhez kell; nem release asset.
3. A workflow elküldi az artifact azonosítóját a SignPathnak, és legfeljebb két órát vár az aláírásra.
   Ha kézi jóváhagyás szükséges, azt a SignPathban kell megadni. Az időkeret túllépése vagy
   elutasítás hibával leállítja a kiadást.
4. A letöltött eredmény mindkét EXE-jén kötelező az érvényes, beágyazott Authenticode-aláírás,
   az időbélyeg és az azonos aláíró tanúsítvány. Csak ezután cseréli le a workflow a build EXE-it,
   futtatja a csomagolt eszközök ellenőrzését, és készíti el a ZIP-et.
5. A ZIP készítése előtt ismét ellenőrzi a kiadandó EXE-k aláírását. A végleges artifact és
   a GitHub Release kizárólag ezekből a fájlokból készül. Az aláírás után ne módosítsd az EXE-ket.

Helyi ellenőrzés Windows PowerShellből, a két EXE-t tartalmazó `dist` könyvtárra:

```powershell
./scripts/verify-windows-signatures.ps1 -Root dist
```

Az aláírás a kiadó kilétét és a fájl sértetlenségét igazolja. Nem garantálja a SmartScreen-jelzés
azonnali megszűnését; az új kiadónak és az új fájloknak reputációt kell szerezniük.
Lásd a [Microsoft SmartScreen-dokumentációját](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation).
