"""Create immutable checksums and provenance metadata for release artifacts."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping


VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z]+(?:\.[0-9A-Za-z]+)*)?$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _resolved_inside(base_dir: Path, relative_path: str) -> tuple[Path, str]:
    base = base_dir.resolve()
    candidate = (base / relative_path).resolve()
    try:
        relative = candidate.relative_to(base)
    except ValueError as exc:
        raise ValueError(f"artifact escapes base directory: {relative_path}") from exc
    if not candidate.is_file():
        raise FileNotFoundError(candidate)
    return candidate, relative.as_posix()


def create_release_files(
    *,
    base_dir: Path,
    output_dir: Path,
    version: str,
    commit: str,
    artifact_paths: Iterable[str],
    toolchain: Mapping[str, str],
    created_utc: str | None = None,
) -> tuple[Path, Path]:
    if not VERSION_RE.fullmatch(version):
        raise ValueError(f"invalid release version: {version}")
    if not re.fullmatch(r"[0-9a-fA-F]{40}", commit):
        raise ValueError("git commit must be a full 40-character SHA")

    artifacts: list[dict[str, object]] = []
    seen: set[str] = set()
    for requested in artifact_paths:
        path, relative = _resolved_inside(base_dir, requested)
        if relative in seen:
            raise ValueError(f"duplicate artifact: {relative}")
        seen.add(relative)
        artifacts.append(
            {
                "path": relative,
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    if not artifacts:
        raise ValueError("at least one release artifact is required")

    timestamp = created_utc or datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    manifest = {
        "schema_version": 1,
        "app_version": version,
        "expected_git_tag": f"v{version}",
        "git_commit": commit.lower(),
        "source_dirty": False,
        "created_utc": timestamp,
        "toolchain": dict(sorted(toolchain.items())),
        "artifacts": artifacts,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / f"SpotterApp-{version}-manifest.json"
    sums_path = output_dir / f"SpotterApp-{version}-SHA256SUMS.txt"
    manifest_tmp = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    sums_tmp = sums_path.with_suffix(sums_path.suffix + ".tmp")
    manifest_tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    sums_tmp.write_text(
        "".join(f"{item['sha256']}  {item['path']}\n" for item in artifacts),
        encoding="ascii",
    )
    manifest_tmp.replace(manifest_path)
    sums_tmp.replace(sums_path)
    return manifest_path, sums_path


def _parse_toolchain(values: Iterable[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"tool must be NAME=VERSION: {value}")
        name, version = value.split("=", 1)
        if not name or not version or name in result:
            raise ValueError(f"invalid or duplicate tool entry: {value}")
        result[name] = version
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--artifact", action="append", default=[], required=True)
    parser.add_argument("--tool", action="append", default=[])
    args = parser.parse_args()

    manifest, sums = create_release_files(
        base_dir=args.base_dir,
        output_dir=args.output_dir,
        version=args.version,
        commit=args.commit,
        artifact_paths=args.artifact,
        toolchain=_parse_toolchain(args.tool),
    )
    print(manifest)
    print(sums)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
