from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest
import yt_dlp
from yt_dlp.utils import DownloadError

from ytletolto.downloader import DownloadRequest, Downloader, Finished, Log, Mode, Progress, Tools


@pytest.fixture
def local_video(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "video.mp4").write_bytes(b"x" * 1024 * 1024)
    (source / "playlist.m3u8").write_text(
        "#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:10\n"
        "#EXTINF:10,\nvideo.mp4\n#EXTINF:10,\nvideo.mp4\n#EXT-X-ENDLIST\n", encoding="utf-8",
    )
    handler = partial(SimpleHTTPRequestHandler, directory=str(source))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/video.mp4"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize("filename", ["video.mp4", "playlist.m3u8"])
def test_cancelled_http_download_removes_partial_files(local_video, tmp_path, filename):
    output = tmp_path / "out"
    output.mkdir()
    existing = output / "previous.mp4.part"
    existing.write_bytes(b"keep")
    events = []

    def emit(event):
        events.append(event)
        if isinstance(event, Progress) and event.percent != 100:
            downloader.cancel()

    downloader = Downloader(emit, Tools(ffmpeg_dir=Path("/ffmpeg")))
    downloader.run(DownloadRequest(local_video.replace("video.mp4", filename), output, Mode.VIDEO))

    assert events[-1] == Finished(False, "Download cancelled.")
    assert list(output.iterdir()) == [existing]
    assert existing.read_bytes() == b"keep"


@pytest.mark.parametrize("mode", [Mode.VIDEO, Mode.AUDIO])
@pytest.mark.parametrize("outcome", ["cancel", "error"])
@pytest.mark.parametrize("existing", ["absent", "empty", "nonempty"])
def test_failed_playlist_removes_only_new_empty_destination(local_video, tmp_path, monkeypatch, mode, outcome, existing):
    output = tmp_path / "out"
    output.mkdir()
    playlist = output / "Test playlist"
    unrelated = output / "Unrelated empty folder"
    unrelated.mkdir()
    if existing != "absent":
        playlist.mkdir()
    if existing == "nonempty":
        (playlist / "previous.mp4").write_bytes(b"keep")
    events = []

    class LocalPlaylistYDL(yt_dlp.YoutubeDL):
        def download(self, urls):
            self.process_ie_result({
                "_type": "playlist", "id": "PL", "title": "Test playlist", "extractor": "test", "extractor_key": "Test",
                "entries": [{"id": "video", "title": "Video", "url": local_video,
                             "ext": "mp4", "extractor": "test", "extractor_key": "Test"}],
            })
            return self._download_retcode

    def emit(event):
        events.append(event)
        if isinstance(event, Progress):
            assert playlist.is_dir()
            if outcome == "error":
                raise DownloadError("test download error")
            downloader.cancel()

    monkeypatch.setattr("ytletolto.downloader.yt_dlp.YoutubeDL", LocalPlaylistYDL)
    downloader = Downloader(emit, Tools(ffmpeg_dir=Path("/ffmpeg")))
    downloader.run(DownloadRequest("local-playlist", output, mode, playlist=True))

    assert isinstance(events[-1], Finished) and not events[-1].ok
    if outcome == "cancel":
        assert "cancelled" in events[-1].message
    else:
        assert any(isinstance(event, Log) and "test download error" in event.text for event in events)
    assert playlist.exists() is (existing != "absent")
    assert unrelated.is_dir() and output.is_dir()
    assert not list(output.glob(".mm-download-*"))
    if existing == "nonempty":
        assert (playlist / "previous.mp4").read_bytes() == b"keep"


def test_application_exit_waits_for_cancelled_download_cleanup(local_video, tmp_path):
    output = tmp_path / "out"
    script = """
import sys
sys.path.insert(0, sys.argv[1])
import threading
import time
from pathlib import Path
from ytletolto.download_queue import DownloadQueue, ItemEvent
from ytletolto.downloader import DownloadRequest, Downloader, Mode, Progress, Tools

ready, closing = threading.Event(), threading.Event()
def emit(event):
    if isinstance(event, ItemEvent) and isinstance(event.event, Progress):
        ready.set()
        closing.wait(5)
        time.sleep(0.2)

queue = DownloadQueue(emit, lambda emit: Downloader(emit, Tools(ffmpeg_dir=Path('/ffmpeg'))))
queue.add(DownloadRequest(sys.argv[2], Path(sys.argv[3]), Mode.VIDEO))
assert ready.wait(10)
queue.shutdown()
closing.set()
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(Path(__file__).resolve().parents[1]), local_video, str(output)],
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert output.is_dir()
    assert list(output.iterdir()) == []


@pytest.mark.parametrize("outcome", ["cancel", "download_error", "unexpected_error", "return_error", "success"])
def test_cleans_all_intermediate_files_and_keeps_finished_playlist_items(monkeypatch, tmp_path, outcome):
    previous = tmp_path / "previous.mp4.part"
    previous.write_bytes(b"keep")
    finished = tmp_path / "Playlist" / "001 - Finished.mp4"
    events = []

    class WorkingYDL(yt_dlp.YoutubeDL):
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def download(self, urls):
            finished.parent.mkdir(parents=True, exist_ok=True)
            finished.write_bytes(b"finished video")
            self.opts["postprocessor_hooks"][0]({
                "status": "finished", "postprocessor": "MoveFiles", "info_dict": {"filepath": str(finished)},
            })
            workspace = Path(self.opts["paths"].get("temp", self.opts["paths"]["home"])) / "Playlist"
            workspace.mkdir(parents=True, exist_ok=True)
            for name in ("video.f137.mp4", "video.f140.m4a.part", "video.f140.m4a.ytdl",
                         "video.f140.m4a.part-Frag12", "video.temp.mp4", "video.webp"):
                (workspace / name).write_bytes(b"intermediate")
            if outcome == "cancel":
                downloader.cancel()
                self.opts["progress_hooks"][0]({"status": "downloading"})
            if outcome == "download_error":
                raise DownloadError("merge failed")
            if outcome == "unexpected_error":
                raise RuntimeError("unexpected")
            return 1 if outcome == "return_error" else 0

    def emit(event):
        # A befejezés jelzésekor a takarításnak már készen kell lennie.
        if isinstance(event, Finished):
            assert not list(tmp_path.glob(".mm-download-*"))
        events.append(event)

    monkeypatch.setattr("ytletolto.downloader.yt_dlp.YoutubeDL", WorkingYDL)
    downloader = Downloader(emit, Tools(ffmpeg_dir=Path("/ffmpeg")))
    downloader.run(DownloadRequest("url", tmp_path, Mode.VIDEO, playlist=True))

    assert events[-1].ok is (outcome == "success")
    assert events[-1].files == (str(finished),)
    assert sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()) == [
        "Playlist/001 - Finished.mp4", "previous.mp4.part",
    ]
    assert finished.read_bytes() == b"finished video"
    assert previous.read_bytes() == b"keep"


def _section_leaving_partial_files(request, tools, events, temp_dir):
    import os
    from ytletolto.downloader import Status

    if os.name != "nt":
        os.setsid()
    nested = temp_dir / "Playlist"
    nested.mkdir()
    if request.playlist:
        (request.output_dir / "Playlist").mkdir(exist_ok=True)
    # A fájl nyitva marad: a szülő csak a worker leállítása után törölheti Windows-on.
    with (nested / "video.mp4.part").open("wb") as stream:
        stream.write(b"partial video")
        stream.flush()
        events.put(Status("partial file ready"))
        if request.url == "cancel":
            time.sleep(30)


@pytest.mark.parametrize("outcome", ["cancel", "crash"])
@pytest.mark.parametrize("playlist", [False, True])
def test_section_parent_cleans_files_after_worker_is_stopped(monkeypatch, tmp_path, outcome, playlist):
    from ytletolto import section_worker
    from ytletolto.downloader import Status

    monkeypatch.setattr(section_worker, "_run", _section_leaving_partial_files)
    existing = tmp_path / "finished.mp4"
    existing.write_bytes(b"keep")
    cancel = threading.Event()
    events = []

    def emit(event):
        events.append(event)
        if outcome == "cancel" and isinstance(event, Status):
            cancel.set()

    result = section_worker.download_section(
        DownloadRequest(outcome, tmp_path, Mode.VIDEO, end_time=10, playlist=playlist), Tools(None), emit, cancel,
    )

    assert not result.ok
    assert any(isinstance(event, Status) and event.text == "partial file ready" for event in events)
    assert ("cancelled" if outcome == "cancel" else "unexpectedly") in result.message
    assert list(tmp_path.iterdir()) == [existing]
