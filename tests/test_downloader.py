import os
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
    Thumbnail,
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
    download = request(playlist=True)
    opts = build_ydl_opts(download, TOOLS)

    assert opts["paths"] == {"home": str(download.output_dir)}
    assert opts["ffmpeg_location"] == str(TOOLS.ffmpeg_dir)
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


@pytest.mark.parametrize("prefix", ["/opt/homebrew/bin", "/usr/local/bin", "/custom/bin"])
@pytest.mark.parametrize("runtime", ["deno", "node"])
def test_find_tools_from_finder_finds_homebrew(tmp_path, monkeypatch, prefix, runtime):
    monkeypatch.setattr("ytletolto.downloader.sys.platform", "darwin")
    monkeypatch.setenv("PATH", os.pathsep.join(("/custom/bin", "/usr/bin", "/bin")))
    binaries = {f"{prefix}/ffmpeg", f"{prefix}/{runtime}"}
    if prefix == "/custom/bin":
        binaries.update({"/opt/homebrew/bin/ffmpeg", f"/opt/homebrew/bin/{runtime}"})

    def which(name, *, path):
        return next((f"{directory}/{name}" for directory in path.split(os.pathsep)
                     if f"{directory}/{name}" in binaries), None)

    monkeypatch.setattr("ytletolto.downloader.shutil.which", which)

    tools = find_tools(tmp_path)

    assert tools.ffmpeg_dir == Path(prefix)
    assert tools.js_runtimes == {runtime: {"path": str(Path(prefix) / runtime)}}


def test_missing_ffmpeg_reports_error_without_downloading():
    events = []
    Downloader(events.append, Tools(ffmpeg_dir=None)).run(request())

    assert len(events) == 1
    assert isinstance(events[0], Finished) and not events[0].ok
    assert "ffmpeg" in events[0].message


def items(*pairs: tuple[str, str]) -> list[dict]:
    return [{"id": video_id, "mode": mode} for video_id, mode in pairs]


def test_split_by_mode_groups_items_by_id_and_defaults_to_video():
    base = request(playlist=True, mode=Mode.AUDIO)
    payload = [
        {"id": "c", "mode": "audio"},
        {"id": "a", "mode": "video"},
        {"id": "b"},  # mód nélkül: videó
        {"id": "e", "mode": "audio"},
        {"id": "e", "mode": "audio"},  # ismétlődő elem: egyszer
        {"id": "", "mode": "audio"},  # érvénytelen
        {"id": 5, "mode": "audio"},  # érvénytelen
        "szemét",
    ]

    video, audio = split_by_mode(base, payload)

    assert (video.mode, video.playlist_ids) == (Mode.VIDEO, ("a", "b"))
    assert (audio.mode, audio.playlist_ids) == (Mode.AUDIO, ("c", "e"))
    assert video.playlist and audio.playlist


def test_split_by_mode_filters_selection_when_all_items_share_a_mode():
    (whole,) = split_by_mode(request(playlist=True), items(("a", "audio"), ("b", "audio")))

    assert (whole.mode, whole.playlist_ids) == (Mode.AUDIO, ("a", "b"))


def test_split_by_mode_keeps_request_without_items():
    single = request()
    whole_list = request(playlist=True, mode=Mode.AUDIO)

    assert split_by_mode(single, items(("a", "audio"), ("b", "video"))) == [single]
    assert split_by_mode(whole_list, None) == [whole_list]
    assert split_by_mode(whole_list, 5) == [whole_list]  # hibás adat a felületről
    assert split_by_mode(whole_list, [{"id": ""}]) == []
    assert split_by_mode(whole_list, []) == []


def test_selected_ids_become_a_match_filter():
    (video, _) = split_by_mode(request(playlist=True), items(("a", "video"), ("b", "audio")))

    match = build_ydl_opts(video, TOOLS)["match_filter"]

    assert match({"playlist_id": "PL", "playlist_index": 0}, incomplete=True) is None  # maga a lista
    assert match({"id": "a"}, incomplete=True) is None  # a yt-dlp lapozás közbeni előszűrése, sorszám nélkül
    assert match({"id": "a", "playlist_index": 1}, incomplete=True) is None
    assert match({"id": "a", "playlist_index": 1}) is None  # teljes adatokkal újra ellenőrzi
    assert match({"id": "b", "playlist_index": 2}, incomplete=True)
    assert match({"id": "a", "playlist_index": 7}, incomplete=True)  # ugyanaz a videó később újra


def test_whole_list_and_single_video_have_no_match_filter():
    assert build_ydl_opts(request(playlist=True), TOOLS).get("match_filter") is None
    assert build_ydl_opts(request(playlist_ids=("a",)), TOOLS).get("match_filter") is None


def test_video_thumbnail_is_emitted_before_download_only_for_selected_complete_video():
    events = []
    downloader = Downloader(events.append, TOOLS)
    match = downloader._cancellable(build_ydl_opts(request(playlist=True, playlist_ids=("a",)), TOOLS)["match_filter"])
    match({"id": "a", "thumbnail": "incomplete.jpg"}, incomplete=True)
    match({"id": "b", "thumbnail": "not-selected.jpg"})
    assert events == []
    match({"id": "a", "thumbnail": "a.jpg"})
    assert events == [Thumbnail("a.jpg")]


def test_thumbnail_without_selection_uses_video_metadata_and_clears_missing_image():
    events = []
    match = Downloader(events.append, TOOLS)._cancellable(None)
    match({"id": "a", "thumbnails": [{"url": "small.jpg"}, {"url": "large.jpg"}]})
    match({"id": "b"})
    assert events == [Thumbnail("large.jpg"), Thumbnail(None)]


class FakeYDL(yt_dlp.YoutubeDL):
    """A yt-dlp helyett: a `PLAYLIST` elemeiből a szűrőn átjutókra jelent egy letöltést és egy kész fájlt.

    Alosztály, mert a `parse_options` is a `yt_dlp.YoutubeDL` osztálymetódusait hívja.
    """

    PLAYLIST: list[str] = []
    runs: list[dict] = []

    def __init__(self, opts: dict):
        self.opts = opts
        FakeYDL.runs.append(opts)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def download(self, url_list):
        # A yt-dlp előbb az egész listára futtatja a szűrőt (azonosító nélkül), aztán az elemekre.
        if self.opts["match_filter"]({"playlist_id": "PL", "playlist_index": 0}, incomplete=True) is not None:
            return 0
        for index, video_id in enumerate(self.PLAYLIST, start=1):
            if self.opts["match_filter"]({"id": video_id}, incomplete=True) is not None:  # lapozás közbeni előszűrés
                continue
            info = {"id": video_id, "playlist_id": "PL", "playlist_index": index, "n_entries": len(self.PLAYLIST), "vcodec": "none"}
            if self.opts["match_filter"](info, incomplete=True) is not None:
                continue
            for status in ("downloading", "finished"):
                self.opts["progress_hooks"][0]({"status": status, "filename": f"{index}.x", "info_dict": info})
            self.opts["postprocessor_hooks"][0]({"status": "finished", "postprocessor": "MoveFiles", "info_dict": {"filepath": f"/out/{video_id}"}})
        return 0


def test_run_downloads_video_and_audio_items_by_id(monkeypatch, tmp_path):
    monkeypatch.setattr("ytletolto.downloader.yt_dlp.YoutubeDL", FakeYDL)
    FakeYDL.runs = []
    # Az előnézet óta egy új videó ("uj") került a lista elejére, és "a" kétszer is szerepel.
    FakeYDL.PLAYLIST = ["uj", "a", "b", "c", "a"]
    events = []
    base = request(playlist=True, output_dir=tmp_path)
    requests = split_by_mode(base, items(("a", "video"), ("b", "audio"), ("c", "video")))

    Downloader(events.append, TOOLS).run(*requests)

    assert [r.playlist_ids for r in requests] == [("a", "c"), ("b",)]
    assert "FFmpegExtractAudio" not in pp_keys(FakeYDL.runs[0])
    assert "FFmpegExtractAudio" in pp_keys(FakeYDL.runs[1])
    progress = [(e.item, e.mode) for e in events if isinstance(e, Progress)]
    assert progress == [("1/3", "video")] * 2 + [("2/3", "video")] * 2 + [("3/3", "audio")] * 2
    assert events[-1] == Finished(True, "Kész!", ("/out/a", "/out/c", "/out/b"))


def test_cancel_stops_while_skipping_unselected_items(monkeypatch, tmp_path):
    monkeypatch.setattr("ytletolto.downloader.yt_dlp.YoutubeDL", FakeYDL)
    FakeYDL.runs = []
    FakeYDL.PLAYLIST = ["a", "b", "c"]
    events = []
    downloader = Downloader(events.append, TOOLS)
    requests = split_by_mode(request(playlist=True, output_dir=tmp_path), items(("a", "video"), ("c", "audio")))
    downloader.cancel()  # pl. a második menet lapozása közben nyomták meg

    downloader.run(*requests)

    assert not any(isinstance(e, Progress) for e in events)
    assert events[-1] == Finished(False, "Letöltés megszakítva.", ())


def test_single_mode_selection_skips_other_playlist_items(monkeypatch, tmp_path):
    monkeypatch.setattr("ytletolto.downloader.yt_dlp.YoutubeDL", FakeYDL)
    FakeYDL.runs = []
    FakeYDL.PLAYLIST = ["uj", "a", "b", "c"]
    events = []
    requests = split_by_mode(request(playlist=True, output_dir=tmp_path), items(("b", "video")))

    Downloader(events.append, TOOLS).run(*requests)

    assert events[-1] == Finished(True, "Kész!", ("/out/b",))
