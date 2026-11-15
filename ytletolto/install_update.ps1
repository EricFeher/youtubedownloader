# Runs outside the app so Windows can release the executable and bundled DLLs.
$ErrorActionPreference = 'Stop'
$config = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'update.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$backup = Join-Path $PSScriptRoot 'backup'
$moved = @()
$installed = @()
try {
    # All mutations are confined to the app directory and this staging directory.
    $target = [IO.Path]::GetFullPath($config.target)
    $stage = [IO.Path]::GetFullPath($config.stage)
    $payload = [IO.Path]::GetFullPath($config.payload)
    if ($stage -ne $PSScriptRoot -or -not $stage.StartsWith($target + '\', [StringComparison]::OrdinalIgnoreCase) -or
        -not $payload.StartsWith($stage + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Invalid update paths' }
    foreach ($name in $config.names) {
        if ([IO.Path]::GetFileName($name) -ne $name -or $name -in @('.', '..')) { throw 'Invalid update filename' }
    }
    foreach ($processId in $config.pids) {
        $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
        if ($process) { $process | Wait-Process -Timeout 120 -ErrorAction Stop }
    }
    New-Item -ItemType Directory -Path $backup | Out-Null
    foreach ($name in $config.names) {
        $original = Join-Path $target $name
        # Antivirus scanners may briefly keep DLLs open after the app exits.
        for ($attempt = 0; ; $attempt++) {
            try { Move-Item -LiteralPath $original -Destination (Join-Path $backup $name); break }
            catch { if ($attempt -ge 19) { throw }; Start-Sleep -Milliseconds 500 }
        }
        $moved += $name
        Move-Item -LiteralPath (Join-Path $payload $name) -Destination $original
        $installed += $name
    }
    # PyInstaller's onefile bootloader must start a fresh extraction session.
    Remove-Item Env:_PYI_APPLICATION_HOME_DIR -ErrorAction SilentlyContinue
    Remove-Item Env:_PYI_PARENT_PROCESS_LEVEL -ErrorAction SilentlyContinue
    $env:PYINSTALLER_RESET_ENVIRONMENT = '1'
    Start-Process -FilePath (Join-Path $target $config.exe) -WorkingDirectory $target -WindowStyle Hidden
} catch {
    $failure = $_.Exception.Message
    try {
        foreach ($name in $installed) { Remove-Item -LiteralPath (Join-Path $target $name) -Recurse -Force }
        foreach ($name in $moved) { Move-Item -LiteralPath (Join-Path $backup $name) -Destination (Join-Path $target $name) }
    } catch { $failure += "`nRollback: " + $_.Exception.Message }
    Set-Content -LiteralPath (Join-Path $PSScriptRoot 'update-error.txt') -Value $failure -Encoding UTF8
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show("A frissítés nem sikerült. A korábbi verzió visszaállítása megtörtént, ha a fájlok elérhetők voltak. Részletek: $PSScriptRoot\update-error.txt", 'Media Minds Downloader') | Out-Null
    exit 1
}
Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue
