from pathlib import Path

import pytest

from ytletolto.downloader import (
    Downloader,
    DownloadRequest,
    Finished,
    Mode,
    Tools,
    build_ydl_opts,
    find_tools,
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

