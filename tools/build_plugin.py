#!/usr/bin/env python3
"""Build the MangaNana Calibre plugin ZIP."""

from __future__ import annotations

import ast
import hashlib
import os
from pathlib import Path
import subprocess
import zipfile


PYTHON_FILES = (
    '__init__.py',
    'app/__init__.py',
    'app/main.py',
    'app/manga_load_context.py',
    'app/notifications/__init__.py',
    'app/notifications/completion_audio.py',
    'app/notifications/completion_dialog.py',
    'app/notifications/completion_policy.py',
    'app/settings/__init__.py',
    'app/settings/config.py',
    'app/settings/google_books_credentials.py',
    'app/settings/google_books_key_dialog.py',
    'app/updates/__init__.py',
    'app/updates/release_updates.py',
    'app/updates/release_updates_ui.py',
    'app/workflow_state.py',
    'books/__init__.py',
    'books/imaging/__init__.py',
    'books/imaging/artwork_delivery.py',
    'books/imaging/artwork_cache.py',
    'books/imaging/bw_dark_mode.py',
    'books/imaging/cover_rendering.py',
    'books/imaging/dithering.py',
    'books/imaging/image_processing.py',
    'books/imaging/native_dithering.py',
    'books/imaging/page_framing.py',
    'books/imaging/page_rendering.py',
    'books/imaging/processing_presets.py',
    'books/imports/__init__.py',
    'books/imports/calibre_destination.py',
    'books/imports/import_workers.py',
    'books/imports/import_workflow.py',
    'books/imports/local_import.py',
    'books/imports/output_import.py',
    'books/imports/output_import_ui.py',
    'books/imports/replacement_backup.py',
    'books/output/__init__.py',
    'books/output/book_export.py',
    'books/output/chapter_output.py',
    'books/output/final_output_view.py',
    'books/output/batch_progress.py',
    'books/output/finalization_covers.py',
    'books/output/output_series_metadata.py',
    'books/output/series_number_ui.py',
    'books/preview/__init__.py',
    'books/preview/preview_detail.py',
    'books/preview/preview_render_state.py',
    'books/preview/screen_emulation.py',
    'common/__init__.py',
    'common/bounded_cache.py',
    'common/session_retention.py',
    'common/core_helpers.py',
    'common/i18n.py',
    'common/plugin_paths.py',
    'diagnostics/__init__.py',
    'diagnostics/diagnostics.py',
    'diagnostics/performance_diagnostics.py',
    'diagnostics/publication_diagnostics.py',
    'diagnostics/thumbnail_diagnostics.py',
    'discovery/__init__.py',
    'discovery/canonical_identity.py',
    'discovery/discovery_groups.py',
    'discovery/discovery_view.py',
    'discovery/enrichment_matching.py',
    'discovery/enrichment_model.py',
    'discovery/enrichment_sources.py',
    'discovery/recent_searches_ui.py',
    'discovery/saved_manga.py',
    'discovery/saved_manga_ui.py',
    'discovery/search_barrier.py',
    'discovery/search_cache.py',
    'discovery/search_ranking.py',
    'discovery/search_resolution.py',
    'metadata/__init__.py',
    'metadata/description_text.py',
    'metadata/reference_integration.py',
    'metadata/reference_metadata.py',
    'metadata/references/__init__.py',
    'metadata/references/bookwalker_reference.py',
    'metadata/references/google_books_reference.py',
    'metadata/references/madb_reference.py',
    'metadata/references/mangadex_artwork_reference.py',
    'metadata/references/mangadex_structure_reference.py',
    'metadata/references/wikipedia_identity.py',
    'metadata/references/wikipedia_reference.py',
    'metadata/title_metadata.py',
    'presentation/__init__.py',
    'presentation/choose_manga_background.py',
    'presentation/choose_manga_design.py',
    'presentation/choose_manga_polish.py',
    'presentation/choose_manga_reference.py',
    'presentation/hero_readability.py',
    'presentation/import_overview.py',
    'presentation/choose_manga_resources.py',
    'presentation/choose_manga_ui.py',
    'presentation/interface_scale.py',
    'presentation/mangaanka_presentation.py',
    'presentation/mangaanka_theme.py',
    'presentation/mangaanka_widgets.py',
    'presentation/non_modal_window.py',
    'presentation/window_geometry.py',
    'providers/__init__.py',
    'providers/atsu_acquisition.py',
    'providers/atsu_source.py',
    'providers/cross_source_fallback.py',
    'providers/mangadex_source.py',
    'providers/mangak_continuations.py',
    'providers/mangak_source.py',
    'providers/mangapill_source.py',
    'providers/provider_branding.py',
    'providers/source_adapter.py',
    'providers/source_coordinator.py',
    'providers/source_policy.py',
    'providers/source_registry.py',
    'providers/transport.py',
    'providers/weebcentral_source.py',
    'publication/__init__.py',
    'publication/catalog_reader.py',
    'publication/catalog_review.py',
    'publication/chapter_workflow.py',
    'publication/inventory_comparison.py',
    'publication/inventory_coverage.py',
    'publication/inventory_coverage_ui.py',
    'publication/publication_freshness.py',
    'publication/publication_identity.py',
    'publication/publication_manifest.py',
    'publication/publication_preparation.py',
    'publication/publication_specials.py',
    'publication/unified_volume.py',
    'ui.py',
    'version_info.py',
)
ROOT_FILES = (*PYTHON_FILES, "catalog_schema_v1.json",
              "publication_identity_bridge_schema_v1.json", "PUBLICATION_IDENTITY_BRIDGE_CONTRACT.md",
              "assets/publication_identity/empty-example.json",
              "assets/publication_identity/berserk-reviewed-r1.json",
              "assets/publication_identity/reviewed-registry-v1.json",
              "assets/acquisition_layouts/mangak_continuations.json",
              "plugin-import-name-manganana.txt", "LICENSE", "THIRD_PARTY_NOTICES.md")
IMAGE_FILES = (
    "images/icon.png",
    "images/favicon_mangadex_org_32x32.png",
    "images/favicon_mangapill_com_32x32.png",
    "images/favicon_weebcentral_com_32x32.png",
    "images/favicon_mangak_io_32x32.png",
    "images/favicon_atsu_moe_32x32.png",
    "images/tabler-book.svg",
)
OUTPUT_NAME = "MangaAnka-v1.0.0.zip"
NATIVE_FILES = ("native/windows-x86_64/manganana_dither_abi1.dll",)
COVER_FILES = tuple('assets/covers/' + name for name in (
    'background.png', 'anchor.png', 'stamp.png', 'BebasNeue-Regular.ttf', 'OFL.txt'))


def syntax_check(repository_root: Path) -> None:
    """Compile every packaged Python source without writing bytecode caches."""
    for relative_path in PYTHON_FILES:
        source_path = repository_root / relative_path
        source = source_path.read_bytes()
        compile(source, str(source_path), "exec")


def validate_local_imports(repository_root: Path, python_files=None) -> None:
    """Validate canonical local modules and package parents in the curated ZIP."""
    files=set(PYTHON_FILES if python_files is None else python_files)|{'build_info.py'}
    prefix='calibre_plugins.manganana'
    def local_path(module):
        relative=module.removeprefix(prefix).lstrip('.').replace('.','/')
        if not relative:return '__init__.py'
        leaf=relative+'.py';package=relative+'/__init__.py'
        if relative=='build_info':return leaf
        return package if (repository_root/package).is_file() else leaf
    legacy={p.stem for p in map(Path, PYTHON_FILES)}-{'__init__'}
    missing=set()
    for name in files-{'build_info.py'}:
        tree=ast.parse((repository_root/name).read_bytes(),name)
        for node in ast.walk(tree):
            modules=[]
            if isinstance(node,ast.Import):modules=[a.name for a in node.names]
            elif isinstance(node,ast.ImportFrom):
                if node.level:raise ValueError('Unconverted relative import in '+name)
                modules=[node.module or '']
                for alias in node.names:
                    child=(node.module or '')+'.'+alias.name
                    if child.startswith(prefix+'.') and (repository_root/local_path(child)).is_file():modules.append(child)
            for module in modules:
                if module in legacy and module not in ('ui','version_info','build_info'):
                    raise ValueError('Noncanonical local import in '+name+': '+module)
                if module==prefix or module.startswith(prefix+'.'):
                    path=local_path(module)
                    if path not in files:missing.add(name+' imports '+path)
                    parts=Path(path).parts[:-1]
                    for count in range(1,len(parts)+1):
                        parent='/'.join(parts[:count])+'/__init__.py'
                        if parent not in files:missing.add(name+' imports '+parent)
    if missing:raise ValueError('Unpackaged dependencies:\n'+'\n'.join(sorted(missing)))


def files_to_package(repository_root: Path) -> list[tuple[Path, str]]:
    """Return source paths and their POSIX-style paths inside the archive."""
    files = [
        (repository_root / relative_path, relative_path)
        for relative_path in ROOT_FILES
    ]
    files.extend((repository_root / path, path) for path in IMAGE_FILES)
    # Package the icons directly from their source assets.
    files.append((repository_root / 'docs/ui/mangaanka-app-icon.png', 'images/mangaanka-app-icon.png'))
    files.append((repository_root / 'docs/ui/mangaanka-calibre-icon.png', 'images/mangaanka-calibre-icon.png'))
    files.extend((repository_root / path, path) for path in NATIVE_FILES)
    files.extend((repository_root / path, path) for path in COVER_FILES)
    # Shared explicit resource manifest, with no Qt import or extraction here.
    namespace = {'__file__': str(repository_root / 'presentation/choose_manga_resources.py')}
    tree = ast.parse((repository_root / 'presentation/choose_manga_resources.py').read_bytes())
    declarations = [n for n in tree.body if isinstance(n, ast.Assign) and any(getattr(t, 'id', '') in ('PROVIDER_FILES', 'UI_FILES') for t in n.targets)]
    exec(compile(ast.Module(body=declarations, type_ignores=[]), 'resource-manifest', 'exec'), namespace)
    files.extend((repository_root / path, path) for path in namespace['UI_FILES'])
    return files


def build_info_source(repository_root: Path) -> str:
    """Create timestamp-free debug metadata for this development ZIP."""
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
    # A commit alone cannot distinguish successive uncommitted test builds.
    content = hashlib.sha256()
    for path, name in sorted(files_to_package(repository_root), key=lambda row: row[1]):
        content.update(name.encode('utf-8') + b'\0')
        content.update(hashlib.sha256(path.read_bytes()).digest())
    build_id = f'{commit}-{content.hexdigest()[:16]}'
    return (
        '"""Generated development-build identity."""\n\n'
        f"GIT_COMMIT = {commit!r}\n"
        f"BUILD_ID = {build_id!r}\n"
    )


def build_plugin(output_name=OUTPUT_NAME) -> Path:
    repository_root = Path(__file__).resolve().parent.parent
    syntax_check(repository_root)
    validate_local_imports(repository_root)

    output_dir = repository_root.parent / "builds"
    output_dir.mkdir(parents=True, exist_ok=True)
    if Path(output_name).name != output_name or not output_name.endswith('.zip'):
        raise ValueError('Output name must be a ZIP filename')
    output_path = output_dir / output_name
    temporary_path = output_dir / f".{output_name}.tmp"
    if output_path.exists():
        raise FileExistsError("Preserve existing artifact: " + str(output_path))
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
