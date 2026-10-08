# Builds the Windows installer:
#   1. freezes the Python backend into a single exe (PyInstaller) -> app/src-tauri/binaries
#   2. builds the Tauri app and bundles everything into an .msi
# Output: app/src-tauri/target/release/bundle/msi/*.msi
# Native tools (pip, cargo) write progress to stderr; failures are caught via exit codes in Check.
$ErrorActionPreference = "Continue"
$root = $PSScriptRoot
Set-Location $root

function Check($what) { if ($LASTEXITCODE -ne 0) { throw "$what falhou (codigo $LASTEXITCODE)" } }

$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { py -3.13 -m venv (Join-Path $root ".venv"); Check "criar venv" }
& $py -m pip install -q -r requirements.txt pyinstaller; Check "pip install"

Write-Host "==> testes" -ForegroundColor Cyan
& $py -m pytest -q; Check "testes"

Write-Host "==> backend (PyInstaller)" -ForegroundColor Cyan
$triple = ((rustc -vV) | Select-String "^host:").ToString().Split(" ")[1]
$pkg = Join-Path $root "goblin_yapper"
$tts = Join-Path $root "tts_server"  # only its code is bundled; the voice runtime installs on first use
& $py -m PyInstaller --noconfirm --clean --onefile --noconsole `
    --name "goblin-yapper-server-$triple" `
    --add-data "$pkg\web;goblin_yapper\web" `
    --add-data "$pkg\default_config.toml;goblin_yapper" `
    --add-data "$tts\server.py;tts_server" --add-data "$tts\audio.py;tts_server" `
    --add-data "$tts\requirements.txt;tts_server" --add-data "$tts\engines\*.py;tts_server\engines" `
    --distpath (Join-Path $root "app\src-tauri\binaries") `
    --workpath (Join-Path $root "build") --specpath (Join-Path $root "build") `
    (Join-Path $root "run_server.py")
Check "PyInstaller"

Write-Host "==> app (Tauri + MSI)" -ForegroundColor Cyan
Push-Location (Join-Path $root "app")
try {
    npm install --no-fund --no-audit; Check "npm install"
    npx tauri build; Check "tauri build"
} finally { Pop-Location }

Get-ChildItem (Join-Path $root "app\src-tauri\target\release\bundle\msi\*.msi") | ForEach-Object { Write-Host "MSI: $($_.FullName)" -ForegroundColor Green }
