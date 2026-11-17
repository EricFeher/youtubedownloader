import hashlib
import io
import json
import os
import subprocess
import sys
import urllib.error
import zipfile
from pathlib import Path

import pytest

from ytletolto import APP_NAME, updater


def release(package=b"MZnew executable", flavor="onefile", version="v1.2.0"):
    return {
        "tag_name": version, "body": "## Újdonságok\n- Frissítés az alkalmazásból.",
        "published_at": "2026-11-15T10:00:00Z", "draft": False, "prerelease": False,
        "assets": [{"name": {"onefile": "Media.Minds.Downloader.exe", "onedir": "MediaMindsDownloader-windows.zip"}[flavor], "state": "uploaded", "size": len(package),
                    "digest": "sha256:" + hashlib.sha256(package).hexdigest(),
                    "browser_download_url": f"https://github.com/{updater.REPOSITORY}/releases/download/{version}/app"}],
    }


@pytest.fixture
def packaged(tmp_path, monkeypatch):
    monkeypatch.setattr(updater.sys, "frozen", True, raising=False)
    monkeypatch.setattr(updater.sys, "executable", str(tmp_path / "App.exe"))
    monkeypatch.setattr(updater, "FLAVOR", "onefile")
    monkeypatch.setattr(updater, "VERSION", "1.1.0")
    instance = updater.Updater()
    # Keep this fixture portable on non-Windows CI.
    instance._state["supported"] = True
    yield instance
    instance.close()


def serve(monkeypatch, metadata, package=b"MZnew executable"):
    calls = []
    def get(url):
        calls.append(url)
        return io.BytesIO(json.dumps(metadata).encode() if url.endswith("/latest") else package)
    monkeypatch.setattr(updater, "_get", get)
    return calls


@pytest.mark.parametrize("version,available", [("v1.2.0", True), ("v1.10.0", True), ("v1.1.0", False), ("v1.0.0", False)])
def test_release_check_uses_numeric_version_and_notes(packaged, monkeypatch, version, available):
    metadata = release(version=version)
    calls = serve(monkeypatch, metadata)
    state = packaged.check()
    assert state["available"] is available
    assert state["notes"] == metadata["body"]
    assert state["current_version"] == "1.1.0"
    assert len(calls) == 1


@pytest.mark.parametrize("value", ["v1.2.0-beta", "1.2", "1.02.0", "v1.2.3.4", "garbage"])
def test_rejects_invalid_version(value):
    with pytest.raises(ValueError):
        updater.version_tuple(value)


@pytest.mark.parametrize("failure", [OSError("offline"), urllib.error.HTTPError("url", 404, "missing", {}, None),
                                       urllib.error.HTTPError("url", 403, "rate limit", {}, None)])
def test_network_failure_is_visible_and_retryable(packaged, monkeypatch, failure):
    monkeypatch.setattr(updater, "_get", lambda url: (_ for _ in ()).throw(failure))
    assert packaged.check()["status"] == "error"
    serve(monkeypatch, release())
    assert packaged.check()["status"] == "available"


@pytest.mark.parametrize("change", [{"prerelease": True}, {"draft": True}, {"tag_name": "v1.2.0-beta"}])
def test_ignores_nonstable_release(packaged, monkeypatch, change):
    serve(monkeypatch, release() | change)
    assert packaged.check()["status"] == "error"
    assert not packaged.snapshot()["available"]


def test_download_verifies_and_stages_without_touching_current_app(packaged, monkeypatch, tmp_path):
    current = tmp_path / "App.exe"
    current.write_bytes(b"old")
    calls = serve(monkeypatch, release())
    packaged.check()
    state = packaged.download()
    assert state["status"] == "ready"
    assert (packaged._payload / "App.exe").read_bytes() == b"MZnew executable"
    assert current.read_bytes() == b"old"
    packaged.check()
    packaged.download()
    assert len(calls) == 2  # ready payload is retained; no duplicate requests
    stage = packaged._stage
    packaged.close()
    assert not stage.exists()


@pytest.mark.parametrize("field,value", [("digest", None), ("digest", "sha256:" + "0" * 64),
    ("size", 1), ("size", 10000), ("browser_download_url", "https://evil.example/app.exe"),
    ("browser_download_url", f"http://github.com/{updater.REPOSITORY}/releases/download/v1.2.0/app")])
def test_bad_assets_never_become_installable(packaged, monkeypatch, tmp_path, field, value):
    metadata = release()
    metadata["assets"][0][field] = value
    serve(monkeypatch, metadata)
    packaged.check()
    assert packaged.download()["status"] == "error"
    assert not list(tmp_path.glob(".mm-update-*"))
    with pytest.raises(ValueError):
        packaged.launch_installer()


def bundle(extra=None):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(f"{APP_NAME}/{APP_NAME}.exe", b"MZnew executable")
        archive.writestr(f"{APP_NAME}/_internal/runtime.dll", b"new runtime")
        if extra:
            archive.writestr(extra, b"bad")
    return output.getvalue()


def test_folder_bundle_is_verified_and_extracted(packaged, monkeypatch):
    monkeypatch.setattr(updater, "FLAVOR", "onedir")
    package = bundle()
    serve(monkeypatch, release(package, "onedir"), package)
    packaged.check()
    assert packaged.download()["status"] == "ready"
    assert (packaged._payload / "_internal/runtime.dll").read_bytes() == b"new runtime"


@pytest.mark.parametrize("path", [f"{APP_NAME}/../../escape", "/absolute", f"{APP_NAME}/C:evil", f"{APP_NAME}\\..\\escape"])
def test_rejects_zip_traversal(packaged, monkeypatch, path):
    monkeypatch.setattr(updater, "FLAVOR", "onedir")
    package = bundle(path)
    serve(monkeypatch, release(package, "onedir"), package)
    packaged.check()
    assert packaged.download()["status"] == "error"
    assert packaged._payload is None


def test_busy_updater_does_not_start_another_operation(packaged, monkeypatch):
    calls = serve(monkeypatch, release())
    with packaged._lock:
        packaged.check()
        packaged.download()
    assert calls == []


def test_source_build_cannot_install(monkeypatch):
    monkeypatch.setattr(updater, "FLAVOR", "source")
    instance = updater.Updater()
    serve(monkeypatch, release())
    assert instance.check()["available"]
    assert not instance.download()["supported"]
    assert instance._stage is None


def test_missing_asset_explains_unavailable_package(packaged, monkeypatch):
    serve(monkeypatch, release() | {"assets": []})
    packaged.check()
    state = packaged.download()
    assert state["status"] == "error"
    assert "does not have" in state["error"]


def test_closing_during_download_discards_staging(packaged, monkeypatch, tmp_path):
    serve(monkeypatch, release())
    packaged.check()
    class ClosingResponse(io.BytesIO):
        def read(self, size=-1):
            packaged.close()
            return super().read(size)
    monkeypatch.setattr(updater, "_get", lambda url: ClosingResponse(b"MZnew executable"))
    assert packaged.download()["status"] == "error"
    assert not list(tmp_path.glob(".mm-update-*"))


@pytest.mark.skipif(sys.platform != "win32", reason="Windows helper")
def test_failed_helper_launch_can_retry_with_renamed_folder_exe(packaged, monkeypatch):
    monkeypatch.setattr(updater, "FLAVOR", "onedir")
    package = bundle()
    serve(monkeypatch, release(package, "onedir"), package)
    packaged.check()
    packaged.download()
    def fail(*args, **kwargs):
        raise OSError("blocked helper")
    monkeypatch.setattr(updater.subprocess, "Popen", fail)
    with pytest.raises(OSError):
        packaged.launch_installer()
    assert packaged.snapshot()["status"] == "ready"
    monkeypatch.setattr(updater.subprocess, "Popen", lambda *args, **kwargs: None)
    packaged.launch_installer()
    assert packaged.snapshot()["status"] == "installing"
    packaged._cleanup()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows helper")
def test_launch_helper_keeps_verified_payload_and_uses_hidden_process(packaged, monkeypatch):
    serve(monkeypatch, release())
    packaged.check()
    packaged.download()
    launches = []
    monkeypatch.setattr(updater.subprocess, "Popen", lambda args, **kwargs: launches.append((args, kwargs)))
    packaged.launch_installer()
    assert packaged.snapshot()["status"] == "installing"
    stage = packaged._stage
    config = json.loads((stage / "update.json").read_text())
    assert config["pids"] == [os.getpid(), os.getppid()]
    assert config["names"] == ["App.exe"]
    assert launches[0][1]["creationflags"] == subprocess.CREATE_NO_WINDOW
    packaged.close()
    assert stage.exists()
    # Test owns the staged fixture; no actual helper was launched.
    packaged._cleanup()


@pytest.mark.skipif(sys.platform != "win32", reason="Real PowerShell file replacement")
@pytest.mark.parametrize("flavor", ["onefile", "onedir"])
@pytest.mark.parametrize("fail_restart", [False, True])
def test_windows_helper_replaces_or_rolls_back_only_app_files(tmp_path, flavor, fail_restart):
    target = tmp_path / "Alkalmazás [teszt] ' & space"
    stage = target / ".mm-update-test"
    payload = stage / "payload"
    payload.mkdir(parents=True)
    (target / "App.exe").write_bytes(b"old exe")
    (payload / "App.exe").write_bytes(b"new exe")
    (target / "user-video.mp4").write_bytes(b"keep")
    names = ["App.exe"]
    if flavor == "onedir":
        names.append("_internal")
        for base, data in [(target, b"old dll"), (payload, b"new dll")]:
            (base / "_internal").mkdir()
            (base / "_internal/runtime.dll").write_bytes(data)
    config = {"target": str(target), "stage": str(stage), "payload": str(payload), "exe": "App.exe", "names": names, "pids": []}
    (stage / "update.json").write_text(json.dumps(config), encoding="utf-8")
    helper = (Path(updater.__file__).parent / "install_update.ps1").read_text(encoding="utf-8")
    # Replace only UI/process boundaries; execute the actual replacement and rollback code.
    helper = helper.replace("    Add-Type -AssemblyName System.Windows.Forms", "    # test: no dialog")
    helper = "\n".join(line for line in helper.splitlines() if "MessageBox]::Show" not in line)
    stub = "function Start-Process { throw 'simulated restart failure' }\n" if fail_restart else "function Start-Process { }\n"
    script = stage / "install.ps1"
    script.write_text(stub + helper, encoding="utf-8-sig")
    process = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script)], capture_output=True, text=True, timeout=30)
    assert process.returncode == (1 if fail_restart else 0), process.stderr
    assert (target / "App.exe").read_bytes() == (b"old exe" if fail_restart else b"new exe")
    assert (target / "user-video.mp4").read_bytes() == b"keep"
    if flavor == "onedir":
        assert (target / "_internal/runtime.dll").read_bytes() == (b"old dll" if fail_restart else b"new dll")
    assert stage.exists() is fail_restart
