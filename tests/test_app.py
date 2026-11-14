import threading
from pathlib import Path

import pytest

from ytletolto import app
from ytletolto.downloader import Finished, Tools


class IdleDownloader:
    def __init__(self, emit, tools):
        self._emit = emit

    def run(self, request) -> None:
        self._emit(Finished(True, "Kész!"))

    def cancel(self) -> None: ...


class BlockingDownloader:
    def __init__(self):
        self._cancelled = threading.Event()

    def run(self, request) -> None:
        self._cancelled.wait(5)

    def cancel(self) -> None:
        self._cancelled.set()


@pytest.fixture
def api(tmp_path, monkeypatch):
    saved = []
    monkeypatch.setattr(app, "find_tools", lambda: Tools(ffmpeg_dir=Path("/opt/ffmpeg")))
    monkeypatch.setattr(app, "Downloader", IdleDownloader)
    monkeypatch.setattr(app.settings_store, "load", lambda: {**app.settings_store.DEFAULTS, "output_dir": str(tmp_path)})
    monkeypatch.setattr(app.settings_store, "save", lambda settings: saved.append(dict(settings)))
    instance = app.Api()
    instance.saved = saved
    yield instance
    instance.on_closing()


def requests(api) -> dict:
    return {item.request.url: item.request for item in api._queue.snapshot().items}


def test_enqueue_detects_playlists_only_when_the_ui_does_not_know(api):
    result = api.enqueue({
        "items": [
            {"url": "https://www.youtube.com/playlist?list=PL1", "playlist": None},
            {"url": "https://youtu.be/a?list=PL1", "playlist": True, "title": "Előnézet"},
            {"url": "  https://youtu.be/b  "},
            {"url": ""},
        ],
        "mode": "audio",
        "audio_format": "opus",
        "quality": "720",
    })
    api._queue.wait_idle(5)

    assert result == {"ok": True, "added": 3, "skipped": 0}
    got = requests(api)
    assert got["https://www.youtube.com/playlist?list=PL1"].playlist is True
    assert got["https://youtu.be/a?list=PL1"].playlist is True
    assert got["https://youtu.be/b"].playlist is False
    assert got["https://youtu.be/b"].output_dir == Path(api._settings["output_dir"])
    # A minőség a felhasználó mentett választása marad; a videóhoz igazított érték nem írja felül.
    assert api.saved[-1] | {"output_dir": ""} == {
        "output_dir": "", "mode": "audio", "quality": "best", "compatible": False, "container": "mp4", "audio_format": "opus",
    }


def test_enqueue_reports_duplicates_still_in_the_queue(api):
    api._queue.shutdown()  # semmi ne fusson le, így minden elem várakozó marad
    api._queue = app.DownloadQueue(lambda event: None, lambda emit: BlockingDownloader())
    entry = {"url": "https://youtu.be/a"}

    first = api.enqueue({"items": [entry]})
    again = api.enqueue({"items": [entry, {"url": "https://youtu.be/b"}]})

    assert first == {"ok": True, "added": 1, "skipped": 0}
    assert again == {"ok": True, "added": 1, "skipped": 1}


def test_enqueue_rejects_empty_input_and_missing_ffmpeg(api):
    assert api.enqueue({"items": [{"url": "  "}]}) == {"ok": False, "error": "Adj meg egy linket."}

    api._tools = Tools(ffmpeg_dir=None)
    result = api.enqueue({"items": [{"url": "https://youtu.be/a"}]})

    assert not result["ok"] and "ffmpeg" in result["error"]
    assert api._queue.snapshot().items == ()
    assert api.saved == []


@pytest.mark.parametrize("selection, expected", [
    ([{"id": "a", "mode": "video"}], [("video", ("a",))]),
    ([{"id": "a", "mode": "video"}, {"id": "c", "mode": "audio"}],
     [("video", ("a",)), ("audio", ("c",))]),
])
def test_enqueue_preserves_playlist_selection_and_modes(api, selection, expected):
    result = api.enqueue({"items": [{
        "url": "https://www.youtube.com/playlist?list=PL1",
        "selection": selection,
        "title": "Kiválasztott lista",
    }]})
    assert api._queue.wait_idle(5)

    queued = api._queue.snapshot().items
    assert result == {"ok": True, "added": len(expected), "skipped": 0}
    assert [(i.request.mode.value, i.request.playlist_ids) for i in queued] == expected
    assert all(i.title == "Kiválasztott lista" for i in queued)


def test_enqueue_empty_playlist_selection_does_not_download_whole_list(api):
    result = api.enqueue({"items": [{
        "url": "https://www.youtube.com/playlist?list=PL1", "selection": [],
    }]})

    assert result["ok"] is False
    assert api._queue.snapshot().items == ()
    assert api.saved == []


def test_enqueue_invalid_time_range_is_atomic(api):
    result = api.enqueue({"items": [
        {"url": "https://youtu.be/valid"},
        {"url": "https://youtube.com/playlist?list=PL", "selection": [
            {"id": "a", "options": {"start_time": 50, "end_time": 20}},
        ]},
    ]})
    assert not result["ok"]
    assert api._queue.snapshot().items == ()
    assert api.saved == []


def test_playlist_item_options_do_not_overwrite_global_defaults(api):
    result = api.enqueue({"items": [{
        "url": "https://youtube.com/playlist?list=PL", "selection": [
            {"id": "a", "options": {"mode": "audio", "audio_format": "opus", "start_time": 10, "end_time": 30}},
        ],
    }], "mode": "video", "container": "mkv"})
    assert result["ok"]
    assert api._queue.wait_idle(5)
    (item,) = api._queue.snapshot().items
    assert item.request.mode.value == "audio"
    assert (item.request.start_time, item.request.end_time) == (10, 30)
    assert api.saved[-1]["mode"] == "video"
    assert api.saved[-1]["audio_format"] == "mp3"
    assert "start_time" not in api.saved[-1]


def test_playlist_groups_start_with_their_first_video_thumbnail(api):
    result = api.enqueue({"items": [{
        "url": "https://youtube.com/playlist?list=PL", "thumbnail": "playlist.jpg",
        "selection": [
            {"id": "a", "thumbnail": "a.jpg", "options": {}},
            {"id": "b", "thumbnail": "b.jpg", "options": {}},
            {"id": "c", "thumbnail": "c.jpg", "options": {"mode": "audio"}},
        ],
    }]})
    assert result["ok"] and api._queue.wait_idle(5)
    assert [(item.request.playlist_ids, item.thumbnail) for item in api._queue.snapshot().items] == [
        (("a", "b"), "a.jpg"), (("c",), "c.jpg"),
    ]


def test_playlist_without_video_thumbnail_does_not_use_playlist_cover(api):
    result = api.enqueue({"items": [{"url": "https://youtube.com/playlist?list=PL", "thumbnail": "playlist.jpg"}]})
    assert result["ok"] and api._queue.wait_idle(5)
    assert api._queue.snapshot().items[0].thumbnail is None
