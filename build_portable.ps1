$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$Venv = Join-Path $Root ".venv"
$Python = Join-Path $Venv "Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    python -m venv $Venv
    if ($LASTEXITCODE -ne 0) {
        throw "Could not create the local build environment"
    }
}

& $Python -m pip install `
    --disable-pip-version-check `
    --requirement "$Root\requirements-build.txt"
if ($LASTEXITCODE -ne 0) {
    throw "Could not install the pinned build requirements"
}

& $Python -m PyInstaller `
    --clean `
    --noconfirm `
    --onefile `
    --windowed `
    --name ToneSlapper `
    --icon "$Root\assets\icons\app_icon.ico" `
    --paths "$Root" `
    --exclude-module tkinter `
    --hidden-import ctypes.wintypes `
    --collect-all bleak `
    --collect-submodules winrt `
    --add-data "$Root\assets\ffmpeg.exe;assets" `
    --add-data "$Root\assets\LzmaAlone.exe;assets" `
    --add-data "$Root\assets\icons;assets\icons" `
    --add-data "$Root\assets\fonts;assets\fonts" `
    --add-data "$Root\LICENSE;." `
    --add-data "$Root\ATTRIBUTION.md;." `
    --add-data "$Root\THIRD_PARTY.md;." `
    "$Root\app.py"

if ($LASTEXITCODE -ne 0) {
    throw "Portable build failed"
}

$Exe = Join-Path $Root "dist\ToneSlapper.exe"
$Hash = Get-FileHash $Exe -Algorithm SHA256
Write-Host "Built: $Exe"
Write-Host "SHA-256: $($Hash.Hash.ToLowerInvariant())"
