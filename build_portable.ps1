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
    --name BTToneSlapper `
    --paths "$Root" `
    --hidden-import ctypes.wintypes `
    --collect-all bleak `
    --collect-submodules winrt `
    --add-data "$Root\assets;assets" `
    "$Root\app.py"

if ($LASTEXITCODE -ne 0) {
    throw "Portable build failed"
}

$Exe = Join-Path $Root "dist\BTToneSlapper.exe"
$Hash = Get-FileHash $Exe -Algorithm SHA256
Write-Host "Built: $Exe"
Write-Host "SHA-256: $($Hash.Hash.ToLowerInvariant())"
