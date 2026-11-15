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
