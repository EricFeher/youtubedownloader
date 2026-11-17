# Media Minds Downloader

Desktop application for downloading YouTube videos as **video** (MP4, MKV, or WebM) or **audio** (MP3, M4A, Opus, or WAV) at the best available quality.
No server required: a single application running on your computer, with the look and feel of a modern website.

- **Video (MP4)**: the best available video quality (up to 4K/60 fps), merged with the best audio track.
  An optional resolution limit is available (2160p–480p).
- **Video file format**: MP4 (default, widely supported), MKV (supports any codec, with the best
  Opus audio track), or WebM (VP9/AV1 + Opus; falls back to MKV when those streams are unavailable, without cover art).
- **Compatibility mode**: H.264 + AAC for broad player and TV support, limited to 1080p on YouTube.
  Enable it if an older player cannot play the highest-quality VP9/AV1 file.
- **Audio only**: includes cover art and metadata (title and artist).
  - **MP3** (default): 320 kbps, with broad playback support.
  - **M4A** and **Opus**: YouTube's original AAC and Opus tracks, respectively, without re-encoding or additional quality loss.
    Opus provides the best available audio quality.
  - **WAV**: uncompressed audio for editing and DJ software, without cover art. It does not sound better than the source; it is simply larger.
- Paste a link to preview its thumbnail, title, channel, duration, and highest available resolution.
- **Download queue**: add more links while a download is running; the application downloads them sequentially.
  Paste multiple links at once (for example, one per line) and add them to the queue with one click.
  Each item has its own progress indicator. Running downloads can be cancelled, and failed downloads can be retried.
  The same link with identical download settings is not added again while it is queued or running.
- **Playlist downloads**: use checkboxes to select items and choose **video** (default) or **audio only**
  for each one. The all-video and all-audio buttons change every item's mode at once. Files are saved in a folder
  named after the playlist, retaining their original positions. For a video link that belongs to a playlist,
  enable the full-playlist option to access these controls.
- **Clip downloads**: select the start and end using a slider with two handles; the green bar shows the portion
  to download. Arrow keys move a handle by one second, or by ten seconds with Shift held down.
  The full-video button resets the selection. Works for both video and audio-only downloads.
  A floating thumbnail appears above the timeline while hovering, dragging either handle, or using the keyboard,
  including in the playlist editor. The preview follows the pointer or active handle and hides when you finish.
  These use YouTube's sampled timeline images and show an approximate preview time, not an exact frame.
  If timeline images are unavailable or cannot load, time selection still works normally.
- **Playlist editing**: click a video in the playlist to show its details, quality, format, and time range in
  the shared editor below the list. Settings are preserved for each video. Checkboxes independently control
  which items are included in the download. Items with identical settings are grouped into a single download
  run, retaining the playlist folder and original positions.
  Clip filenames include the start and end times.
  Accurate video trimming requires re-encoding (MP4/MKV: H.264 + AAC; WebM: VP9 + Opus), which can take longer.
  For clip downloads, the progress indicator waits for processing to finish; cancellation also stops ffmpeg.
  The slider is unavailable for live streams and videos with an unknown duration.
- Progress indicators show download speed and estimated time remaining, with cancellation support.
- Remembers the output folder and your most recently selected settings.
- **Hungarian and English interface**: switch instantly using the **Language** selector below the header.
  The application remembers your choice. Switching languages preserves the download queue, playlist selections, and video settings.
- **Application updates**: checks GitHub for the latest stable release at startup and every hour.
  A green notification appears when a new version is available. Use the updates button in the footer to check
  manually and read release notes inside the application.
  Packaged Windows builds let you download the update, then restart the application to install it.
  Settings and downloaded videos are preserved. Restarting to update is available after the download queue
  finishes. Network failures can be retried and do not block video downloads.
- MediaMinds branding: a dark interface, green gradients, the Outfit typeface, and the MediaMinds logo.

## Using the application on Windows

Download a package from [Releases](../../releases), or from the artifacts of the latest *Windows build* workflow run:

- `MediaMindsDownloader-windows.zip`: extract it and launch `Media Minds Downloader\Media Minds Downloader.exe`. **This version starts faster.**
- `Media.Minds.Downloader.exe`: a single executable that extracts itself on every launch, so startup takes a few seconds longer.

ffmpeg and Deno are bundled, so you do not need to install them separately. The interface requires Microsoft Edge
WebView2, which is included with Windows 11 and updated Windows 10 installations.
The application is not digitally signed, so Windows SmartScreen may display a warning on first launch:
*More info → Run anyway*.

In-app updates require a writable application directory, such as a folder inside your Downloads directory.
The ZIP version updates from ZIP releases, and the single-file version updates from EXE releases.
Older versions without an updater must be replaced manually once with a version that includes it.
When running from source or on macOS, version checks and release notes are available.

## Development

Requires Python 3.10+, with `ffmpeg` and `deno` on your PATH.

```sh
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt   # Windows: .venv\Scripts\pip
.venv/bin/python -m playwright install chromium
.venv/bin/python main.py
.venv/bin/python -m pytest
```

On Windows, use `.venv\Scripts\python` in place of `.venv/bin/python` in the commands above.

On macOS: `brew install ffmpeg deno`.

### Translations

The shared text catalogs are `ytletolto/web/locales/en.json` and `hu.json`.
English is the source language and fallback for missing translations; keys are independent of their wording.
In JavaScript, use `t(TEXT.PASTE)` or `setText(node, TEXT.DOWNLOAD_ITEMS, {count: 2})`.
In HTML, use `data-i18n="PASTE"`, or `data-i18n-aria-label="LANGUAGE"` for attributes.
Python uses the same keys through `ytletolto.i18n.TEXT`, for example
`Message(TEXT.UNEXPECTED_ERROR, error=str(exc))`. The UI receives the key and parameters,
so status messages can be translated again while downloads are running. Add new text to both catalogs;
English plural forms can use `one` and `other`.
On first launch, the system display language is used; unsupported languages fall back to English.
The `language: "system"` setting follows the system, while explicit `hu` and `en` choices are remembered.
Video titles, filenames, external technical logs, and publisher-written release notes retain their source language.

## Building an executable

```sh
python build.py             # dist/Media Minds Downloader/ directory
python build.py --onefile   # dist/Media Minds Downloader.exe as a single file
```

On macOS, the build also creates the `dist/Media Minds Downloader.app` application:

```sh
open "dist/Media Minds Downloader.app"
```

The application finds Homebrew-installed ffmpeg and Deno even when launched from Finder.

On Windows, `build.py` automatically downloads ffmpeg and Deno into `vendor/` and bundles them.
PyInstaller does not support cross-compilation, so Windows executables must be built on Windows.
The `.github/workflows/build-windows.yml` workflow handles this: it runs only when a `v*` tag is pushed,
runs the tests, builds and checks the Windows packages, and creates a GitHub Release for the tag with the ZIP and EXE.
The build embeds the application version and update source using the tag (`vX.Y.Z`) and GitHub repository.
For a local build, specify the version with `python build.py --version 1.1.0`.
When running from source, the default version is stored in `ytletolto/_build.py`.

The workflow generates release notes automatically. Edit the GitHub Release description to provide custom
release notes; the application displays them as plain text. The updater installs only published, stable releases
and verifies the selected asset against the SHA-256 digest supplied by GitHub.
If the digest is missing or does not match, the application is not replaced. After the application exits,
a helper process replaces the EXE and, for ZIP releases, the `_internal` directory. If installation fails,
it attempts to restore the backed-up files.
Other files stored alongside the application are left untouched. Installation failure details are saved in
`.mm-update-*/update-error.txt` inside the application directory. Updates replace the portable application package:
the full new package is downloaded, rather than a differential patch. No separate update server or access token is required.

To publish a new version, create and push a tag on the `main` commit you want to release. For example:

```sh
git tag v1.1.0
git push origin v1.1.0
```

## How it works

- The interface uses plain HTML/CSS/JS (`ytletolto/web/`), displayed in a native window by
  [pywebview](https://pywebview.flowrl.com/) using the system's browser engine (Edge WebView2 on Windows,
  WebKit on macOS). JavaScript calls the Python `Api` class (`ytletolto/app.py`) through `window.pywebview.api`.
  Everything runs locally; no hosted backend is required.
- The Outfit typeface, licensed under the SIL Open Font License, is bundled in `ytletolto/web/fonts/`,
  so the interface looks the same offline.
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) handles downloads; ffmpeg merges video and audio and creates MP3 files.
- For YouTube, yt-dlp needs a JavaScript runtime (Deno); without one, only a limited set of formats is available.
- If downloads suddenly stop working, YouTube may have changed. Update yt-dlp
  (`pip install -U "yt-dlp[default]"`) and rebuild the application.

Only download content you have the right to download.
