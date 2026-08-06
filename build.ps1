# build.ps1 - SpotterApp.exe build script
# Usage:  .\build.ps1
# Optional: set a specific interpreter via $env:SPOTTER_PYTHON before running.
#
# IMPORTANT: the build interpreter must have the FULL runtime stack installed
# (bottle, pywebview, pywin32, sounddevice, soundfile, piper-tts, onnxruntime,
# numpy, psutil, aiohttp, pandas) PLUS pyinstaller. PyInstaller bundles packages
# from whatever interpreter runs it, so all deps must live in ONE environment.

# --- Pick the build interpreter ---
$pyExe = $null
$pyArgs = @()
if ($env:SPOTTER_PYTHON) {
    $pyExe = $env:SPOTTER_PYTHON
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $pyExe = "py"; $pyArgs = @("-3.12")
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $pyExe = "python"
} else {
    Write-Host "ERROR: no Python found (tried py -3.12 and python)." -ForegroundColor Red
    exit 1
}
Write-Host ("Build interpreter: " + $pyExe + " " + ($pyArgs -join " ")) -ForegroundColor Cyan

# --- PyInstaller availability ---
& $pyExe @pyArgs -m PyInstaller --version 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: PyInstaller is not available in the build interpreter." -ForegroundColor Red
    Write-Host ("  " + $pyExe + " " + ($pyArgs -join " ") + " -m pip install pyinstaller") -ForegroundColor Yellow
    exit 1
}

# --- Runtime dependency gate (import names) ---
$deps = @("bottle","webview","win32gui","sounddevice","soundfile","piper",
          "onnxruntime","numpy","psutil","aiohttp","pandas","grpc","yandexcloud",
          "pyttsx3")
$pipName = @{ webview = "pywebview"; win32gui = "pywin32"; piper = "piper-tts"; grpc = "grpcio" }
$missing = @()
foreach ($pkg in $deps) {
    & $pyExe @pyArgs -c "import $pkg" 2>$null
    if ($LASTEXITCODE -ne 0) { $missing += $pkg }
}
if ($missing.Count -gt 0) {
    $pipPkgs = $missing | ForEach-Object { if ($pipName.ContainsKey($_)) { $pipName[$_] } else { $_ } }
    Write-Host "ERROR: missing runtime packages in the build interpreter:" -ForegroundColor Red
    Write-Host ("  " + ($missing -join ", ")) -ForegroundColor Yellow
    Write-Host "Install them into the SAME interpreter used for building:" -ForegroundColor Yellow
    Write-Host ("  " + $pyExe + " " + ($pyArgs -join " ") + " -m pip install " + ($pipPkgs -join " ")) -ForegroundColor Yellow
    exit 1
}

# --- Piper voices (offline fallback) must be present ---
$piperDir = Join-Path $PSScriptRoot "models\piper"
if (-not (Test-Path $piperDir)) {
    Write-Host "ERROR: Piper voices not found: models\piper" -ForegroundColor Red
    Write-Host "  Place ru_RU-*-medium.onnx (+ .json) voices into models\piper\" -ForegroundColor Yellow
    exit 1
}
$onnx = Get-ChildItem -Path $piperDir -Filter *.onnx -ErrorAction SilentlyContinue
if (-not $onnx) {
    Write-Host "ERROR: no .onnx voices found in models\piper" -ForegroundColor Red
    exit 1
}

# --- Track Intelligence JSON database must be present ---
$tracksDir = Join-Path $PSScriptRoot "tracks"
if (-not (Test-Path $tracksDir)) {
    Write-Host "ERROR: tracks/ not found - track AI will not work in EXE." -ForegroundColor Red
    Write-Host "  Create tracks/ with 24 F1 25 circuit JSON files." -ForegroundColor Yellow
    exit 1
}
$trackJson = Get-ChildItem -Path $tracksDir -Filter *.json -ErrorAction SilentlyContinue
if ($trackJson.Count -lt 20) {
    Write-Host ("WARNING: only " + $trackJson.Count + " track JSON files found (expected 24).") -ForegroundColor Yellow
}
Write-Host ("Track JSON: " + $trackJson.Count + " circuits found.") -ForegroundColor Green

# --- Build web UI (Next.js static export -> webui/) ---
# UI живёт в NewSpotterUI/ (Next.js 16 + React 19 + Tailwind v4). Собирается в out/
# и копируется в webui/, который PyInstaller вшивает в .exe (SpotterApp.spec).
# Node нужен ТОЛЬКО на сборке; конечному пользователю — нет.
$uiDir = Join-Path $PSScriptRoot "NewSpotterUI"
if (-not (Test-Path $uiDir)) {
    Write-Host "ERROR: NewSpotterUI/ not found - cannot build the web UI." -ForegroundColor Red
    exit 1
}
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Write-Host "ERROR: Node.js not found. Install Node 18+ to build the UI." -ForegroundColor Red
    exit 1
}
if (-not (Get-Command pnpm -ErrorAction SilentlyContinue)) {
    Write-Host "pnpm not found - installing globally via npm..." -ForegroundColor Yellow
    npm install -g pnpm@9 | Out-Null
}
Write-Host "Installing UI dependencies (pnpm install)..." -ForegroundColor Cyan
pnpm -C $uiDir install
if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: pnpm install failed." -ForegroundColor Red; exit 1 }
Write-Host "Building UI (pnpm build -> static export)..." -ForegroundColor Cyan
pnpm -C $uiDir build
if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: UI build failed." -ForegroundColor Red; exit 1 }
$uiOut = Join-Path $uiDir "out"
if (-not (Test-Path $uiOut)) { Write-Host "ERROR: UI export not found: $uiOut" -ForegroundColor Red; exit 1 }
$webui = Join-Path $PSScriptRoot "webui"
Write-Host "Syncing UI export -> webui/ ..." -ForegroundColor Cyan
robocopy $uiOut $webui /MIR /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { Write-Host "ERROR: failed to copy UI export to webui/." -ForegroundColor Red; exit 1 }
Write-Host "Web UI ready (webui/)." -ForegroundColor Green

Write-Host "Dependencies OK. Cleaning build artifacts (preserving user data in dist/)..." -ForegroundColor Cyan
# НЕ удаляем весь dist/: там пользовательские данные (yandex_creds.json — сохранённый
# API-ключ, tts_cache/, spotter.log). Сносим только сам EXE и build/. Onefile-сборка
# выдаёт единственный dist\SpotterApp.exe, поэтому этого достаточно для чистой пересборки.
Remove-Item -Recurse -Force build -ErrorAction SilentlyContinue
Remove-Item -Force "dist\SpotterApp.exe" -ErrorAction SilentlyContinue

Write-Host "Running PyInstaller..." -ForegroundColor Cyan
& $pyExe @pyArgs -m PyInstaller --clean --noconfirm SpotterApp.spec

if ($LASTEXITCODE -eq 0) {
    $exe = Get-Item "dist\SpotterApp.exe" -ErrorAction SilentlyContinue
    $mb  = if ($exe) { [math]::Round($exe.Length / 1MB) } else { "?" }
    Write-Host "Done! dist\SpotterApp.exe ($mb MB)" -ForegroundColor Green
    Write-Host "Yandex GPT/SpeechKit = primary (API key entered at runtime in Settings)." -ForegroundColor Cyan
    Write-Host "Piper voices bundled as offline fallback (models/piper)." -ForegroundColor Cyan
} else {
    Write-Host "Build failed! Exit code: $LASTEXITCODE" -ForegroundColor Red
    exit $LASTEXITCODE
}
