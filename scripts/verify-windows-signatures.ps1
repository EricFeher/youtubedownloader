param(
    [Parameter(Mandatory = $true)]
    [string]$Root
)

$ErrorActionPreference = 'Stop'
$paths = @(
    'Media Minds Downloader.exe',
    'Media Minds Downloader/Media Minds Downloader.exe'
)
$signer = $null
foreach ($relativePath in $paths) {
    $path = Join-Path $Root $relativePath
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Missing signed executable: $path"
    }
    $signature = Get-AuthenticodeSignature -LiteralPath $path
    if ($signature.Status -ne 'Valid' -or $signature.SignatureType -ne 'Authenticode' -or
        $null -eq $signature.SignerCertificate) {
        throw "Invalid Authenticode signature: $path ($($signature.Status))"
    }
    if ($null -eq $signature.TimeStamperCertificate) {
        throw "Missing signature timestamp: $path"
    }
    if ($null -ne $signer -and $signer -ne $signature.SignerCertificate.Thumbprint) {
        throw 'The release executables must have the same signing certificate.'
    }
    $signer = $signature.SignerCertificate.Thumbprint
    Write-Host "Verified: $relativePath ($($signature.SignerCertificate.Subject))"
}
