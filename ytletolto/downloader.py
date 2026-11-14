"""A letöltés magja: yt-dlp beállítások összeállítása és futtatása, GUI-tól függetlenül."""

from __future__ import annotations

import os
import re
import shutil
import sys
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path

import yt_dlp
from yt_dlp.utils import DownloadCancelled, DownloadError


class Mode(Enum):
    VIDEO = "video"  # MP4 / MKV / WebM
    AUDIO = "audio"  # MP3 / M4A / Opus / WAV


MP3_BITRATE = "320K"
# Fájlformátumok; az első az alapértelmezett.
VIDEO_CONTAINERS = ("mp4", "mkv", "webm")
AUDIO_FORMATS = ("mp3", "m4a", "opus", "wav")


@dataclass(frozen=True)
class DownloadRequest:
    url: str
    output_dir: Path
    mode: Mode
    max_height: int | None = None
    # H.264 + AAC: minden lejátszón megy, de a YouTube-on ez legfeljebb 1080p. WebM-nél nem értelmezett.
    compatible: bool = False
    container: str = VIDEO_CONTAINERS[0]
    audio_format: str = AUDIO_FORMATS[0]
    playlist: bool = False
    # A lista mely elemei (videóazonosítók); üres = mind. Azonosító szerint választunk, nem sorszám
    # szerint, így ha a lista az előnézet óta változott (pl. új feltöltés), akkor sem jön rossz videó.
    playlist_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class Tools:
    ffmpeg_dir: Path | None
    js_runtimes: dict[str, dict[str, str]] = field(default_factory=dict)


# --- Események a GUI felé -------------------------------------------------


@dataclass(frozen=True)
class Progress:
    percent: float | None
    speed: float | None  # bájt/s
    eta: int | None  # másodperc
    filename: str
    item: str  # pl. "2/15" lejátszási listánál, különben üres
    kind: str  # "video" | "audio" – melyik sáv töltődik épp
    mode: str = Mode.VIDEO.value  # a letöltés módja: videó vagy csak hang


@dataclass(frozen=True)
class Status:
    text: str


@dataclass(frozen=True)
class Log:
    text: str
    level: str = "info"  # info | warning | error


@dataclass(frozen=True)
class Finished:
    ok: bool
    message: str
    files: tuple[str, ...] = ()


Event = Progress | Status | Log | Finished


# --- Külső programok (ffmpeg, JS futtatókörnyezet) -------------------------


def bundled_dir() -> Path:
    """PyInstaller-es futtatáskor a kicsomagolt mappa, fejlesztéskor a repo `vendor/` mappája."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent / "vendor"


def _exe(name: str) -> str:
    return f"{name}.exe" if os.name == "nt" else name


def find_tools(base: Path | None = None) -> Tools:
    """Előbb a csomagolt binárisokat keresi, utána a PATH-on lévőket."""
    base = base or bundled_dir()

    def locate(name: str) -> Path | None:
        candidate = base / _exe(name)
        if candidate.is_file():
            return candidate
        found = shutil.which(name)
        return Path(found) if found else None

    ffmpeg = locate("ffmpeg")
    ffmpeg_dir = ffmpeg.parent if ffmpeg else None

    js_runtimes: dict[str, dict[str, str]] = {}
    if deno := locate("deno"):
        js_runtimes["deno"] = {"path": str(deno)}
    elif node := locate("node"):
        js_runtimes["node"] = {"path": str(node)}

    return Tools(ffmpeg_dir=ffmpeg_dir, js_runtimes=js_runtimes)


# --- yt-dlp beállítások ----------------------------------------------------


def build_cli_args(request: DownloadRequest, tools: Tools) -> list[str]:
    """yt-dlp parancssori kapcsolók; ezekből a yt-dlp saját parserje állítja elő a pontos API-beállításokat."""
    if request.playlist:
        template = "%(playlist_title|Lejátszási lista)s/%(playlist_index|0)03d - %(title)s.%(ext)s"
    else:
        template = "%(title)s.%(ext)s"

    args = [
        "--ignore-config",
        "--paths", str(request.output_dir),
        "--output", template,
        "--windows-filenames",
        "--embed-metadata",
        "--yes-playlist" if request.playlist else "--no-playlist",
    ]
    if tools.ffmpeg_dir:
        args += ["--ffmpeg-location", str(tools.ffmpeg_dir)]

    if request.mode is Mode.AUDIO:
        return args + _audio_args(request.audio_format)

    container = request.container
    if container not in VIDEO_CONTAINERS:
        raise ValueError(f"Ismeretlen videóformátum: {container}")
    compatible = request.compatible and container != "webm"  # H.264 nem fér WebM-be

    # A HDR-es sáv nem HDR-es kijelzőn fakón jelenik meg, ezért az SDR-t vesszük előre.
    sort = ["hdr:sdr"]
    if compatible:
        sort.append("vcodec:h264")
    if request.max_height:
        sort.append(f"res:{request.max_height}")
    args += ["--format-sort", ",".join(sort), "--embed-chapters"]

    if container == "webm":
        # Csak VP9/AV1 + Opus fér bele; ha egy videónál nincs ilyen, MKV lesz belőle, nem hiba.
        # Borítóképet a yt-dlp WebM-be nem tud beágyazni.
        args += [
            "--format", "bestvideo[ext=webm]+bestaudio[ext=webm]/bestvideo+bestaudio/best",
            "--merge-output-format", "webm/mkv",
            "--remux-video", "webm>webm/mkv",
        ]
    else:
        if container == "mp4" or compatible:
            # Az AAC hang mindenhol lejátszható, az Opus nem; minőségben alig van különbség.
            video_format = "bestvideo+bestaudio[acodec^=mp4a]/bestvideo+bestaudio/best"
        else:
            # MKV-be bármi belefér, így a legjobb hangsávot (általában Opus) vesszük.
            video_format = "bestvideo+bestaudio/best"
        args += [
            "--embed-thumbnail",
            "--format", video_format,
            "--merge-output-format", container,
            "--remux-video", container,
        ]
    return args


def _audio_args(audio_format: str) -> list[str]:
    if audio_format not in AUDIO_FORMATS:
        raise ValueError(f"Ismeretlen hangformátum: {audio_format}")

    # Az M4A (AAC) és az Opus sávot a YouTube eleve így adja: ha megvan, újrakódolás nélkül átmásoljuk.
    source = {
        "m4a": "bestaudio[ext=m4a]/bestaudio/best",
        "opus": "bestaudio[acodec=opus]/bestaudio/best",
    }.get(audio_format, "bestaudio/best")
    # MP3-nál fix bitráta; a többinél csak akkor számít, ha mégis át kell kódolni (0 = legjobb VBR).
    quality = MP3_BITRATE if audio_format == "mp3" else "0"

    args = ["--format", source, "--extract-audio", "--audio-format", audio_format, "--audio-quality", quality]
    if audio_format != "wav":  # WAV-ba a yt-dlp nem tud borítóképet tenni
        args.append("--embed-thumbnail")
    return args


def split_by_mode(request: DownloadRequest, items: object) -> list[DownloadRequest]:
    """Lejátszási listánál az elemenként választott mód szerint két kérésre bont: előbb a videók, aztán a hangok.

    `items`: `[{"id": "dQw4w9WgXcQ", "mode": "audio"}, …]`, csak a kijelölt elemek.
    Megadott elemeknél mindig azonosító alapján szűrünk, akkor is, ha mind ugyanabban a módban van.
    Ha nincs megadva, a teljes lista töltődik le.
    """
    if not request.playlist or not isinstance(items, list):
        return [request]
    chosen: dict[Mode, list[str]] = {Mode.VIDEO: [], Mode.AUDIO: []}
    for item in items:
        video_id = item.get("id") if isinstance(item, dict) else None
        if not isinstance(video_id, str) or not video_id:
            continue
        mode = Mode.AUDIO if item.get("mode") == Mode.AUDIO.value else Mode.VIDEO
        if video_id not in chosen[mode]:
            chosen[mode].append(video_id)
    groups = {mode: ids for mode, ids in chosen.items() if ids}
    return [replace(request, mode=mode, playlist_ids=tuple(ids)) for mode, ids in groups.items()]


def _select_ids(ids: tuple[str, ...]) -> Callable[..., str | None]:
    """yt-dlp `match_filter`: csak a megadott videókat engedi át, mindegyiket egyszer.

    A lapos listaelemre is lefut, mielőtt a yt-dlp lekérné a videó adatait, így a kihagyás olcsó.
    Csak önálló videókból álló listához való (lásd `_summarize_entries`).
    """
    wanted = set(ids)
    positions: dict[str, object] = {}  # azonosító → a letöltött előfordulás helye a listában

    def match(info: dict, *, incomplete: bool = False) -> str | None:
        video_id = info.get("id")
        if video_id is None:
            return None  # maga a lista: a yt-dlp az egész listára is lefuttatja a szűrőt, azonosító nélkül
        if video_id not in wanted:
            return f"{info.get('title') or video_id}: ebben a menetben nincs kiválasztva"
        # Ha a videó többször is szerepel a listában, csak az első előfordulását töltjük le. A yt-dlp a lista
        # lapozása közben sorszám nélkül is meghívja a szűrőt; azt még nem tekintjük előfordulásnak.
        position = info.get("playlist_index")
        if position is not None and positions.setdefault(video_id, position) != position:
            return f"{info.get('title') or video_id}: már szerepelt a listában"
        return None

    return match


def build_ydl_opts(request: DownloadRequest, tools: Tools) -> dict:
    opts = yt_dlp.parse_options(build_cli_args(request, tools)).ydl_opts
    if tools.js_runtimes:
        # Közvetlenül adjuk át, mert a CLI "név:útvonal" formátuma Windows-on ("C:\...") kétértelmű.
        opts["js_runtimes"] = tools.js_runtimes
    if request.playlist and request.playlist_ids:
        opts["match_filter"] = _select_ids(request.playlist_ids)
    return opts


# --- Előnézet ---------------------------------------------------------------


@dataclass(frozen=True)
class PlaylistEntry:
    index: int  # 1-től számozott helye a listában, ezt kapja a `--playlist-items`
    id: str
    title: str
    duration: int | None = None
    thumbnail: str | None = None


@dataclass(frozen=True)
class VideoInfo:
    kind: str  # "video" | "playlist"
    title: str
    uploader: str
    thumbnail: str | None
    duration: int | None = None  # másodperc
    max_height: int | None = None
    count: int | None = None  # lejátszási lista elemszáma
    entries: tuple[PlaylistEntry, ...] = ()


def summarize(info: dict) -> VideoInfo:
    """A yt-dlp info dictből az előnézethez szükséges adatok."""
    thumbnails = [t for t in info.get("thumbnails") or [] if t.get("url")]
    thumbnail = info.get("thumbnail") or (thumbnails[-1]["url"] if thumbnails else None)
    uploader = info.get("uploader") or info.get("channel") or ""

    if info.get("_type") == "playlist":
        entries = list(info.get("entries") or [])
        if not thumbnail and entries:
            first = ((entries[0] or {}).get("thumbnails") or [{}])[-1]
            thumbnail = first.get("url")
        return VideoInfo(
            kind="playlist",
            title=info.get("title") or "Lejátszási lista",
            uploader=uploader,
            thumbnail=thumbnail,
            count=info.get("playlist_count") or len(entries) or None,
            entries=tuple(_summarize_entries(entries)),
        )

    heights = [f["height"] for f in info.get("formats") or [] if f.get("height") and f.get("vcodec") != "none"]
    return VideoInfo(
        kind="video",
        title=info.get("title") or "",
        uploader=uploader,
        thumbnail=thumbnail,
        duration=int(info["duration"]) if info.get("duration") else None,
        max_height=max(heights) if heights else None,
    )


def _is_video(entry: dict) -> bool:
    """Lapos listaelemnél: önálló videó-e (és nem pl. egy csatorna Videók/Shorts füle, ami maga is lista)."""
    kind = entry.get("_type", "video")
    return kind == "video" or (kind in ("url", "url_transparent") and entry.get("ie_key") == "Youtube")


def _summarize_entries(entries: list[dict | None]) -> Iterable[PlaylistEntry]:
    """A lista elemei elemenkénti választáshoz. Ha nem mind önálló videó (pl. csatorna linkje, ahol az elemek
    a csatorna fülei), üres: ilyenkor a teljes lista egyben, egy módban töltődik le."""
    if not all(_is_video(entry) for entry in entries if entry):
        return
    for position, entry in enumerate(entries, start=1):
        if not entry:
            continue
        # A sorszám a lista egészében értendő, a kihagyott (üres) elemek is számítanak.
        thumbnails = [t["url"] for t in entry.get("thumbnails") or [] if t.get("url")]
        yield PlaylistEntry(
            index=entry.get("playlist_index") or position,
            id=entry.get("id") or "",
            title=entry.get("title") or entry.get("id") or f"{position}. elem",
            duration=int(entry["duration"]) if entry.get("duration") else None,
            thumbnail=thumbnails[0] if thumbnails else entry.get("thumbnail"),  # a legkisebb is elég
        )


class _SilentLogger:
    def debug(self, msg: str) -> None: ...
    def info(self, msg: str) -> None: ...
    def warning(self, msg: str) -> None: ...
    def error(self, msg: str) -> None: ...


def probe(url: str, tools: Tools | None = None, playlist: bool = False) -> VideoInfo:
    """Letöltés nélkül lekéri a videó vagy lejátszási lista adatait. Hiba esetén DownloadError.

    `playlist=True`: listához tartozó videó linkjénél (`watch?v=…&list=…`) a listát kéri le.
    """
    tools = tools or find_tools()
    opts: dict = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": not playlist,
        "extract_flat": "in_playlist",
        "logger": _SilentLogger(),
    }
    if tools.js_runtimes:
        opts["js_runtimes"] = tools.js_runtimes
    with yt_dlp.YoutubeDL(opts) as ydl:
        return summarize(ydl.extract_info(url, download=False))


# --- Futtatás ---------------------------------------------------------------


# A felhasználónak semmitmondó, de gyakori yt-dlp üzenetek.
_NOISE = re.compile(r"^\[download\](?!.*already been downloaded)|^\[debug\]|video thumbnail \d+|Downloading .*(webpage|API JSON|player|m3u8)")


class _Logger:
    def __init__(self, emit: Callable[[Event], None]):
        self._emit = emit

    def debug(self, msg: str) -> None:
        self.info(msg)

    def info(self, msg: str) -> None:
        if not _NOISE.search(msg):
            self._emit(Log(msg))

    def warning(self, msg: str) -> None:
        self._emit(Log(msg, "warning"))

    def error(self, msg: str) -> None:
        self._emit(Log(msg, "error"))


# A kulcs a yt-dlp utófeldolgozó neve (PostProcessor.pp_key()).
_POSTPROCESSOR_LABELS = {
    "Merger": "Videó és hang összefűzése…",
    "ExtractAudio": "Hangsáv feldolgozása…",
    "VideoRemuxer": "Átcsomagolás…",
    "EmbedThumbnail": "Borítókép beágyazása…",
    "Metadata": "Metaadatok beírása…",
}


class Downloader:
    """Egy letöltés futtatása. A `run` blokkol, ezért háttérszálon kell hívni."""

    def __init__(self, emit: Callable[[Event], None], tools: Tools | None = None):
        self._emit = emit
        self._tools = tools or find_tools()
        self._cancel = threading.Event()
        self._mode = Mode.VIDEO
        # Elemenként választott listánál az elemek folyamatos számozásához, a menetek (videó, hang) között is.
        self._item_offset = 0
        self._item_total: int | None = None
        self._item_numbers: dict[str, int] = {}  # az aktuális menetben: azonosító → sorszám

    @property
    def tools(self) -> Tools:
        return self._tools

    def cancel(self) -> None:
        self._cancel.set()

    def run(self, *requests: DownloadRequest) -> None:
        """A kéréseket egymás után futtatja (pl. egy lista videóként és hangként kért elemeit)."""
        if not self._tools.ffmpeg_dir:
            self._emit(Finished(False, "Az ffmpeg nem található. Telepítsd, vagy használd a csomagolt alkalmazást."))
            return
        if not self._tools.js_runtimes:
            self._emit(Log("Nincs JavaScript futtatókörnyezet (Deno) – a YouTube csak korlátozottan működhet.", "warning"))

        if all(r.playlist and r.playlist_ids for r in requests):
            self._item_total = sum(len(r.playlist_ids) for r in requests)
        files: list[str] = []
        failed = False

        for request in requests:
            if self._cancel.is_set():
                break
            opts = build_ydl_opts(request, self._tools)
            opts.update(
                logger=_Logger(self._emit),
                quiet=True,
                noprogress=True,
                progress_hooks=[self._on_progress],
                postprocessor_hooks=[self._on_postprocess(files)],
            )
            if "match_filter" in opts:
                opts["match_filter"] = self._cancellable(opts["match_filter"])
            self._mode = request.mode
            self._item_numbers = {}

            try:
                request.output_dir.mkdir(parents=True, exist_ok=True)
                self._emit(Status(_fetch_status(request, len(requests) > 1)))
                with yt_dlp.YoutubeDL(opts) as ydl:
                    failed |= bool(ydl.download([request.url]))
            except DownloadCancelled:
                self._emit(Finished(False, "Letöltés megszakítva.", tuple(files)))
                return
            except DownloadError as e:
                self._emit(Finished(False, _clean_error(str(e)), tuple(files)))
                return
            except Exception as e:  # noqa: BLE001 - a GUI-nak minden hibáról tudnia kell
                self._emit(Finished(False, f"Váratlan hiba: {e}", tuple(files)))
                return
            self._item_offset += len(request.playlist_ids)

        if self._cancel.is_set():
            self._emit(Finished(False, "Letöltés megszakítva.", tuple(files)))
        elif failed:
            self._emit(Finished(False, "A letöltés hibával ért véget, részletek a naplóban.", tuple(files)))
        else:
            self._emit(Finished(True, "Kész!", tuple(files)))

    def _cancellable(self, match_filter: Callable[..., str | None]) -> Callable[..., str | None]:
        """A megszakítást a szűrőben is figyeljük: a kihagyott elemek átlépése alatt nincs folyamatjelzés."""

        def match(info: dict, *, incomplete: bool = False) -> str | None:
            if self._cancel.is_set():
                raise DownloadCancelled()
            return match_filter(info, incomplete=incomplete)

        return match

    def _on_progress(self, d: dict) -> None:
        if self._cancel.is_set():
            raise DownloadCancelled()

        info = d.get("info_dict") or {}
        index, count = info.get("playlist_index"), info.get("n_entries")
        item = f"{index}/{count}" if index and count else ""
        if self._item_total and info.get("id"):
            # A yt-dlp számozása a teljes listára vonatkozik (a kihagyott elemekkel együtt), ezért magunk számolunk.
            number = self._item_numbers.setdefault(info["id"], len(self._item_numbers) + 1)
            item = f"{self._item_offset + number}/{self._item_total}"
        filename = Path(d.get("filename") or "").name
        kind = "audio" if info.get("vcodec") == "none" else "video"
        mode = self._mode.value

        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            done = d.get("downloaded_bytes") or 0
            percent = done / total * 100 if total else None
            self._emit(Progress(percent, d.get("speed"), d.get("eta"), filename, item, kind, mode))
        elif d["status"] == "finished":
            self._emit(Progress(100.0, None, None, filename, item, kind, mode))

    def _on_postprocess(self, files: list[str]) -> Callable[[dict], None]:
        def hook(d: dict) -> None:
            if d["status"] == "started":
                label = _POSTPROCESSOR_LABELS.get(d.get("postprocessor", ""))
                if label:
                    self._emit(Status(label))
            elif d["status"] == "finished" and d.get("postprocessor") == "MoveFiles":
                path = (d.get("info_dict") or {}).get("filepath")
                if path and path not in files:
                    files.append(path)

        return hook


def _fetch_status(request: DownloadRequest, multiple: bool) -> str:
    if not multiple:
        return "Videó adatainak lekérése…"
    what = "hangként" if request.mode is Mode.AUDIO else "videóként"
    return f"{len(request.playlist_ids)} elem előkészítése {what}…"


def _clean_error(message: str) -> str:
    return message.removeprefix("ERROR: ").strip() or "Ismeretlen hiba történt."
