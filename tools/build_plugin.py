#!/usr/bin/env python3
"""Build the MangaNana Calibre plugin ZIP."""

from __future__ import annotations

import os
from pathlib import Path
import zipfile


PYTHON_FILES = (
    "__init__.py",
    "core_helpers.py",
    "main.py",
    "ui.py",
    "config.py",
    "i18n.py",
)
ROOT_FILES = (*PYTHON_FILES, "plugin-import-name-manganana.txt")
OUTPUT_NAME = "MangaNana-Calibre-dev.zip"


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


def build_plugin() -> Path:
    repository_root = Path(__file__).resolve().parent.parent
    syntax_check(repository_root)

    output_dir = repository_root / "dist"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / OUTPUT_NAME
    temporary_path = output_dir / f".{OUTPUT_NAME}.tmp"

    try:
        with zipfile.ZipFile(
            temporary_path, "w", compression=zipfile.ZIP_DEFLATED
        ) as archive:
            for source_path, archive_path in files_to_package(repository_root):
                archive.write(source_path, archive_path)
        os.replace(temporary_path, output_path)
    finally:
        temporary_path.unlink(missing_ok=True)

    return output_path


if __name__ == "__main__":
    print(build_plugin())
