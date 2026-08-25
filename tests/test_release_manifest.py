from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.release_manifest import create_release_files, sha256_file


def test_release_manifest_records_clean_provenance_and_checksums(tmp_path: Path):
    base = tmp_path / "dist"
    installer = base / "installer" / "SpotterApp-Setup-0.2.0-rc.1.exe"
    installer.parent.mkdir(parents=True)
    app = base / "SpotterApp.exe"
    app.write_bytes(b"app")
    installer.write_bytes(b"setup")

    manifest_path, sums_path = create_release_files(
        base_dir=base,
        output_dir=base / "release",
        version="0.2.0-rc.1",
        commit="a" * 40,
        artifact_paths=["SpotterApp.exe", "installer/SpotterApp-Setup-0.2.0-rc.1.exe"],
        toolchain={"python": "3.12.7", "node": "20.9.0"},
        created_utc="2026-08-17T12:00:00Z",
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["app_version"] == "0.2.0-rc.1"
    assert manifest["expected_git_tag"] == "v0.2.0-rc.1"
    assert manifest["git_commit"] == "a" * 40
    assert manifest["source_dirty"] is False
    assert manifest["toolchain"] == {"node": "20.9.0", "python": "3.12.7"}
    assert manifest["artifacts"][0]["sha256"] == sha256_file(app)
    assert sums_path.read_text(encoding="ascii").splitlines() == [
        f"{sha256_file(app)}  SpotterApp.exe",
        f"{sha256_file(installer)}  installer/SpotterApp-Setup-0.2.0-rc.1.exe",
    ]


def test_release_manifest_rejects_artifact_outside_dist(tmp_path: Path):
    base = tmp_path / "dist"
    base.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("secret", encoding="utf-8")

    with pytest.raises(ValueError, match="escapes base directory"):
        create_release_files(
            base_dir=base,
            output_dir=base / "release",
            version="0.2.0",
            commit="b" * 40,
            artifact_paths=["../secret.txt"],
            toolchain={},
        )
