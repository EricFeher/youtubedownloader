from ytletolto import settings
from ytletolto.downloader import summarize


def test_summarize_video_uses_highest_video_format():
    info = {
        "title": "Klip",
        "uploader": "Csatorna",
        "thumbnail": "https://img/thumb.jpg",
        "duration": 213.6,
        "formats": [
            {"height": 1080, "vcodec": "avc1"},
            {"height": 2160, "vcodec": "vp9"},
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


def test_summarize_video_has_no_entries():
    assert summarize({"title": "Klip"}).entries == ()


def test_settings_roundtrip_ignores_unknown_keys(tmp_path):
    path = tmp_path / "settings.json"
    settings.save({"output_dir": str(tmp_path), "mode": "audio", "quality": "1080", "compatible": True, "container": "mkv", "audio_format": "opus", "x": 1}, path)

    loaded = settings.load(path)

    assert loaded == {"output_dir": str(tmp_path), "mode": "audio", "quality": "1080", "compatible": True, "container": "mkv", "audio_format": "opus"}


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
