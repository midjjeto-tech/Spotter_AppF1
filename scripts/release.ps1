[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Push-Location $repoRoot
try {
    function Stop-Release([string]$Message) {
        Write-Host "RELEASE BLOCKED: $Message" -ForegroundColor Red
        exit 1
    }

    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        Stop-Release "git is not available."
    }

    $sourceChanges = @(git status --porcelain=v1 --untracked-files=all)
    if ($LASTEXITCODE -ne 0) { Stop-Release "git status failed." }
    if ($sourceChanges.Count -gt 0) {
        $sourceChanges | ForEach-Object { Write-Host "  $_" -ForegroundColor Yellow }
        Stop-Release "source tree is dirty; commit the exact release candidate first."
    }

    git diff --check
    if ($LASTEXITCODE -ne 0) { Stop-Release "git diff --check failed." }

    $bootstrapPython = if ($env:SPOTTER_PYTHON) {
        $env:SPOTTER_PYTHON
    } else {
        Join-Path $repoRoot ".venv\Scripts\python.exe"
    }
    if (-not (Test-Path -LiteralPath $bootstrapPython -PathType Leaf)) {
        Stop-Release "bootstrap Python not found: $bootstrapPython"
    }
    $expectedPythonVersion = (Get-Content (Join-Path $repoRoot ".python-version") -Raw).Trim()
    $actualPythonVersion = (& $bootstrapPython -c "import platform; print(platform.python_version())").Trim()
    if ($LASTEXITCODE -ne 0 -or $actualPythonVersion -ne $expectedPythonVersion) {
        Stop-Release "Python $expectedPythonVersion is required; found $actualPythonVersion."
    }

    $releaseLock = Join-Path $repoRoot "requirements-release.lock"
    if (-not (Test-Path -LiteralPath $releaseLock -PathType Leaf)) {
        Stop-Release "requirements-release.lock is missing."
    }
    $releaseVenv = [IO.Path]::GetFullPath((Join-Path $repoRoot ".release-venv"))
    if ([IO.Path]::GetDirectoryName($releaseVenv) -ne $repoRoot -or
        [IO.Path]::GetFileName($releaseVenv) -ne ".release-venv") {
        Stop-Release "unsafe release venv path: $releaseVenv"
    }
    if (Test-Path -LiteralPath $releaseVenv) {
        Remove-Item -LiteralPath $releaseVenv -Recurse -Force
    }
    & $bootstrapPython -m venv $releaseVenv
    if ($LASTEXITCODE -ne 0) { Stop-Release "cannot create clean release virtualenv." }
    $python = Join-Path $releaseVenv "Scripts\python.exe"
    & $python -m pip install --require-hashes -r $releaseLock
    if ($LASTEXITCODE -ne 0) { Stop-Release "locked Python environment installation failed." }

    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        Stop-Release "release Python not found after venv creation: $python"
    }

    $version = (& $python -c "import sys; sys.path.insert(0, r'$repoRoot'); import config; print(config.APP_VERSION)").Trim()
    if ($LASTEXITCODE -ne 0) { Stop-Release "cannot read config.APP_VERSION." }
    if ($version -notmatch '^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z]+(?:\.[0-9A-Za-z]+)*)?$') {
        Stop-Release "invalid release version: $version"
    }

    $package = Get-Content (Join-Path $repoRoot "NewSpotterUI\package.json") -Raw | ConvertFrom-Json
    $issMatch = Select-String -Path (Join-Path $repoRoot "installer\SpotterApp.iss") `
        -Pattern '^#define\s+AppVersion\s+"([^"]+)"'
    if (-not $issMatch) { Stop-Release "installer AppVersion is missing." }
    $installerVersion = $issMatch.Matches[0].Groups[1].Value
    if ($version -ne [string]$package.version -or $version -ne $installerVersion) {
        Stop-Release "config.py, package.json and SpotterApp.iss versions differ."
    }

    $tag = "v$version"
    git show-ref --verify --quiet "refs/tags/$tag"
    if ($LASTEXITCODE -eq 0) {
        Stop-Release "tag $tag already exists; release versions are immutable."
    }
    if ($LASTEXITCODE -ne 1) { Stop-Release "unable to inspect tag $tag." }

    $commit = (git rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or $commit -notmatch '^[0-9a-f]{40}$') {
        Stop-Release "unable to resolve the full release commit SHA."
    }

    Write-Host "Release preflight: $version @ $commit" -ForegroundColor Cyan
    & $python -m pip check
    if ($LASTEXITCODE -ne 0) { Stop-Release "Python environment has broken dependencies." }
    & $python -m pytest -q
    if ($LASTEXITCODE -ne 0) { Stop-Release "full Python test suite failed." }

    $env:SPOTTER_PYTHON = $python
    & (Join-Path $repoRoot "build.ps1") -RequireInstaller -RequireSigning
    if ($LASTEXITCODE -ne 0) { Stop-Release "signed application build failed." }

    $postBuildChanges = @(git status --porcelain=v1 --untracked-files=all)
    if ($LASTEXITCODE -ne 0) { Stop-Release "post-build git status failed." }
    if ($postBuildChanges.Count -gt 0) {
        $postBuildChanges | ForEach-Object { Write-Host "  $_" -ForegroundColor Yellow }
        Stop-Release "build changed tracked source; commit regenerated webui before releasing."
    }

    $installerName = "SpotterApp-Setup-$version.exe"
    $artifactPaths = @(
        "SpotterApp.exe",
        "piper.exe",
        "installer/$installerName"
    )
    foreach ($relativePath in $artifactPaths) {
        $artifact = Join-Path (Join-Path $repoRoot "dist") $relativePath
        if (-not (Test-Path -LiteralPath $artifact -PathType Leaf)) {
            Stop-Release "missing release artifact: $relativePath"
        }
        $signature = Get-AuthenticodeSignature -LiteralPath $artifact
        if ($signature.Status -ne "Valid") {
            Stop-Release "invalid Authenticode signature: $relativePath ($($signature.Status))"
        }
    }

    $pythonVersion = (& $python --version 2>&1).Trim()
    $nodeVersion = (& node --version).Trim()
    if ($LASTEXITCODE -ne 0) { Stop-Release "cannot read Node.js version." }
    $pnpmVersion = (& pnpm --version).Trim()
    if ($LASTEXITCODE -ne 0) { Stop-Release "cannot read pnpm version." }
    $pyInstallerVersion = (& $python -m PyInstaller --version).Trim()
    if ($LASTEXITCODE -ne 0) { Stop-Release "cannot read PyInstaller version." }

    $manifestArgs = @(
        "scripts\release_manifest.py",
        "--base-dir", "dist",
        "--output-dir", "dist\release",
        "--version", $version,
        "--commit", $commit,
        "--tool", "python=$pythonVersion",
        "--tool", "node=$nodeVersion",
        "--tool", "pnpm=$pnpmVersion",
        "--tool", "pyinstaller=$pyInstallerVersion"
    )
    foreach ($relativePath in $artifactPaths) {
        $manifestArgs += @("--artifact", $relativePath)
    }
    & $python @manifestArgs
    if ($LASTEXITCODE -ne 0) { Stop-Release "release manifest generation failed." }

    Write-Host "SIGNED RELEASE CANDIDATE READY: $version" -ForegroundColor Green
    Write-Host "After live acceptance create the signed annotated tag: $tag" -ForegroundColor Cyan
} finally {
    Pop-Location
}
