from pathlib import Path

import pytest
import yt_dlp

from ytletolto.downloader import (
    Downloader,
    DownloadRequest,
    Finished,
    Mode,
    Progress,
    Tools,
    build_ydl_opts,
    find_tools,
    split_by_mode,
)

TOOLS = Tools(ffmpeg_dir=Path("/opt/ffmpeg"), js_runtimes={"deno": {"path": r"C:\app\deno.exe"}})


def request(**overrides) -> DownloadRequest:
    return DownloadRequest(**{"url": "https://youtu.be/x", "output_dir": Path("/out"), "mode": Mode.VIDEO, **overrides})


def pp_keys(opts: dict) -> list[str]:
    return [pp["key"] for pp in opts["postprocessors"]]


def test_video_best_quality_merges_to_mp4():
    opts = build_ydl_opts(request(), TOOLS)

    assert opts["format"] == "bestvideo+bestaudio[acodec^=mp4a]/bestvideo+bestaudio/best"
    assert opts["format_sort"] == ["hdr:sdr"]
    assert opts["merge_output_format"] == "mp4"
    assert opts["noplaylist"] is True
    assert {"FFmpegVideoRemuxer", "FFmpegMetadata", "EmbedThumbnail"} <= set(pp_keys(opts))
    assert "FFmpegExtractAudio" not in pp_keys(opts)


def test_video_height_cap_and_compat_mode():
    opts = build_ydl_opts(request(max_height=1080, compatible=True), TOOLS)

    assert opts["format_sort"] == ["hdr:sdr", "vcodec:h264", "res:1080"]


def test_mkv_takes_best_audio_of_any_codec():
    opts = build_ydl_opts(request(container="mkv"), TOOLS)

    assert opts["format"] == "bestvideo+bestaudio/best"
    assert opts["merge_output_format"] == "mkv"
    assert "EmbedThumbnail" in pp_keys(opts)


def test_mkv_compat_mode_keeps_aac():
    opts = build_ydl_opts(request(container="mkv", compatible=True), TOOLS)

    assert opts["format"].startswith("bestvideo+bestaudio[acodec^=mp4a]")
    assert "vcodec:h264" in opts["format_sort"]


def test_webm_prefers_webm_streams_and_falls_back_to_mkv():
    opts = build_ydl_opts(request(container="webm", compatible=True, max_height=720), TOOLS)

    assert opts["format"].startswith("bestvideo[ext=webm]+bestaudio[ext=webm]")
    assert opts["merge_output_format"] == "webm/mkv"
    assert opts["format_sort"] == ["hdr:sdr", "res:720"]  # H.264 nem fér WebM-be
    assert "EmbedThumbnail" not in pp_keys(opts)  # a yt-dlp WebM-be nem tud borítót tenni


def test_unknown_container_is_rejected():
    with pytest.raises(ValueError):
        build_ydl_opts(request(container="avi"), TOOLS)


def test_audio_extracts_320k_mp3():
    opts = build_ydl_opts(request(mode=Mode.AUDIO), TOOLS)

    assert opts["format"] == "bestaudio/best"
    extract = next(pp for pp in opts["postprocessors"] if pp["key"] == "FFmpegExtractAudio")
    assert extract["preferredcodec"] == "mp3"
    assert extract["preferredquality"] == "320"
    assert opts["merge_output_format"] is None


def test_m4a_and_opus_prefer_matching_source_stream():
    m4a = build_ydl_opts(request(mode=Mode.AUDIO, audio_format="m4a"), TOOLS)
    opus = build_ydl_opts(request(mode=Mode.AUDIO, audio_format="opus"), TOOLS)

    assert m4a["format"] == "bestaudio[ext=m4a]/bestaudio/best"
    assert opus["format"] == "bestaudio[acodec=opus]/bestaudio/best"
    for opts, codec in ((m4a, "m4a"), (opus, "opus")):
        extract = next(pp for pp in opts["postprocessors"] if pp["key"] == "FFmpegExtractAudio")
        assert extract["preferredcodec"] == codec
        assert "EmbedThumbnail" in pp_keys(opts)


def test_wav_skips_thumbnail():
    opts = build_ydl_opts(request(mode=Mode.AUDIO, audio_format="wav"), TOOLS)

    extract = next(pp for pp in opts["postprocessors"] if pp["key"] == "FFmpegExtractAudio")
    assert extract["preferredcodec"] == "wav"
    assert "EmbedThumbnail" not in pp_keys(opts)


def test_unknown_audio_format_is_rejected():
    with pytest.raises(ValueError):
        build_ydl_opts(request(mode=Mode.AUDIO, audio_format="flac"), TOOLS)


def test_paths_tools_and_playlist_template():
    opts = build_ydl_opts(request(playlist=True), TOOLS)

    assert opts["paths"] == {"home": "/out"}
    assert opts["ffmpeg_location"] == "/opt/ffmpeg"
    assert opts["js_runtimes"] == {"deno": {"path": r"C:\app\deno.exe"}}
    assert opts["noplaylist"] is False
    assert "playlist_index" in opts["outtmpl"]["default"]
    assert opts["windowsfilenames"] is True


def test_find_tools_prefers_bundled_binaries(tmp_path, monkeypatch):
    monkeypatch.setattr("ytletolto.downloader.os.name", "posix")
    for name in ("ffmpeg", "deno"):
        (tmp_path / name).touch()

    tools = find_tools(tmp_path)

    assert tools.ffmpeg_dir == tmp_path
    assert tools.js_runtimes == {"deno": {"path": str(tmp_path / "deno")}}


def test_missing_ffmpeg_reports_error_without_downloading():
    events = []
    Downloader(events.append, Tools(ffmpeg_dir=None)).run(request())

    assert len(events) == 1
    assert isinstance(events[0], Finished) and not events[0].ok
    assert "ffmpeg" in events[0].message


def test_playlist_items_are_passed_to_yt_dlp():
    opts = build_ydl_opts(request(playlist=True, playlist_items=(1, 3, 7)), TOOLS)

    assert opts["playlist_items"] == "1,3,7"


def test_playlist_items_are_ignored_for_single_video():
    opts = build_ydl_opts(request(playlist_items=(1, 3)), TOOLS)

    assert opts.get("playlist_items") is None


def test_split_by_mode_groups_items_and_defaults_to_video():
    base = request(playlist=True, mode=Mode.AUDIO)
    items = [
        {"index": 3, "mode": "audio"},
        {"index": 1, "mode": "video"},
        {"index": 2},  # mód nélkül: videó
        {"index": 5, "mode": "audio"},
        {"index": 1, "mode": "audio"},  # ismétlődő sorszám: az első számít
        {"index": 0, "mode": "audio"},  # érvénytelen
        {"index": True, "mode": "audio"},  # érvénytelen
        "szemét",
    ]

    video, audio = split_by_mode(base, items)

    assert (video.mode, video.playlist_items) == (Mode.VIDEO, (1, 2))
    assert (audio.mode, audio.playlist_items) == (Mode.AUDIO, (3, 5))
    assert video.playlist and audio.playlist


def test_split_by_mode_skips_empty_group():
    (only,) = split_by_mode(request(playlist=True), [{"index": 1, "mode": "audio"}, {"index": 2, "mode": "audio"}])

    assert (only.mode, only.playlist_items) == (Mode.AUDIO, (1, 2))


def test_split_by_mode_keeps_request_without_items():
    single = request()
    whole_list = request(playlist=True, mode=Mode.AUDIO)

    assert split_by_mode(single, [{"index": 1, "mode": "audio"}]) == [single]
    assert split_by_mode(whole_list, None) == [whole_list]
    assert split_by_mode(whole_list, []) == []


class FakeYDL(yt_dlp.YoutubeDL):
    """A yt-dlp helyett: minden kért elemre jelent egy kész letöltést és egy áthelyezett fájlt.

    Alosztály, mert a `parse_options` is a `yt_dlp.YoutubeDL` osztálymetódusait hívja.
    """

    runs: list[dict] = []

    def __init__(self, opts: dict):
        self.opts = opts
        FakeYDL.runs.append(opts)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def download(self, url_list):
        indexes = [int(i) for i in self.opts["playlist_items"].split(",")]
        for number, index in enumerate(indexes, start=1):
            info = {"playlist_index": index, "playlist_autonumber": number, "n_entries": len(indexes), "vcodec": "none"}
            self.opts["progress_hooks"][0]({"status": "finished", "filename": f"{index}.x", "info_dict": info})
            self.opts["postprocessor_hooks"][0]({"status": "finished", "postprocessor": "MoveFiles", "info_dict": {"filepath": f"/out/{index}"}})
        return 0


def test_run_downloads_video_and_audio_items_in_sequence(monkeypatch, tmp_path):
    monkeypatch.setattr("ytletolto.downloader.yt_dlp.YoutubeDL", FakeYDL)
    FakeYDL.runs = []
    events = []
    base = request(playlist=True, output_dir=tmp_path)
    requests = split_by_mode(base, [{"index": 1}, {"index": 2, "mode": "audio"}, {"index": 3}])

    Downloader(events.append, TOOLS).run(*requests)

    assert [opts["playlist_items"] for opts in FakeYDL.runs] == ["1,3", "2"]
    assert "FFmpegExtractAudio" not in pp_keys(FakeYDL.runs[0])
    assert "FFmpegExtractAudio" in pp_keys(FakeYDL.runs[1])
    progress = [(e.item, e.mode) for e in events if isinstance(e, Progress)]
    assert progress == [("1/3", "video"), ("2/3", "video"), ("3/3", "audio")]
    assert events[-1] == Finished(True, "Kész!", ("/out/1", "/out/3", "/out/2"))

