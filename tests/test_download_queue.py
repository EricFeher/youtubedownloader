import json
import threading
from pathlib import Path

import pytest

from ytletolto.download_queue import (
    DownloadQueue,
    ItemEvent,
    ItemState,
    QueueChanged,
    build_request,
    event_payload,
    extract_urls,
    is_playlist_url,
)
from ytletolto.downloader import DownloadRequest, Downloader, Finished, Log, Mode, Progress, Status, Tools

TIMEOUT = 5


def request(url: str = "https://youtu.be/ok", **overrides) -> DownloadRequest:
    return DownloadRequest(**{"url": url, "output_dir": Path("/out"), "mode": Mode.VIDEO, **overrides})


class FakeDownloader:
    """A link végződése dönti el, mi történik: ok, fail, crash, silent vagy block (megszakításig fut)."""

    def __init__(self, harness: "Harness", emit):
        self._harness = harness
        self._emit = emit
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        self._cancelled.set()

    def run(self, request: DownloadRequest) -> None:
        h = self._harness
        with h.lock:
            h.running += 1
            h.max_running = max(h.max_running, h.running)
            h.runs.append(request.url)
        try:
            kind = request.url.rsplit("/", 1)[-1]
            self._emit(Status("Videó adatainak lekérése…"))
            self._emit(Progress(50.0, 1024.0, 3, "x.mp4", "", "video", f"Cím: {kind}"))
            if kind == "block":
                h.blocking.set()
                self._cancelled.wait(TIMEOUT)
                self._emit(Finished(False, "Letöltés megszakítva."))
            elif kind == "fail" or (kind == "flaky" and h.runs.count(request.url) == 1):
                self._emit(Log("valami elromlott", "error"))
                self._emit(Finished(False, "Nem elérhető videó."))
            elif kind == "crash":
                raise RuntimeError("bumm")
            elif kind == "silent":
                pass  # Finished esemény nélkül tér vissza
            else:
                self._emit(Finished(True, "Kész!", (f"/out/{kind}.mp4",)))
        finally:
            with h.lock:
                h.running -= 1


class Harness:
    def __init__(self):
        self.lock = threading.Lock()
        self.events: list = []
        self.runs: list[str] = []
        self.running = self.max_running = 0
        self.blocking = threading.Event()
        self.queue = DownloadQueue(self._record, self._factory)

    def _factory(self, emit):
        return FakeDownloader(self, emit)

    def _record(self, event) -> None:
        with self.lock:
            self.events.append(event)

    def add(self, *urls: str, **kwargs):
        return [self.queue.add(request(url), **kwargs) for url in urls]

    def wait(self) -> None:
        assert self.queue.wait_idle(TIMEOUT), "a sor nem ürült ki időben"

    def items(self) -> dict[str, object]:
        return {item.request.url.rsplit("/", 1)[-1]: item for item in self.queue.snapshot().items}

    def snapshots(self) -> list[QueueChanged]:
        with self.lock:
            return [e for e in self.events if isinstance(e, QueueChanged)]


@pytest.fixture
def h() -> Harness:
    harness = Harness()
    yield harness
    harness.queue.shutdown()


def test_runs_items_one_at_a_time_in_order(h):
    h.add("https://youtu.be/a", "https://youtu.be/b", "https://youtu.be/c")
    h.wait()

    assert h.runs == ["https://youtu.be/a", "https://youtu.be/b", "https://youtu.be/c"]
    assert h.max_running == 1
    items = h.items()
    assert all(item.state is ItemState.DONE for item in items.values())
    assert items["b"].files == ("/out/b.mp4",)


def test_failure_does_not_stop_the_queue(h):
    h.add("https://youtu.be/fail", "https://youtu.be/crash", "https://youtu.be/silent", "https://youtu.be/ok")
    h.wait()

    items = h.items()
    assert (items["fail"].state, items["fail"].message) == (ItemState.FAILED, "Nem elérhető videó.")
    assert items["crash"].state is ItemState.FAILED and "bumm" in items["crash"].message
    assert items["silent"].state is ItemState.FAILED
    assert items["ok"].state is ItemState.DONE


def test_same_request_is_not_queued_twice_while_pending(h):
    first, duplicate = h.add("https://youtu.be/block", "https://youtu.be/block")
    other_format = h.queue.add(request("https://youtu.be/block", mode=Mode.AUDIO))

    assert first is not None and duplicate is None
    assert other_format is not None  # más formátumban ugyanaz a videó külön elem

    assert h.blocking.wait(TIMEOUT)
    h.queue.remove(other_format.id)
    h.queue.cancel(first.id)
    h.wait()
    assert h.queue.add(request("https://youtu.be/ok")) is not None
    assert h.queue.add(request("https://youtu.be/block")) is not None  # befejezett után újra felvehető


def test_cancel_stops_running_item_and_continues_with_next(h):
    block, ok = h.add("https://youtu.be/block", "https://youtu.be/ok")
    assert h.blocking.wait(TIMEOUT)

    assert h.queue.cancel(ok.id) is False  # csak a futó elemet lehet megszakítani
    assert h.queue.cancel(block.id) is True
    h.wait()

    items = h.items()
    assert items["block"].state is ItemState.CANCELLED
    assert items["ok"].state is ItemState.DONE


def test_retry_requeues_failed_item_at_the_end(h):
    flaky, ok = h.add("https://youtu.be/flaky", "https://youtu.be/ok")
    h.wait()
    assert h.items()["flaky"].state is ItemState.FAILED

    assert h.queue.retry(flaky.id) is True
    h.wait()

    assert [i.id for i in h.queue.snapshot().items] == [ok.id, flaky.id]
    retried = h.items()["flaky"]
    assert (retried.state, retried.message, retried.files) == (ItemState.DONE, "Kész!", ("/out/flaky.mp4",))
    assert h.queue.retry(ok.id) is False  # sikeres elemet nem kell újrapróbálni


def test_retry_does_not_duplicate_a_request_already_back_in_the_queue(h):
    (failed,) = h.add("https://youtu.be/fail")
    h.wait()
    h.add("https://youtu.be/block", "https://youtu.be/fail")  # ugyanaz a link újra beillesztve
    assert h.blocking.wait(TIMEOUT)

    assert h.queue.retry(failed.id) is False
    assert [i.request.url for i in h.queue.snapshot().items].count("https://youtu.be/fail") == 2


def test_add_many_skips_duplicates_and_emits_one_snapshot(h):
    h.add("https://youtu.be/block")
    assert h.blocking.wait(TIMEOUT)
    before = len(h.snapshots())

    added = h.queue.add_many([(request(u), "", None) for u in ("https://youtu.be/a", "https://youtu.be/block", "https://youtu.be/a")])

    assert [item is not None for item in added] == [True, False, False]
    assert len(h.snapshots()) == before + 1


def test_item_that_cannot_start_fails_and_the_queue_moves_on(h):
    real_factory = h._factory
    calls = []

    def flaky_factory(emit):
        calls.append(1)
        if len(calls) == 1:
            raise OSError("nincs több szál")
        return real_factory(emit)

    h.queue._factory = flaky_factory
    h.add("https://youtu.be/a", "https://youtu.be/b")
    h.wait()

    items = h.items()
    assert items["a"].state is ItemState.FAILED and "nincs több szál" in items["a"].message
    assert items["b"].state is ItemState.DONE
    assert h.queue.retry(h.items()["a"].id) is True
    h.wait()
    assert h.items()["a"].state is ItemState.DONE


def test_remove_drops_waiting_item_but_not_running_one(h):
    block, waiting = h.add("https://youtu.be/block", "https://youtu.be/ok")
    assert h.blocking.wait(TIMEOUT)

    assert h.queue.remove(block.id) is False
    assert h.queue.remove(waiting.id) is True
    h.queue.cancel(block.id)
    h.wait()

    assert "https://youtu.be/ok" not in h.runs
    assert list(h.items()) == ["block"]


def test_clear_finished_keeps_pending_items(h):
    h.add("https://youtu.be/ok", "https://youtu.be/fail")
    h.wait()
    h.add("https://youtu.be/block", "https://youtu.be/waiting")
    assert h.blocking.wait(TIMEOUT)

    assert h.queue.clear_finished() == 2
    assert set(h.items()) == {"block", "waiting"}


def test_title_comes_from_download_when_unknown(h):
    h.queue.add(request("https://youtu.be/a"))
    h.queue.add(request("https://youtu.be/b"), title="Előnézet címe", thumbnail="https://img/b.jpg")
    h.wait()

    items = h.items()
    assert items["a"].title == "Cím: a"
    assert (items["b"].title, items["b"].thumbnail) == ("Előnézet címe", "https://img/b.jpg")


def test_progress_is_forwarded_with_item_id_and_snapshots_are_versioned(h):
    (item,) = h.add("https://youtu.be/ok")
    h.wait()

    with h.lock:
        forwarded = [e for e in h.events if isinstance(e, ItemEvent)]
    assert {e.item_id for e in forwarded} == {item.id}
    assert any(isinstance(e.event, Progress) for e in forwarded)
    assert not any(isinstance(e.event, Finished) for e in forwarded)  # azt a sor dolgozza fel

    versions = [s.version for s in h.snapshots()]
    assert versions == sorted(set(versions))
    latest = max(h.snapshots(), key=lambda s: s.version)
    assert latest.items[0].state is ItemState.DONE


def test_snapshot_items_are_copies(h):
    h.add("https://youtu.be/block")
    assert h.blocking.wait(TIMEOUT)

    copy = h.queue.snapshot().items[0]
    copy.state = ItemState.DONE

    assert h.queue.snapshot().items[0].state is ItemState.RUNNING


def test_shutdown_cancels_running_and_drops_waiting(h):
    block, _ = h.add("https://youtu.be/block", "https://youtu.be/ok")
    assert h.blocking.wait(TIMEOUT)

    h.queue.shutdown()
    h.wait()

    assert h.runs == ["https://youtu.be/block"]
    assert [i.id for i in h.queue.snapshot().items] == [block.id]
    assert h.queue.add(request("https://youtu.be/new")) is None


def test_no_events_after_shutdown(h):
    h.add("https://youtu.be/block")
    assert h.blocking.wait(TIMEOUT)

    h.queue.shutdown()
    with h.lock:
        seen = len(h.events)
    h.wait()

    with h.lock:
        assert len(h.events) == seen


def test_running_item_keeps_its_latest_status_message(h):
    h.add("https://youtu.be/block")
    assert h.blocking.wait(TIMEOUT)

    assert h.queue.snapshot().items[0].status == "Videó adatainak lekérése…"


def test_event_payload_is_json_serialisable(h):
    h.add("https://youtu.be/ok")
    h.wait()
    with h.lock:
        events = list(h.events)

    payloads = [json.loads(json.dumps(event_payload(e))) for e in events]

    queue = next(p for p in reversed(payloads) if p["type"] == "queue")
    assert queue["items"][0] | {"id": 0} == {
        "id": 0, "url": "https://youtu.be/ok", "title": "Cím: ok", "thumbnail": None, "state": "done",
        "message": "Kész!", "files": ["/out/ok.mp4"], "status": "Videó adatainak lekérése…", "mode": "video", "container": "mp4",
        "audio_format": "mp3", "max_height": None, "compatible": False, "playlist": False,
    }
    progress = next(p for p in payloads if p["type"] == "progress")
    assert progress["id"] == queue["items"][0]["id"] and progress["percent"] == 50.0


# --- Felületről érkező adatok ------------------------------------------------


def test_extract_urls_from_pasted_text():
    text = """Ezeket nézd meg:
    https://www.youtube.com/watch?v=aaa,
    youtu.be/bbb
    (https://youtu.be/ccc) és https://www.youtube.com/watch?v=aaa megint
    nem link: youtube
    [https://youtu.be/ddd](https://youtu.be/ddd)
    „https://youtu.be/eee” és “https://youtu.be/fff”…
    https://youtu.be/ggg,https://youtu.be/hhh;youtu.be/iii
    """

    assert extract_urls(text) == [
        "https://www.youtube.com/watch?v=aaa",
        "https://youtu.be/bbb",
        "https://youtu.be/ccc",
        "https://youtu.be/ddd",
        "https://youtu.be/eee",
        "https://youtu.be/fff",
        "https://youtu.be/ggg",
        "https://youtu.be/hhh",
        "https://youtu.be/iii",
    ]
    assert extract_urls("semmi") == []


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.youtube.com/playlist?list=PL123", True),
        ("youtube.com/playlist?list=PL123", True),
        ("https://www.youtube.com/watch?v=abc&list=PL123", False),
        ("https://youtu.be/abc?list=PL123", False),
        ("https://www.youtube.com/watch?v=abc", False),
        ("https://www.youtube.com/@csatorna", True),
        ("https://www.youtube.com/@csatorna/videos", True),
        ("https://www.youtube.com/channel/UC123/shorts", True),
        ("https://www.youtube.com/c/Valami", True),
        ("https://www.youtube.com/shorts/abc", False),
        ("https://example.com/@valaki", False),
    ],
)
def test_is_playlist_url(url, expected):
    assert is_playlist_url(url) is expected


def test_build_request_normalises_unknown_options():
    out = Path("/out")

    good = build_request("u", {"mode": "audio", "quality": "1080", "container": "mkv", "audio_format": "opus", "compatible": 1}, out, True)
    bad = build_request("u", {"mode": "x", "quality": "4k", "container": "avi", "audio_format": "flac"}, out, False)

    assert good == DownloadRequest("u", out, Mode.AUDIO, 1080, True, "mkv", "opus", True)
    assert bad == DownloadRequest("u", out, Mode.VIDEO, None, False, "mp4", "mp3", False)
    assert build_request("u", {"quality": "best"}, out, False).max_height is None


# --- A Downloader címe a folyamateseményben ----------------------------------


@pytest.mark.parametrize(
    ("info", "title"),
    [
        ({"title": "Videó"}, "Videó"),
        ({"title": "3. rész", "playlist_title": "Lista", "playlist_index": 3, "n_entries": 9}, "Lista"),
        ({}, ""),
    ],
)
def test_progress_carries_video_or_playlist_title(info, title):
    events = []
    downloader = Downloader(events.append, Tools(ffmpeg_dir=Path("/opt/ffmpeg")))

    downloader._on_progress({"status": "downloading", "info_dict": info, "downloaded_bytes": 5, "total_bytes": 10})

    assert events[0].title == title and events[0].percent == 50.0
