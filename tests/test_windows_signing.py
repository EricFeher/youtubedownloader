"""Exercise the release signature gate without needing a production signing key."""

import base64
import os
import subprocess
import sys
from pathlib import Path

import pytest


pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows Authenticode gate")
VERIFY_SCRIPT = Path(__file__).resolve().parents[1] / "scripts/verify-windows-signatures.ps1"
POWERSHELL = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"


@pytest.mark.parametrize("mode,expected", [
    ("valid", None),
    ("missing", "Missing signed executable"),
    ("unsigned", "Invalid Authenticode signature"),
    ("tampered", "Invalid Authenticode signature"),
    ("catalog", "Invalid Authenticode signature"),
    ("no-certificate", "Invalid Authenticode signature"),
    ("no-timestamp", "Missing signature timestamp"),
    ("different-signer", "same signing certificate"),
])
def test_signature_gate(tmp_path, mode, expected):
    for relative in ("Media Minds Downloader.exe", "Media Minds Downloader/Media Minds Downloader.exe"):
        path = tmp_path / relative
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b"MZtest")
    if mode == "missing":
        path.unlink()
    # Mock only the Windows trust API; run the actual file checks and gate logic.
    command = r"""
$ErrorActionPreference = 'Stop'
$global:signingTestChecks = 0
function Get-AuthenticodeSignature {
    param([string]$LiteralPath)
    $global:signingTestChecks++
    $signature = [pscustomobject]@{
        Status = 'Valid'
        SignatureType = 'Authenticode'
        SignerCertificate = [pscustomobject]@{ Thumbprint = 'publisher'; Subject = 'CN=Publisher' }
        TimeStamperCertificate = [pscustomobject]@{ Subject = 'CN=Timestamp' }
    }
    if ($global:signingTestChecks -eq 2) {
        switch ($env:SIGNING_TEST_MODE) {
            'unsigned' { $signature.Status = 'NotSigned' }
            'tampered' { $signature.Status = 'HashMismatch' }
            'catalog' { $signature.SignatureType = 'Catalog' }
            'no-certificate' { $signature.SignerCertificate = $null }
            'no-timestamp' { $signature.TimeStamperCertificate = $null }
            'different-signer' { $signature.SignerCertificate.Thumbprint = 'other-publisher' }
        }
    }
    return $signature
}
& $env:SIGNING_VERIFY_SCRIPT -Root $env:SIGNING_TEST_ROOT
if ($global:signingTestChecks -ne 2) { throw 'Both executables must be verified.' }
"""
    result = run_powershell(command, tmp_path, mode)
    if expected is None:
        assert result.returncode == 0, result.stdout + result.stderr
    else:
        assert result.returncode != 0
        assert expected in result.stdout + result.stderr


def run_powershell(command, root, mode=""):
    return subprocess.run(
        [str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-EncodedCommand", base64.b64encode(command.encode("utf-16-le")).decode("ascii")],
        env={**os.environ, "SIGNING_TEST_ROOT": str(root), "SIGNING_TEST_MODE": mode,
             "SIGNING_VERIFY_SCRIPT": str(VERIFY_SCRIPT)},
        capture_output=True, text=True, timeout=30,
    )


def test_real_unsigned_file_is_rejected(tmp_path):
    (tmp_path / "Media Minds Downloader.exe").write_bytes(b"MZunsigned executable")
    result = run_powershell(
        "$ErrorActionPreference = 'Stop'; & $env:SIGNING_VERIFY_SCRIPT -Root $env:SIGNING_TEST_ROOT", tmp_path,
    )
    assert result.returncode != 0
    assert "Invalid Authenticode signature" in result.stdout + result.stderr
