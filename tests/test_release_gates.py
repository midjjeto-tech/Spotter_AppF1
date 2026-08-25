"""Release build must fail loudly before producing a stale/unchecked EXE."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "NewSpotterUI"
INSTALLER = ROOT / "installer" / "SpotterApp.iss"
RELEASE = ROOT / "scripts" / "release.ps1"


def test_next_production_build_does_not_ignore_typescript_errors():
    config = (UI / "next.config.mjs").read_text(encoding="utf-8")
    assert "ignoreBuildErrors" not in config


def test_frontend_has_an_executable_next_eslint_gate():
    package = json.loads((UI / "package.json").read_text(encoding="utf-8"))
    assert package["scripts"]["lint"] == "eslint . --max-warnings 37"
    assert package["devDependencies"]["eslint"]
    assert package["devDependencies"]["eslint-config-next"]
    assert (UI / "eslint.config.mjs").is_file()


def test_package_manager_and_release_install_are_reproducible():
    package = json.loads((UI / "package.json").read_text(encoding="utf-8"))
    assert package["packageManager"].startswith("pnpm@")

    build = (ROOT / "build.ps1").read_text(encoding="utf-8")
    assert "npm install -g pnpm" not in build
    assert "install --frozen-lockfile" in build
    assert "audit --prod --audit-level=high" in build
    assert "run lint" in build
    assert "exec tsc --noEmit" in build
    assert "[version]\"20.9.0\"" in build

    release = RELEASE.read_text(encoding="utf-8")
    assert "requirements-release.lock" in release
    assert "pip install --require-hashes" in release
    assert 'Join-Path $repoRoot ".release-venv"' in release
    assert (ROOT / ".python-version").read_text(encoding="utf-8").strip() == "3.12.7"


def test_python_requirements_declare_utf8_for_russian_windows():
    assert (ROOT / "requirements.txt").read_text(encoding="utf-8").startswith("# -*- coding: utf-8 -*-")
    assert (ROOT / "requirements-release.in").read_text(encoding="utf-8").startswith("# -*- coding: utf-8 -*-")


def test_unfinished_iracing_driver_is_not_in_the_f1_release_lock_input():
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    active_lines = [line.strip().lower() for line in requirements.splitlines()
                    if line.strip() and not line.lstrip().startswith("#")]
    assert not any(line.startswith("pyirsdk") for line in active_lines)
    assert "iracing_no_lib" in requirements

    release_lock = (ROOT / "requirements-release.lock").read_text(encoding="utf-8")
    locked_lines = [line.strip().lower() for line in release_lock.splitlines()
                    if line.strip() and not line.lstrip().startswith("#")]
    assert "--hash=sha256:" in release_lock
    assert not any(line.startswith("pyirsdk==") for line in locked_lines)
    for required_package in ("pip==", "piper-tts==", "pyinstaller==", "pytest=="):
        assert any(line.startswith(required_package) for line in locked_lines)


def test_all_user_facing_versions_match():
    package = json.loads((UI / "package.json").read_text(encoding="utf-8"))
    config = (ROOT / "config.py").read_text(encoding="utf-8")
    installer = INSTALLER.read_text(encoding="utf-8")

    app_version = re.search(r'^APP_VERSION\s*=\s*"([^"]+)"', config, re.MULTILINE)
    installer_version = re.search(r'^#define\s+AppVersion\s+"([^"]+)"', installer, re.MULTILINE)
    assert app_version and installer_version
    assert app_version.group(1) == installer_version.group(1) == package["version"]


def test_piper_release_is_an_exact_two_voice_allowlist():
    build = (ROOT / "build.ps1").read_text(encoding="utf-8")
    installer = INSTALLER.read_text(encoding="utf-8")
    piper_readme = (ROOT / "installer" / "piper-README.txt").read_text(encoding="utf-8")

    assert '$allowedVoiceNames = @("ru_RU-denis-medium", "ru_RU-dmitri-medium")' in build
    assert "ru_RU-*.onnx" not in installer
    for voice in ("denis", "dmitri"):
        assert f"ru_RU-{voice}-medium.onnx\"" in installer
        assert f"ru_RU-{voice}-medium.onnx.json\"" in installer
        assert f"ru_RU-{voice}-medium" in piper_readme
    assert "{ruslan,denis,irina,dmitri}" not in piper_readme


def test_release_path_is_fail_closed_for_source_signing_and_installer():
    release = RELEASE.read_text(encoding="utf-8")
    build = (ROOT / "build.ps1").read_text(encoding="utf-8")

    assert "git status --porcelain=v1 --untracked-files=all" in release
    assert "-m pytest -q" in release
    assert "-RequireInstaller -RequireSigning" in release
    assert "Get-AuthenticodeSignature" in release
    assert "release_manifest.py" in release
    assert "SPOTTER_SIGN_CERT_THUMBPRINT" in build
    assert "SPOTTER_SIGN_TIMESTAMP_URL" in build
    assert "Get-AuthenticodeSignature" in build


def test_release_build_uses_exact_versioned_installer_path():
    build = (ROOT / "build.ps1").read_text(encoding="utf-8")
    assert '"dist\\installer\\SpotterApp-Setup-{0}.exe" -f $verPy' in build
    assert 'Get-ChildItem "dist\\installer\\SpotterApp-Setup-*.exe"' not in build


def test_published_exes_embed_windows_version_resources():
    for spec_name in ("SpotterApp.spec", "PiperCLI.spec"):
        spec = (ROOT / spec_name).read_text(encoding="utf-8")
        assert "from config import APP_VERSION" in spec
        assert "StringStruct('FileVersion', APP_VERSION)" in spec
        assert "StringStruct('ProductVersion', APP_VERSION)" in spec
        assert "version=version_info" in spec

    installer = (ROOT / "installer" / "SpotterApp.iss").read_text(encoding="utf-8")
    assert '#define WindowsVersion "0.2.0.0"' in installer
    assert "VersionInfoVersion={#WindowsVersion}" in installer

    build = (ROOT / "build.ps1").read_text(encoding="utf-8")
    assert "$expectedWindowsVersion = \"$versionCore.0\"" in build
    assert "$windowsVersion -ne $expectedWindowsVersion" in build


def test_gigachat_ca_bundle_ships_and_is_versioned():
    """Бандл Минцифры обязан быть В ИСТОРИИ, а не только на машине сборщика.

    До 2026-08-25 `certs/` был закрыт `.gitignore` целиком, и бандл жил лишь в
    рабочем дереве. `release.ps1` собирает релиз с ЧИСТОГО коммита — то есть на
    любой другой машине сборка прошла бы успешно и выпустила EXE, в котором
    GigaChat не подключается вовсе: системное хранилище Windows цепочку НУЦ
    Минцифры не содержит. Отказ безопасный, но полный и незаметный —
    приложение уходит на шаблоны и снаружи выглядит просто скучнее."""
    bundle = ROOT / "certs" / "gigachat_ca_bundle.pem"
    assert bundle.is_file(), "нет certs/gigachat_ca_bundle.pem"

    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "certs/gigachat_ca_bundle.pem"],
        cwd=ROOT, capture_output=True, text=True, shell=True)
    assert tracked.returncode == 0, "бандл не под git — сборка с коммита его не увидит"

    text = bundle.read_text(encoding="utf-8", errors="replace")
    assert "BEGIN CERTIFICATE" in text
    # Только сертификаты: приватный ключ в репозитории — совсем другая история.
    assert "PRIVATE KEY" not in text


def test_signed_build_refuses_to_ship_without_the_ca_bundle():
    """Гейт, а не предупреждение. Жёлтая строка в логе сборки не мешает выпуску,
    и прежняя формулировка («используется проверенное системное хранилище»)
    вдобавок утверждала неверное."""
    build = (ROOT / "build.ps1").read_text(encoding="utf-8")

    assert "} elseif ($RequireSigning) {" in build
    assert "gigachat_ca_bundle.pem" in build
    assert "setup_gigachat_certs.py" in build
