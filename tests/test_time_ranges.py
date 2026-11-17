import json
import os
import shutil
import subprocess
import sys
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from yt_dlp.utils import DownloadError

from ytletolto.download_queue import build_requests
from ytletolto.downloader import DownloadRequest, Downloader, Finished, Mode, Progress, Status, Thumbnail, Tools, build_ydl_opts
from ytletolto.i18n import TEXT, Message


@pytest.mark.parametrize("start,end", [(-1, 10), (10, 10), (20, 10), (float("nan"), 20),
                                       (0, float("inf")), (True, 10), (0, "20"), (None, 20)])
def test_invalid_ranges_are_rejected(start, end, tmp_path):
    with pytest.raises(ValueError):
        DownloadRequest("url", tmp_path, Mode.VIDEO, start_time=start, end_time=end)


def test_range_is_clamped_to_actual_duration_and_rejects_live_or_empty(tmp_path):
    request = DownloadRequest("url", tmp_path, Mode.VIDEO, start_time=10, end_time=50)
    opts = build_ydl_opts(request, Tools(None))
    ranges = opts["download_ranges"]
    assert ranges({"duration": 30}, None) == [{"start_time": 10, "end_time": 30}]
    assert opts["force_keyframes_at_cuts"] is True
    assert "section_start" in opts["outtmpl"]["default"]
    for info in ({"duration": 5}, {"is_live": True}):
        with pytest.raises(DownloadError):
            ranges(info, None)


def test_full_download_keeps_existing_encoding_and_filename(tmp_path):
    opts = build_ydl_opts(DownloadRequest("url", tmp_path, Mode.VIDEO), Tools(None))
    assert not opts.get("force_keyframes_at_cuts")
    assert not opts.get("external_downloader_args")
    assert opts["outtmpl"]["default"] == "%(title)s.%(ext)s"


def test_playlist_groups_preserve_individual_formats_ranges_and_ids(tmp_path):
    requests = build_requests("https://youtube.com/playlist?list=PL", {"quality": "1080"}, tmp_path, True, [
        {"id": "a", "options": {"start_time": 10, "end_time": 20, "quality": "720"}},
        {"id": "b", "options": {"mode": "audio", "audio_format": "opus", "start_time": 30, "end_time": 40}},
        {"id": "c", "options": {}},
        {"id": "d", "options": {}},
        {"id": "a", "options": {"start_time": 70}},
    ])
    assert len(requests) == 3
    video, audio, whole = requests
    assert (video.playlist_ids, video.max_height, video.start_time, video.end_time) == (("a",), 720, 10, 20)
    assert (audio.playlist_ids, audio.mode, audio.audio_format, audio.start_time, audio.end_time) == (("b",), Mode.AUDIO, "opus", 30, 40)
    assert (whole.playlist_ids, whole.max_height, whole.is_section) == (("c", "d"), 1080, False)


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture
def local_media(tmp_path):
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("A média-integrációs tesztekhez ffmpeg és ffprobe szükséges.")
    source = tmp_path / "source.mp4"
    subprocess.run([
        ffmpeg, "-v", "error", "-f", "lavfi", "-i", "testsrc=size=128x72:rate=20:duration=4",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=4", "-c:v", "libx264", "-g", "60",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart", str(source),
    ], check=True, capture_output=True)
    subprocess.run([ffmpeg, "-v", "error", "-i", str(source), "-c:v", "libvpx-vp9", "-c:a", "libopus", str(tmp_path / "source.webm")], check=True, capture_output=True)
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(tmp_path)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/source.mp4", Path(ffmpeg).parent, ffprobe
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize("mode,audio_format,container", [
    (Mode.VIDEO, "mp3", "mp4"), (Mode.VIDEO, "mp3", "mkv"), (Mode.VIDEO, "mp3", "webm"),
    (Mode.AUDIO, "mp3", "mp4"), (Mode.AUDIO, "opus", "mp4"), (Mode.AUDIO, "m4a", "mp4"), (Mode.AUDIO, "wav", "mp4"),
])
def test_real_section_download_produces_selected_duration(local_media, tmp_path, mode, audio_format, container):
    url, ffmpeg_dir, ffprobe = local_media
    if mode is Mode.VIDEO and container == "mp4":
        url = url.replace("source.mp4", "source.webm")
    request = DownloadRequest(url, tmp_path / "out", mode, audio_format=audio_format, container=container, start_time=1, end_time=2.5)
    events = []
    Downloader(events.append, Tools(ffmpeg_dir)).run(request)
    result = events[-1]
    assert isinstance(result, Finished) and result.ok, events
    # A borító már az ffmpeg befejezése előtti metaadat-lekéréskor megérkezik.
    assert next(i for i, event in enumerate(events) if isinstance(event, Thumbnail)) < next(
        i for i, event in enumerate(events) if isinstance(event, Progress)
    )
    assert len(result.files) == 1
    path = Path(result.files[0])
    assert path.is_file() and "000001.000-000002.500" in path.name
    assert path.parent == request.output_dir
    assert list(request.output_dir.iterdir()) == [path]
    assert path.suffix == "." + (container if mode is Mode.VIDEO else audio_format)
    info = json.loads(subprocess.check_output([ffprobe, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)]))
    assert float(info["format"]["duration"]) == pytest.approx(1.5, abs=0.2)
    assert any(s["codec_type"] == "video" for s in info["streams"]) is (mode is Mode.VIDEO)
    assert any(s["codec_type"] == "audio" for s in info["streams"])


@pytest.mark.parametrize("mode", [Mode.VIDEO, Mode.AUDIO])
@pytest.mark.parametrize("relative", [False, True])
def test_real_full_download_preserves_final_file_and_removes_workspace(local_media, tmp_path, monkeypatch, mode, relative):
    url, ffmpeg_dir, ffprobe = local_media
    monkeypatch.chdir(tmp_path)
    request = DownloadRequest(url, Path("out") if relative else tmp_path / "out", mode)
    events = []
    Downloader(events.append, Tools(ffmpeg_dir)).run(request)
    result = events[-1]
    assert isinstance(result, Finished) and result.ok, events
    assert len(result.files) == 1
    path = Path(result.files[0])
    assert path.parent == request.output_dir.resolve()
    assert list(request.output_dir.resolve().iterdir()) == [path]
    info = json.loads(subprocess.check_output([ffprobe, "-v", "error", "-show_format", "-of", "json", str(path)]))
    assert float(info["format"]["duration"]) == pytest.approx(4, abs=0.2)


def _worker_with_child(request, tools, events, temp_dir):
    if os.name != "nt":
        os.setsid()
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    events.put(Status(str(child.pid)))
    child.wait()


@pytest.mark.skipif(os.name == "nt", reason="POSIX folyamatcsoport ellenőrzése")
def test_cancellation_stops_worker_and_its_child(monkeypatch, tmp_path):
    from ytletolto import section_worker

    monkeypatch.setattr(section_worker, "_run", _worker_with_child)
    cancel = threading.Event()
    children = []

    def emit(event):
        if isinstance(event, Status):
            children.append(int(event.text))
            cancel.set()

    started = time.monotonic()
    result = section_worker.download_section(DownloadRequest("url", tmp_path, Mode.VIDEO, end_time=10), Tools(None), emit, cancel)
    assert not result.ok
    assert isinstance(result.message, Message) and result.message.key == TEXT.DOWNLOAD_CANCELLED
    assert time.monotonic() - started < 8
    assert len(children) == 1
    process = subprocess.run(["ps", "-o", "stat=", "-p", str(children[0])], capture_output=True, text=True)
    assert not process.stdout.strip() or process.stdout.strip().startswith("Z")
