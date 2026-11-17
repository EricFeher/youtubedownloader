from pathlib import Path

import pytest
import yt_dlp

from ytletolto import downloader, settings
from ytletolto.downloader import Tools, available_qualities, probe, quality_key, quality_tier, summarize, storyboard_preview

TOOLS = Tools(ffmpeg_dir=Path("/opt/ffmpeg"))


def test_storyboards_use_extractor_timing_and_partial_final_sheet():
    from yt_dlp.extractor.youtube import YoutubeIE

    # Ten frames in 2x2 sheets, including a final sheet with two empty cells.
    spec = "https://i.ytimg.com/sb/test/storyboard$L/$N.jpg?sqp=x|160#90#10#2#2#12000#M$M#signature"
    response = {"storyboards": {"playerStoryboardSpecRenderer": {"spec": spec}}}
    formats = list(YoutubeIE(yt_dlp.YoutubeDL({"quiet": True}))._extract_storyboard([response], 120))
    board = summarize({"duration": 120, "formats": formats}).storyboard

    assert (board.width, board.height, board.columns, board.rows, board.fps) == (160, 90, 2, 2, 1 / 12)
    assert [(sheet.start, sheet.duration, sheet.frame_count) for sheet in board.sheets] == [
        (0, 48, 4), (48, 48, 4), (96, 24, 2),
    ]
    assert "M2.jpg" in board.sheets[-1].url


def test_storyboard_chooses_largest_complete_track_and_survives_missing_data():
    small = {"protocol": "mhtml", "width": 80, "height": 45, "rows": 2, "columns": 2, "fps": 0.1,
             "fragments": [{"url": "https://img/small.jpg", "duration": 40}]}
    large = {**small, "width": 160, "height": 90}
    broken = {**large, "width": 320, "fragments": [*large["fragments"], {"duration": 40}]}
    assert storyboard_preview({"formats": [large, small, broken]}).width == 160
    assert storyboard_preview({}) is None
    assert summarize({"_type": "playlist", "formats": [large]}).storyboard is None


@pytest.mark.parametrize("changes", [
    {"fps": None}, {"fps": 0}, {"fps": float("nan")}, {"columns": 0}, {"height": None},
    {"fragments": []}, {"fragments": [{"url": "file:///private", "duration": 10}]},
    {"fragments": [{"url": "https://img/frame.jpg", "duration": float("inf")}]},
])
def test_invalid_storyboards_do_not_break_video_metadata(changes):
    fmt = {"protocol": "mhtml", "width": 160, "height": 90, "rows": 2, "columns": 2, "fps": 0.1,
           "fragments": [{"url": "https://img/frame.jpg", "duration": 40}], **changes}
    result = summarize({"title": "Video", "duration": 120, "formats": [fmt]})
    assert result.title == "Video"
    assert result.storyboard is None


def fmt(format_id, ext, width, height, vcodec, acodec="none", fps=30, size=None):
    return {
        "format_id": format_id, "url": f"https://media/{format_id}", "ext": ext, "protocol": "https",
        "width": width, "height": height, "fps": fps, "vcodec": vcodec, "acodec": acodec, "filesize": size,
    }


# Egy YouTube-videó formátumai kicsiben: AV1 és H.264 MP4-ben, VP9 WebM-ben, külön hangsávok.
YOUTUBE_FORMATS = [
    fmt("401", "mp4", 3840, 2160, "av01.0.13M.08", fps=60, size=700),
    fmt("315", "webm", 3840, 2160, "vp9", fps=60, size=1300),
    fmt("299", "mp4", 1920, 1080, "avc1.64002A", fps=60, size=250),
    fmt("399", "mp4", 1920, 1080, "av01.0.09M.08", fps=60, size=120),
    fmt("303", "webm", 1920, 1080, "vp9", fps=60, size=160),
    fmt("135", "mp4", 854, 480, "avc1.4D401F", size=28),
    fmt("244", "webm", 854, 480, "vp9", size=33),
    fmt("140", "m4a", None, None, "none", "mp4a.40.2", fps=None, size=10),
    fmt("251", "webm", None, None, "none", "opus", fps=None, size=12),
    fmt("sb0", "mhtml", 320, 180, "none", fps=None),  # előnézeti képkockák, nem videó
]


@pytest.fixture
def processed():
    """A yt-dlp-vel feldolgozott info dict, ahogy a probe is kapja; a választást ugyanez a példány futtatja."""
    ydl = yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True})
    raw = {"id": "x", "title": "Klip", "extractor": "youtube", "extractor_key": "Youtube",
           "webpage_url": "https://youtu.be/x", "formats": [dict(f) for f in YOUTUBE_FORMATS]}
    return ydl, ydl.process_ie_result(raw, download=False)


def tiers(qualities):
    return [(q.tier, q.fps, q.size) for q in qualities]


@pytest.mark.parametrize(("width", "height", "tier"), [
    (1920, 1080, 1080),
    (854, 480, 480),  # nem pontosan 16:9
    (1080, 1920, 1080),  # függőleges (Shorts)
    (1920, 800, 1080),  # szélesvásznú film
    (1280, 534, 720),
    (1440, 1080, 1080),  # 4:3
    (7680, 4320, 4320),
    (None, 2160, 2160),
    (None, None, None),
])
def test_quality_tier_classifies_by_shorter_side_and_16_9_width(width, height, tier):
    assert quality_tier(width, height) == tier


def test_quality_key_ignores_compatible_for_webm():
    assert quality_key("mp4", False) == "mp4"
    assert quality_key("mkv", True) == "mkv-compatible"
    assert quality_key("webm", True) == "webm"


def test_available_qualities_match_what_the_download_would_pick(processed):
    ydl, info = processed

    result = available_qualities(ydl, info, TOOLS)

    assert set(result) == {"mp4", "mkv", "webm", "mp4-compatible", "mkv-compatible"}
    # MP4: a legjobb kodek (AV1, ahol nincs, VP9) + AAC hang; a méret a két sáv összege.
    assert tiers(result["mp4"]) == [(2160, 60, 710), (1080, 60, 130), (480, 30, 43)]
    # H.264 a YouTube-on legfeljebb 1080p, így a 4K itt nem választható.
    assert tiers(result["mp4-compatible"]) == [(1080, 60, 260), (480, 30, 38)]
    # WebM: VP9 + Opus.
    assert tiers(result["webm"]) == [(2160, 60, 1312), (1080, 60, 172), (480, 30, 45)]


def test_available_qualities_skip_tiers_the_download_would_not_give(processed):
    ydl, info = processed
    # Csak 4K és 480p H.264: 4K-ra kérve is H.264-et választana, 1080p tehát nincs.
    info["formats"] = [f for f in info["formats"] if f["format_id"] not in ("299", "399", "303")]

    assert [q.tier for q in available_qualities(ydl, info, TOOLS)["mp4"]] == [2160, 480]


def test_probe_returns_qualities_and_survives_a_failing_selector(processed, monkeypatch):
    _, info = processed
    monkeypatch.setattr(yt_dlp.YoutubeDL, "extract_info", lambda self, url, download: info)

    assert probe("https://youtu.be/x", TOOLS).qualities["mkv"][0].tier == 2160

    def broken(*args):
        raise KeyError("format_sort")

    monkeypatch.setattr(downloader, "available_qualities", broken)
    result = probe("https://youtu.be/x", TOOLS)
    assert (result.title, result.max_height, result.qualities) == ("Klip", 2160, {})


def test_summarize_video_uses_highest_video_format():
    info = {
        "title": "Klip",
        "uploader": "Csatorna",
        "thumbnail": "https://img/thumb.jpg",
        "duration": 213.6,
        "formats": [
            {"height": 1080, "vcodec": "avc1"},
            {"width": 2160, "height": 3840, "vcodec": "vp9"},  # függőleges 4K
            {"height": None, "vcodec": "none"},
        ],
    }

    result = summarize(info)

    assert (result.kind, result.title, result.uploader) == ("video", "Klip", "Csatorna")
    assert result.duration == 213
    assert result.max_height == 2160


def test_summarize_playlist_falls_back_to_first_entry_thumbnail():
    info = {
        "_type": "playlist",
        "title": "Lista",
        "channel": "Csatorna",
        "playlist_count": 12,
        "entries": [{"thumbnails": [{"url": "https://img/small.jpg"}, {"url": "https://img/big.jpg"}]}],
    }

    result = summarize(info)

    assert (result.kind, result.count, result.uploader) == ("playlist", 12, "Csatorna")
    assert result.thumbnail == "https://img/big.jpg"


def test_summarize_playlist_lists_entries_with_their_position():
    info = {
        "_type": "playlist",
        "title": "Lista",
        "entries": [
            {"id": "a", "title": "Első", "duration": 61.9, "thumbnails": [{"url": "https://img/a-small.jpg"}, {"url": "https://img/a-big.jpg"}]},
            None,  # elérhetetlen elem: a sorszáma foglalt marad
            {"id": "c", "title": None},
        ],
    }

    entries = summarize(info).entries

    assert [(e.index, e.id, e.title) for e in entries] == [(1, "a", "Első"), (3, "c", "c")]
    assert (entries[0].duration, entries[0].thumbnail) == (61, "https://img/a-small.jpg")
    assert (entries[1].duration, entries[1].thumbnail) == (None, None)


def test_summarize_channel_tabs_offer_no_per_item_choice():
    # Csatorna linkjénél az elemek a csatorna fülei (Videók, Shorts…), mind a csatorna azonosítójával.
    tab = {"_type": "playlist", "id": "UC1", "title": "Csatorna - Videos"}
    info = {"_type": "playlist", "title": "Csatorna", "entries": [tab, {**tab, "title": "Csatorna - Shorts"}]}

    assert summarize(info).entries == ()
    assert summarize({**info, "entries": [{"_type": "url", "ie_key": "YoutubeTab", "id": "PL1"}]}).entries == ()
    assert len(summarize({**info, "entries": [{"_type": "url", "ie_key": "Youtube", "id": "v"}]}).entries) == 1


def test_summarize_video_has_no_entries():
    assert summarize({"title": "Klip"}).entries == ()


def test_settings_roundtrip_ignores_unknown_keys(tmp_path):
    path = tmp_path / "settings.json"
    settings.save({"output_dir": str(tmp_path), "mode": "audio", "quality": "1080", "compatible": True, "container": "mkv", "audio_format": "opus", "x": 1}, path)

    loaded = settings.load(path)

    assert loaded == {"language": "system", "output_dir": str(tmp_path), "mode": "audio", "quality": "1080", "compatible": True, "container": "mkv", "audio_format": "opus"}


def test_settings_fall_back_to_defaults_when_missing_or_broken(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{nem json", encoding="utf-8")

    loaded = settings.load(path)

    assert loaded["mode"] == "video"
    assert loaded["output_dir"] == str(settings.default_output_dir())


def test_settings_replace_deleted_output_dir(tmp_path):
    path = tmp_path / "settings.json"
    settings.save({"output_dir": str(tmp_path / "torolt")}, path)

    assert settings.load(path)["output_dir"] == str(settings.default_output_dir())


@pytest.mark.parametrize("language,expected", [("en", "en"), ("hu", "hu"), ("de", "system"), (None, "system"), ({}, "system")])
def test_language_is_persisted_and_unsupported_values_fall_back(tmp_path, language, expected):
    path = tmp_path / "settings.json"
    settings.save({"language": language}, path)
    assert settings.load(path)["language"] == expected


@pytest.mark.parametrize("locale,expected", [("hu_HU", "hu"), ("hu-HU", "hu"), ("HU-hu", "hu"),
                                          ("en_US", "en"), ("en-GB", "en"), ("de_DE", "en"), (None, "en")])
def test_first_launch_uses_system_language_without_pinning_it(tmp_path, monkeypatch, locale, expected):
    path = tmp_path / "settings.json"
    monkeypatch.setattr(settings, "system_locale", lambda: locale)
    loaded = settings.load(path)
    assert settings.resolve_language(loaded["language"]) == expected
    settings.save(loaded, path)
    monkeypatch.setattr(settings, "system_locale", lambda: "hu_HU" if expected == "en" else "en_US")
    assert settings.resolve_language(settings.load(path)["language"]) != expected


@pytest.mark.parametrize("manual", ["hu", "en"])
def test_saved_language_overrides_system_language(tmp_path, monkeypatch, manual):
    path = tmp_path / "settings.json"
    settings.save({"language": manual}, path)
    monkeypatch.setattr(settings, "system_locale", lambda: "en_US" if manual == "hu" else "hu_HU")
    assert settings.resolve_language(settings.load(path)["language"]) == manual


def test_unavailable_system_locale_uses_english(monkeypatch):
    monkeypatch.setattr(settings.locale, "getlocale", lambda: (_ for _ in ()).throw(ValueError("no locale")))
    monkeypatch.setattr(settings.sys, "platform", "linux")
    for name in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        monkeypatch.delenv(name, raising=False)
    assert settings.resolve_language("system") == "en"


def test_windows_uses_display_language_instead_of_regional_format(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(settings.sys, "platform", "win32")
    monkeypatch.setattr(settings.ctypes, "windll", SimpleNamespace(
        kernel32=SimpleNamespace(GetUserDefaultUILanguage=lambda: 0x040E)), raising=False)
    monkeypatch.setattr(settings.locale, "getlocale", lambda: ("en_US", "UTF-8"))
    assert settings.resolve_language("system") == "hu"


def test_macos_uses_first_preferred_display_language(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(settings.sys, "platform", "darwin")
    monkeypatch.setattr(settings.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(stdout='(\n "hu-HU",\n "en-US"\n)'))
    assert settings.resolve_language("system") == "hu"


def test_linux_uses_message_locale(monkeypatch):
    monkeypatch.setattr(settings.sys, "platform", "linux")
    monkeypatch.delenv("LANGUAGE", raising=False)
    monkeypatch.delenv("LC_ALL", raising=False)
    monkeypatch.setenv("LC_MESSAGES", "hu_HU.UTF-8")
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    assert settings.resolve_language("system") == "hu"
