#!/usr/bin/env python3
"""Build the MangaNana Calibre plugin ZIP."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
from datetime import datetime, timezone
import zipfile


PYTHON_FILES = (
    "__init__.py",
    "core_helpers.py",
    "source_adapter.py",
    "mangadex_source.py",
    "main.py",
    "ui.py",
    "config.py",
    "i18n.py",
)
ROOT_FILES = (*PYTHON_FILES, "plugin-import-name-manganana.txt")
OUTPUT_NAME = "MangaNana-Calibre-dev.zip"
PUBLIC_VERSION = "0.9.8"


def syntax_check(repository_root: Path) -> None:
    """Compile every packaged Python source without writing bytecode caches."""
    for relative_path in PYTHON_FILES:
        source_path = repository_root / relative_path
        source = source_path.read_bytes()
        compile(source, str(source_path), "exec")


def files_to_package(repository_root: Path) -> list[tuple[Path, str]]:
    """Return source paths and their POSIX-style paths inside the archive."""
    files = [
        (repository_root / relative_path, relative_path)
        for relative_path in ROOT_FILES
    ]
    files.append((repository_root / "images" / "icon.png", "images/icon.png"))
    return files


def build_info_source(repository_root: Path) -> str:
    """Create a visible identity for this exact development ZIP."""
    try:
        result = subprocess.run(
            [
                "git",
                "-c",
                f"safe.directory={repository_root.as_posix()}",
                "rev-parse",
                "--short=7",
                "HEAD",
            ],
            cwd=repository_root,
            check=True,
            capture_output=True,
            text=True,
        )
        commit = result.stdout.strip() or "unknown"
    except Exception:
        commit = "unknown"
    built_at = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ")
    build_id = f"{commit}+{built_at}"
    display_version = f"MangaNana {PUBLIC_VERSION}-dev ({build_id})"
    return (
        '"""Generated development-build identity."""\n\n'
        f"BUILD_ID = {build_id!r}\n"
        f"DISPLAY_VERSION = {display_version!r}\n"
    )


def build_plugin() -> Path:
    repository_root = Path(__file__).resolve().parent.parent
    syntax_check(repository_root)

    output_dir = repository_root / "dist"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / OUTPUT_NAME
    temporary_path = output_dir / f".{OUTPUT_NAME}.tmp"
    generated_build_info = build_info_source(repository_root)
    compile(generated_build_info, "build_info.py", "exec")

    try:
        with zipfile.ZipFile(
            temporary_path, "w", compression=zipfile.ZIP_DEFLATED
        ) as archive:
            for source_path, archive_path in files_to_package(repository_root):
                archive.write(source_path, archive_path)
            archive.writestr("build_info.py", generated_build_info)
        os.replace(temporary_path, output_path)
    finally:
        temporary_path.unlink(missing_ok=True)

    return output_path


if __name__ == "__main__":
    print(build_plugin())
