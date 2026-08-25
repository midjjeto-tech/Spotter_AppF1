# build.ps1 - SpotterApp.exe build script
# Usage:  .\build.ps1
# Optional: set a specific interpreter via $env:SPOTTER_PYTHON before running.
#
# IMPORTANT: the build interpreter must have the FULL runtime stack installed
# (bottle, pywebview, pywin32, sounddevice, soundfile, piper-tts, onnxruntime,
# numpy, psutil, aiohttp) PLUS pyinstaller. PyInstaller bundles packages
# from whatever interpreter runs it, so all deps must live in ONE environment.

[CmdletBinding()]
param(
    [switch]$RequireInstaller,
    [switch]$RequireSigning
)

$signTool = $null
if ($RequireSigning) {
    if (-not $env:SPOTTER_SIGN_CERT_THUMBPRINT) {
        Write-Host "ERROR: SPOTTER_SIGN_CERT_THUMBPRINT is required for a signed build." -ForegroundColor Red
        exit 1
    }
    if (-not $env:SPOTTER_SIGN_TIMESTAMP_URL) {
        Write-Host "ERROR: SPOTTER_SIGN_TIMESTAMP_URL is required for a signed build." -ForegroundColor Red
        exit 1
    }
    if ($env:SPOTTER_SIGNTOOL) {
        $signTool = $env:SPOTTER_SIGNTOOL
    } else {
        $signCommand = Get-Command signtool.exe -ErrorAction SilentlyContinue
        if ($signCommand) { $signTool = $signCommand.Source }
    }
    if (-not $signTool -or -not (Test-Path -LiteralPath $signTool -PathType Leaf)) {
        Write-Host "ERROR: signtool.exe not found. Set SPOTTER_SIGNTOOL explicitly." -ForegroundColor Red
        exit 1
    }
}

function Invoke-SpotterCodeSign {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not $RequireSigning) { return }
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        Write-Host "ERROR: signing target not found: $Path" -ForegroundColor Red
        exit 1
    }

    & $signTool sign /sha1 $env:SPOTTER_SIGN_CERT_THUMBPRINT /fd SHA256 `
        /tr $env:SPOTTER_SIGN_TIMESTAMP_URL /td SHA256 $Path
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: code signing failed: $Path" -ForegroundColor Red
        exit $LASTEXITCODE
    }

    $signature = Get-AuthenticodeSignature -LiteralPath $Path
    if ($signature.Status -ne "Valid") {
        Write-Host "ERROR: invalid Authenticode signature on $Path ($($signature.Status))." -ForegroundColor Red
        exit 1
    }
    Write-Host "Signed: $Path" -ForegroundColor Green
}

# --- Pick the build interpreter ---
$pyExe = $null
$pyArgs = @()
if ($env:SPOTTER_PYTHON) {
    $pyExe = $env:SPOTTER_PYTHON
} elseif (Test-Path (Join-Path $PSScriptRoot ".venv\Scripts\python.exe")) {
    $pyExe = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
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
# pandas выбыл 2026-08-08 вместе с fastf1: его импортировал только удалённый
# analytics/openf1_loader.py (см. NOTICE и SpotterApp.spec).
$deps = @("bottle","webview","win32gui","sounddevice","soundfile","piper",
          "onnxruntime","numpy","psutil","aiohttp","grpc","yandexcloud",
          "pyttsx3","pycaw")
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

# --- Версия: config.py и установщик обязаны совпадать ---
# Единственный источник правды - config.APP_VERSION, но Inno Setup питоновский
# модуль прочитать не может, поэтому версия дублируется в SpotterApp.iss. Дубль
# без проверки означает, что пользователь однажды назовёт версию из установщика,
# а в логе будет стоять другая - и разбор начнётся с неверной сборки.
$verPy = (& $pyExe @pyArgs -c "import sys; sys.path.insert(0, r'$PSScriptRoot'); import config; print(config.APP_VERSION)")
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: не удалось прочитать config.APP_VERSION." -ForegroundColor Red
    exit 1
}
$verPy = "$verPy".Trim()
$issPath = Join-Path $PSScriptRoot "installer\SpotterApp.iss"
$packagePath = Join-Path $PSScriptRoot "NewSpotterUI\package.json"
$issHit = Select-String -Path $issPath -Pattern '^#define\s+AppVersion\s+"([^"]+)"'
if (-not $issHit) {
    Write-Host "ERROR: в $issPath не найден #define AppVersion." -ForegroundColor Red
    exit 1
}
$verIss = $issHit.Matches[0].Groups[1].Value
$windowsVersionHit = Select-String -Path $issPath -Pattern '^#define\s+WindowsVersion\s+"([^"]+)"'
if (-not $windowsVersionHit) {
    Write-Host "ERROR: в $issPath не найден #define WindowsVersion." -ForegroundColor Red
    exit 1
}
$windowsVersion = $windowsVersionHit.Matches[0].Groups[1].Value
$versionCore = ($verPy -split '-', 2)[0]
if ($versionCore -notmatch '^\d+\.\d+\.\d+$') {
    Write-Host "ERROR: APP_VERSION должен начинаться с major.minor.patch: $verPy" -ForegroundColor Red
    exit 1
}
$expectedWindowsVersion = "$versionCore.0"
$packageJson = Get-Content $packagePath -Raw | ConvertFrom-Json
$verUi = [string]$packageJson.version
if ($verPy -ne $verIss -or $verPy -ne $verUi -or $windowsVersion -ne $expectedWindowsVersion) {
    Write-Host "ERROR: версия разошлась." -ForegroundColor Red
    Write-Host ("  config.py:       " + $verPy) -ForegroundColor Yellow
    Write-Host ("  SpotterApp.iss:  " + $verIss) -ForegroundColor Yellow
    Write-Host ("  WindowsVersion:  " + $windowsVersion + " (expected " + $expectedWindowsVersion + ")") -ForegroundColor Yellow
    Write-Host ("  package.json:    " + $verUi) -ForegroundColor Yellow
    exit 1
}
Write-Host ("Версия " + $verPy + ": config.py, установщик, Windows metadata и UI совпадают.") -ForegroundColor Green

# --- Piper voices (offline fallback) must be present ---
$piperDir = Join-Path $PSScriptRoot "models\piper"
if (-not (Test-Path $piperDir)) {
    Write-Host "ERROR: Piper voices not found: models\piper" -ForegroundColor Red
    Write-Host "  Place ru_RU-*-medium.onnx (+ .json) voices into models\piper\" -ForegroundColor Yellow
    exit 1
}
$onnx = @(Get-ChildItem -Path $piperDir -Filter *.onnx -File -ErrorAction SilentlyContinue)
if (-not $onnx) {
    Write-Host "ERROR: no .onnx voices found in models\piper" -ForegroundColor Red
    exit 1
}

# --- Лицензионный гейт по голосам: строгий allowlist, не banlist ---
# В коммерческий дистрибутив разрешены только две проверенные CC0-модели.
# Любое новое имя обязано сначала получить отдельную лицензионную проверку.
$allowedVoiceNames = @("ru_RU-denis-medium", "ru_RU-dmitri-medium")
$actualVoiceNames = @($onnx | ForEach-Object { $_.BaseName })
$unexpectedVoices = @($actualVoiceNames | Where-Object { $_ -notin $allowedVoiceNames })
$missingVoices = @($allowedVoiceNames | Where-Object { $_ -notin $actualVoiceNames })
$missingVoiceMetadata = @($allowedVoiceNames | Where-Object {
    -not (Test-Path -LiteralPath (Join-Path $piperDir ("$_.onnx.json")) -PathType Leaf)
})
$orphanVoiceMetadata = @(Get-ChildItem -Path $piperDir -Filter *.onnx.json -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Name.Substring(0, $_.Name.Length - ".onnx.json".Length) -notin $allowedVoiceNames })
if ($unexpectedVoices -or $missingVoices -or $missingVoiceMetadata -or $orphanVoiceMetadata) {
    Write-Host "ERROR: набор Piper-голосов не совпадает с release allowlist." -ForegroundColor Red
    if ($unexpectedVoices) { Write-Host ("  unexpected: " + ($unexpectedVoices -join ", ")) -ForegroundColor Red }
    if ($missingVoices) { Write-Host ("  missing: " + ($missingVoices -join ", ")) -ForegroundColor Red }
    if ($missingVoiceMetadata) { Write-Host ("  missing metadata: " + ($missingVoiceMetadata -join ", ")) -ForegroundColor Red }
    if ($orphanVoiceMetadata) { Write-Host ("  orphan metadata: " + (($orphanVoiceMetadata.Name) -join ", ")) -ForegroundColor Red }
    Write-Host "  Разрешены только ru_RU-denis-medium и ru_RU-dmitri-medium (см. NOTICE)." -ForegroundColor Yellow
    exit 1
}

# --- CA-бандл Минцифры для строгой TLS-проверки GigaChat ---
# Бандл НЕ опциональный, вопреки прежней записи здесь. Проверено рукопожатием
# 2026-08-25: системное хранилище Windows на чистой машине отвечает
# `self-signed certificate in certificate chain` для ngw.devices.sberbank.ru и
# gigachat.devices.sberbank.ru — то есть ровно той ошибкой, которая убила
# GigaChat на весь заезд 08-19. С бандлом обе цепочки проверяются (эмитент
# Russian Trusted Sub CA).
#
# Отказ при этом БЕЗОПАСНЫЙ, но полный и молчаливый: приложение уходит на
# шаблоны и снаружи выглядит просто скучнее. Поэтому релизная сборка без
# бандла запрещена — иначе EXE уедет пользователю с заведомо мёртвым «мозгом».
$caBundle = Join-Path $PSScriptRoot "certs\gigachat_ca_bundle.pem"
if (Test-Path $caBundle) {
    Write-Host "GigaChat CA bundle: найден, TLS будет проверяться." -ForegroundColor Green
} elseif ($RequireSigning) {
    Write-Host "ERROR: certs\gigachat_ca_bundle.pem отсутствует." -ForegroundColor Red
    Write-Host "  Без него GigaChat в собранном приложении не подключится вовсе:" -ForegroundColor Red
    Write-Host "  цепочка НУЦ Минцифры не входит в системное хранилище Windows." -ForegroundColor Red
    Write-Host "  Собрать: python scripts/setup_gigachat_certs.py" -ForegroundColor Red
    exit 1
} else {
    Write-Host "GigaChat CA bundle: НЕ НАЙДЕН — в этой сборке GigaChat работать не будет." -ForegroundColor Yellow
    Write-Host "  Приложение молча уйдёт на шаблоны. Собрать: python scripts/setup_gigachat_certs.py" -ForegroundColor Yellow
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
    Write-Host "ERROR: Node.js not found. Install Node 20.9+ to build the UI." -ForegroundColor Red
    exit 1
}
$minimumNodeVersion = [version]"20.9.0"
try {
    $actualNodeVersion = [version]("$(node -p "process.versions.node")".Trim())
} catch {
    Write-Host "ERROR: unable to determine Node.js version." -ForegroundColor Red
    exit 1
}
if ($actualNodeVersion -lt $minimumNodeVersion) {
    Write-Host "ERROR: Node.js 20.9+ is required; found $actualNodeVersion." -ForegroundColor Red
    exit 1
}
if (-not (Get-Command pnpm -ErrorAction SilentlyContinue)) {
    Write-Host "ERROR: pnpm not found. Enable the packageManager version from NewSpotterUI/package.json." -ForegroundColor Red
    exit 1
}
$expectedPnpm = [string]$packageJson.packageManager
if ($expectedPnpm -notmatch '^pnpm@(.+)$') {
    Write-Host "ERROR: package.json must pin packageManager as pnpm@<version>." -ForegroundColor Red
    exit 1
}
$expectedPnpmVersion = $Matches[1]
$actualPnpmVersion = "$(pnpm --version)".Trim()
if ($LASTEXITCODE -ne 0 -or $actualPnpmVersion -ne $expectedPnpmVersion) {
    Write-Host "ERROR: pnpm version mismatch." -ForegroundColor Red
    Write-Host ("  expected: " + $expectedPnpmVersion) -ForegroundColor Yellow
    Write-Host ("  actual:   " + $actualPnpmVersion) -ForegroundColor Yellow
    exit 1
}
Write-Host "Installing locked UI dependencies (pnpm install --frozen-lockfile)..." -ForegroundColor Cyan
pnpm -C $uiDir install --frozen-lockfile
if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: pnpm install failed." -ForegroundColor Red; exit 1 }
Write-Host "Auditing production UI dependencies..." -ForegroundColor Cyan
pnpm -C $uiDir audit --prod --audit-level=high
if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: production dependency audit failed." -ForegroundColor Red; exit 1 }
Write-Host "Linting UI..." -ForegroundColor Cyan
pnpm -C $uiDir run lint
if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: UI lint failed." -ForegroundColor Red; exit 1 }
Write-Host "Type-checking UI..." -ForegroundColor Cyan
pnpm -C $uiDir exec tsc --noEmit
if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: UI type-check failed." -ForegroundColor Red; exit 1 }
Write-Host "Building UI (pnpm build -> static export)..." -ForegroundColor Cyan
pnpm -C $uiDir run build
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
Remove-Item -Force "dist\piper.exe" -ErrorAction SilentlyContinue

# --- 1/3: piper.exe — ОТДЕЛЬНАЯ программа под GPL-3.0-or-later ---
# Собирается первой и НЕ входит в SpotterApp.exe: вшивать GPL-код в закрытый
# бинарник нельзя (см. NOTICE). Установщик кладёт её в отдельную папку.
Write-Host "Building piper.exe (separate GPL program)..." -ForegroundColor Cyan
& $pyExe @pyArgs -m PyInstaller --clean --noconfirm PiperCLI.spec
if ($LASTEXITCODE -ne 0) {
    Write-Host "piper.exe build failed! Exit code: $LASTEXITCODE" -ForegroundColor Red
    exit $LASTEXITCODE
}
Invoke-SpotterCodeSign -Path (Join-Path $PSScriptRoot "dist\piper.exe")

# --- 2/3: SpotterApp.exe ---
Write-Host "Running PyInstaller (SpotterApp)..." -ForegroundColor Cyan
& $pyExe @pyArgs -m PyInstaller --clean --noconfirm SpotterApp.spec
if ($LASTEXITCODE -ne 0) {
    Write-Host "Build failed! Exit code: $LASTEXITCODE" -ForegroundColor Red
    exit $LASTEXITCODE
}
Invoke-SpotterCodeSign -Path (Join-Path $PSScriptRoot "dist\SpotterApp.exe")

# Проверка лицензионной границы. Если GPL-код просочился в закрытый EXE
# транзитивным импортом, заметить это на глаз невозможно — поэтому гейт.
#
# Смотрим PKG-00.toc (что РЕАЛЬНО упаковано), а не Analysis-00.toc: в последнем
# лежит в том числе сам список excludes, и первая версия проверки ловила слово
# "onnxruntime" из него — то есть падала как раз на доказательстве, что
# исключение сработало.
#
# Наш собственный new_tts\piper_tts.py под шаблон не подпадает намеренно: это
# наш код, который управляет чужим процессом, а не код Piper.
$pkgToc = "build\SpotterApp\PKG-00.toc"
$leak = $null
if (Test-Path $pkgToc) {
    $leak = Select-String -Path $pkgToc -Pattern "site-packages\\\\+(piper|onnxruntime)\\\\|'(piper|onnxruntime)\\\\" -ErrorAction SilentlyContinue
} else {
    Write-Host "WARNING: $pkgToc не найден — лицензионная граница НЕ проверена." -ForegroundColor Yellow
}
if ($leak) {
    Write-Host "ERROR: GPL-код Piper/onnxruntime попал в SpotterApp.exe!" -ForegroundColor Red
    Write-Host "  Проверьте excludes в SpotterApp.spec." -ForegroundColor Yellow
    exit 1
}
Write-Host "Лицензионная граница: Piper в закрытом EXE не найден." -ForegroundColor Green

$exe = Get-Item "dist\SpotterApp.exe" -ErrorAction SilentlyContinue
$mb  = if ($exe) { [math]::Round($exe.Length / 1MB) } else { "?" }
Write-Host "dist\SpotterApp.exe ($mb MB)" -ForegroundColor Green

# --- 3/3: установщик (Inno Setup) ---
$iscc = $null
# Путь в LOCALAPPDATA обязателен: winget ставит Inno Setup в профиль
# пользователя, а не в Program Files, и первая версия поиска его не находила —
# сборка молча заканчивалась без установщика.
foreach ($candidate in @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
                         "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
                         "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe")) {
    if (Test-Path $candidate) { $iscc = $candidate; break }
}
if (-not $iscc) { $g = Get-Command ISCC -ErrorAction SilentlyContinue; if ($g) { $iscc = $g.Source } }

if (-not $iscc) {
    if ($RequireInstaller) {
        Write-Host "ERROR: Inno Setup не найден, а release-сборка требует установщик." -ForegroundColor Red
        exit 1
    } else {
        Write-Host "WARNING: Inno Setup не найден — установщик не собран." -ForegroundColor Yellow
        Write-Host "  winget install --id JRSoftware.InnoSetup" -ForegroundColor Yellow
    }
} else {
    $setupPath = Join-Path $PSScriptRoot ("dist\installer\SpotterApp-Setup-{0}.exe" -f $verPy)
    Remove-Item -LiteralPath $setupPath -Force -ErrorAction SilentlyContinue
    Write-Host "Building installer..." -ForegroundColor Cyan
    & $iscc "installer\SpotterApp.iss"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Installer build failed! Exit code: $LASTEXITCODE" -ForegroundColor Red
        exit $LASTEXITCODE
    }
    if (-not (Test-Path -LiteralPath $setupPath -PathType Leaf)) {
        Write-Host "ERROR: expected installer was not produced: $setupPath" -ForegroundColor Red
        exit 1
    }
    Invoke-SpotterCodeSign -Path $setupPath
    $setup = Get-Item -LiteralPath $setupPath
    Write-Host ("Done! " + $setup.FullName + " (" + [math]::Round($setup.Length / 1MB) + " MB)") -ForegroundColor Green
}

if (-not $RequireSigning) {
    Write-Host "DEV BUILD: Authenticode signing was not required. Do not publish these artifacts." -ForegroundColor Yellow
}

Write-Host "Yandex GPT/SpeechKit = primary (API key entered at runtime in Settings)." -ForegroundColor Cyan
Write-Host "Piper = отдельный компонент установщика, отдельный процесс." -ForegroundColor Cyan
