import sys
from pathlib import Path

import pytest

import build


@pytest.mark.parametrize("onefile,flavor", [(False, "onedir"), (True, "onefile")])
@pytest.mark.parametrize("fail", [False, True])
def test_build_stamps_version_and_restores_source(tmp_path, monkeypatch, onefile, flavor, fail):
    metadata = tmp_path / "ytletolto/_build.py"
    metadata.parent.mkdir()
    metadata.write_text("VERSION = 'source-original'\n")
    original = metadata.read_bytes()
    monkeypatch.setattr(build, "ROOT", tmp_path)
    monkeypatch.setattr(build, "vendor_binaries", lambda: [])
    monkeypatch.setattr(sys, "argv", ["build.py", "--no-fetch", "--version", "v2.3.4"] + (["--onefile"] if onefile else []))
    monkeypatch.setenv("GITHUB_REPOSITORY", "Example/downloader")
    calls = []
    def package(args):
        namespace = {}
        exec(metadata.read_text(), namespace)
        assert namespace["VERSION"] == "2.3.4"
        assert namespace["FLAVOR"] == flavor
        assert namespace["REPOSITORY"] == "Example/downloader"
        assert any("install_update.ps1" in arg for arg in args)
        if sys.platform == "win32":
            assert Path(args[args.index("--version-file") + 1]).is_file()
        calls.append(args)
        if fail:
            raise RuntimeError("Build failed")
    monkeypatch.setattr(build.PyInstaller.__main__, "run", package)
    if fail:
        with pytest.raises(RuntimeError):
            build.main()
    else:
        build.main()
    assert len(calls) == 1
    assert metadata.read_bytes() == original


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PE resources")
@pytest.mark.parametrize("version", ["1.2.3", "v1.2.3"])
def test_windows_version_resource_round_trips(tmp_path, monkeypatch, version):
    from PyInstaller.utils.win32.versioninfo import VSVersionInfo, load_version_info_from_text_file

    monkeypatch.setattr(build, "ROOT", tmp_path)
    resource = load_version_info_from_text_file(str(build.windows_version_file(version)))
    decoded = VSVersionInfo()
    decoded.fromRaw(resource.toRaw())
    strings = {item.name: item.val for item in decoded.kids[0].kids[0].kids}
    assert strings["ProductName"] == build.APP_NAME
    assert strings["OriginalFilename"] == f"{build.APP_NAME}.exe"
    assert strings["ProductVersion"] == strings["FileVersion"] == "1.2.3"
    assert decoded.ffi.fileVersionMS == (1 << 16) | 2
    assert decoded.ffi.fileVersionLS == 3 << 16


def test_windows_version_resource_rejects_unrepresentable_version(tmp_path, monkeypatch):
    monkeypatch.setattr(build, "ROOT", tmp_path)
    with pytest.raises(ValueError, match="65535"):
        build.windows_version_file("1.65536.0")
