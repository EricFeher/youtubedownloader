"""Letöltési sor: a hozzáadott letöltéseket egymás után futtatja egy háttérszálon, GUI-tól függetlenül."""

from __future__ import annotations

import dataclasses
import itertools
import re
import threading
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Protocol
from urllib.parse import parse_qs, urlparse

from .downloader import AUDIO_FORMATS, VIDEO_CONTAINERS, DownloadRequest, Event, Finished, Mode, Progress, Status


class ItemState(Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


_PENDING = {ItemState.QUEUED, ItemState.RUNNING}
_FINISHED = {ItemState.DONE, ItemState.FAILED, ItemState.CANCELLED}


@dataclass
class QueueItem:
    id: int
    request: DownloadRequest
    title: str = ""  # ha üres, az első letöltési eseményből töltjük ki
    thumbnail: str | None = None
    state: ItemState = ItemState.QUEUED
    message: str = ""
    files: tuple[str, ...] = ()
    status: str = ""  # a futó letöltés utolsó állapotüzenete

    def to_dict(self) -> dict:
        r = self.request
        return {
            "id": self.id,
            "url": r.url,
            "title": self.title,
            "thumbnail": self.thumbnail,
            "state": self.state.value,
            "message": self.message,
            "files": list(self.files),
            "status": self.status,
            "mode": r.mode.value,
            "container": r.container,
            "audio_format": r.audio_format,
            "max_height": r.max_height,
            "compatible": r.compatible,
            "playlist": r.playlist,
        }


# --- Események a GUI felé -------------------------------------------------


@dataclass(frozen=True)
class QueueChanged:
    version: int  # verziósorrendben mennek ki; a GUI a régebbit eldobja
    items: tuple[QueueItem, ...]  # másolatok, a sor belső állapotát nem lehet rajtuk keresztül módosítani


@dataclass(frozen=True)
class ItemEvent:
    item_id: int
    event: Event  # Progress | Status | Log – a Finished-et a sor maga dolgozza fel


QueueEvent = QueueChanged | ItemEvent


def event_payload(event: QueueEvent) -> dict:
    """JSON-ná alakítható alak a felületnek."""
    if isinstance(event, QueueChanged):
        return {"type": "queue", "version": event.version, "items": [item.to_dict() for item in event.items]}
    return {"type": type(event.event).__name__.lower(), "id": event.item_id, **dataclasses.asdict(event.event)}


# --- A sor --------------------------------------------------------------------


class Runner(Protocol):
    def run(self, request: DownloadRequest) -> None: ...
    def cancel(self) -> None: ...


DownloaderFactory = Callable[[Callable[[Event], None]], Runner]


class DownloadQueue:
    """Egyszerre egy letöltést futtat, a többi a hozzáadás sorrendjében várakozik.

    A metódusok bármelyik szálról hívhatók; az `emit` a letöltés háttérszáláról is meghívódik.
    """

    def __init__(self, emit: Callable[[QueueEvent], None], downloader_factory: DownloaderFactory):
        self._emit = emit
        self._factory = downloader_factory
        self._lock = threading.Lock()
        # Az állapotképeket sorosítja, így verziósorrendben mennek ki; az állapotzárat közben nem tartjuk.
        self._emit_lock = threading.Lock()
        self._idle = threading.Condition(self._lock)
        self._items: list[QueueItem] = []
        self._ids = itertools.count(1)
        self._version = 0
        self._active: tuple[QueueItem, Runner] | None = None
        self._unannounced = 0  # befejezett letöltések, amelyek végleges állapotképe még nem ment ki
        self._cancel_requested = False
        self._closed = False

    def snapshot(self) -> QueueChanged:
        with self._lock:
            self._version += 1
            return QueueChanged(self._version, tuple(dataclasses.replace(i) for i in self._items))

    def add(self, request: DownloadRequest, title: str = "", thumbnail: str | None = None) -> QueueItem | None:
        """Sorba állít egy letöltést. Ha pontosan ez már várakozik vagy fut, nem veszi fel újra (None)."""
        return self.add_many([(request, title, thumbnail)])[0]

    def add_many(self, entries: list[tuple[DownloadRequest, str, str | None]]) -> list[QueueItem | None]:
        """Több letöltés sorba állítása egyetlen állapotképpel; az ismétlődők helyén None."""
        added: list[QueueItem | None] = []
        with self._lock:
            for request, title, thumbnail in entries:
                if self._closed or self._is_pending_locked(request):
                    added.append(None)
                    continue
                item = QueueItem(next(self._ids), request, title, thumbnail)
                self._items.append(item)
                added.append(dataclasses.replace(item))
            self._start_next_locked()
        if any(added):
            self._changed()
        return added

    def remove(self, item_id: int) -> bool:
        """Kiveszi a várakozó vagy befejezett elemet. A futót előbb meg kell szakítani."""
        with self._lock:
            item = self._find(item_id)
            if not item or item.state is ItemState.RUNNING:
                return False
            self._items.remove(item)
        self._changed()
        return True

    def cancel(self, item_id: int) -> bool:
        """Megszakítja a futó elemet; utána a sor a következővel folytatja."""
        with self._lock:
            if not self._active or self._active[0].id != item_id:
                return False
            self._cancel_requested = True
            self._active[1].cancel()
        return True

    def retry(self, item_id: int) -> bool:
        """A sikertelen vagy megszakított elemet újra a sor végére teszi, ha ugyanez nincs már a sorban."""
        with self._lock:
            item = self._find(item_id)
            if (
                not item
                or item.state not in (ItemState.FAILED, ItemState.CANCELLED)
                or self._closed
                or self._is_pending_locked(item.request)
            ):
                return False
            self._items.remove(item)
            item.state, item.message, item.files, item.status = ItemState.QUEUED, "", (), ""
            self._items.append(item)
            self._start_next_locked()
        self._changed()
        return True

    def clear_finished(self) -> int:
        with self._lock:
            kept = [i for i in self._items if i.state not in _FINISHED]
            removed = len(self._items) - len(kept)
            self._items = kept
        if removed:
            self._changed()
        return removed

    def shutdown(self) -> None:
        """Ablak bezárásakor: a várakozókat eldobja, a futót megszakítja. Ezután eseményt már nem küld."""
        with self._lock:
            self._closed = True
            self._items = [i for i in self._items if i.state is not ItemState.QUEUED]
            if self._active:
                self._cancel_requested = True
                self._active[1].cancel()
            self._idle.notify_all()

    def wait_idle(self, timeout: float | None = None) -> bool:
        """Megvárja, amíg nincs futó és várakozó elem, és a végleges állapotkép is kiment. Hamis, ha lejárt az idő."""
        with self._lock:
            return self._idle.wait_for(self._is_idle_locked, timeout)

    # --- Belső -------------------------------------------------------------

    def _find(self, item_id: int) -> QueueItem | None:
        return next((i for i in self._items if i.id == item_id), None)

    def _is_pending_locked(self, request: DownloadRequest) -> bool:
        return any(i.request == request and i.state in _PENDING for i in self._items)

    def _is_idle_locked(self) -> bool:
        if self._active or self._unannounced:
            return False
        return self._closed or all(i.state is not ItemState.QUEUED for i in self._items)

    def _changed(self) -> None:
        with self._emit_lock:
            if not self._closed:
                self._emit(self.snapshot())

    def _start_next_locked(self) -> None:
        while not self._active and not self._closed:
            item = next((i for i in self._items if i.state is ItemState.QUEUED), None)
            if not item:
                return
            try:
                runner = self._factory(lambda event, item=item: self._on_event(item, event))
                thread = threading.Thread(target=self._run, args=(item, runner), daemon=True, name=f"download-{item.id}")
                item.state = ItemState.RUNNING
                self._active = (item, runner)
                self._cancel_requested = False
                thread.start()
            except Exception as e:  # noqa: BLE001 - ami el sem indul, legyen sikertelen, és jöhet a következő
                item.state, item.message = ItemState.FAILED, f"Nem sikerült elindítani: {e}"
                self._active = None

    def _run(self, item: QueueItem, runner: Runner) -> None:
        try:
            runner.run(item.request)
        except Exception as e:  # noqa: BLE001 - egy hibás elem ne állítsa le a sort
            with self._lock:
                self._finish_locked(item, Finished(False, f"Váratlan hiba: {e}"))
        with self._lock:
            self._finish_locked(item, Finished(False, "A letöltés eredmény nélkül ért véget."))
            self._active = None
            self._unannounced += 1
            self._start_next_locked()
        self._changed()
        with self._lock:
            # Csak az állapotkép után számít tétlennek, hogy a várakozó már a végleges állapotot lássa.
            self._unannounced -= 1
            if self._is_idle_locked():
                self._idle.notify_all()

    def _finish_locked(self, item: QueueItem, result: Finished) -> None:
        if item.state is not ItemState.RUNNING:
            return  # csak az első eredmény számít
        if result.ok:
            item.state = ItemState.DONE
        elif self._cancel_requested:
            item.state = ItemState.CANCELLED
        else:
            item.state = ItemState.FAILED
        item.message, item.files = result.message, result.files

    def _on_event(self, item: QueueItem, event: Event) -> None:
        if isinstance(event, Finished):
            with self._lock:
                self._finish_locked(item, event)
            return
        title_found = False
        with self._lock:
            if self._closed:
                return
            if isinstance(event, Status):
                # Az állapotképbe is bekerül: az indulás utáni első üzenet megelőzheti a „fut” állapotképet.
                item.status = event.text
            elif isinstance(event, Progress) and event.title and not item.title:
                item.title = event.title
                title_found = True
        if title_found:
            self._changed()
        self._emit(ItemEvent(item.id, event))


# --- Felületről érkező adatok -------------------------------------------------


# Séma nélküli YouTube-link is jó (pl. "youtu.be/abc"). Szóköz, zárójel és idézőjel nem lehet része.
_URL_START = r"(?:https?://|(?:(?:www|m|music)\.)?youtube\.com/|youtu\.be/)"
_URL = re.compile(_URL_START + r"[^\s<>\"'\[\]„“”‘’«»…]+", re.IGNORECASE)
# Szóköz nélkül, vesszővel vagy pontosvesszővel egymás után írt linkek határa.
_JOINED = re.compile(r"[,;](?=" + _URL_START + ")", re.IGNORECASE)
_TRAILING = ".,;:!?)}>"


def extract_urls(text: str) -> list[str]:
    """A beillesztett szövegből a linkek sorrendben, ismétlés nélkül (pl. soronként egy link)."""
    urls: list[str] = []
    for match in _URL.finditer(_JOINED.sub(" ", text)):
        url = match.group().rstrip(_TRAILING)
        if not url.lower().startswith(("http://", "https://")):
            url = f"https://{url}"
        if url not in urls:
            urls.append(url)
    return urls


# Csatorna és a lapjai (videók, shortok…): a yt-dlp ezeket is lejátszási listaként tölti le.
_CHANNEL_PATH = re.compile(r"^/(?:@[^/]+|channel/[^/]+|c/[^/]+|user/[^/]+)(?:/|$)", re.IGNORECASE)


def is_playlist_url(url: str) -> bool:
    """Lejátszási listát vagy csatornát jelölő link, nem egy listában lévő videó."""
    parsed = urlparse(url if "://" in url else f"https://{url}")
    host = parsed.netloc.lower()
    if host.endswith("youtu.be"):
        return False
    query = parse_qs(parsed.query)
    if "list" in query and "v" not in query:
        return True
    return host.endswith("youtube.com") and bool(_CHANNEL_PATH.match(parsed.path))


def build_request(url: str, options: dict, output_dir: Path, playlist: bool) -> DownloadRequest:
    """Letöltési kérés a felület beállításaiból; ismeretlen érték helyett az alapértelmezettet veszi."""
    mode = options.get("mode")
    container = options.get("container")
    audio_format = options.get("audio_format")
    quality = str(options.get("quality") or "best")
    return DownloadRequest(
        url=url,
        output_dir=output_dir,
        mode=Mode(mode) if mode in {m.value for m in Mode} else Mode.VIDEO,
        max_height=int(quality) if quality.isascii() and quality.isdigit() else None,
        compatible=bool(options.get("compatible")),
        container=container if container in VIDEO_CONTAINERS else VIDEO_CONTAINERS[0],
        audio_format=audio_format if audio_format in AUDIO_FORMATS else AUDIO_FORMATS[0],
        playlist=playlist,
    )
