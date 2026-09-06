# MangaNana Agent Instructions

## Project

MangaNana is a Calibre GUI plugin for finding manga, preparing CBZ files, processing manga pages, and adding finished books to Calibre.

Current development branch: `feature/emperor-expansion`.

Current milestone: `0.13.0-dev — The Emperor`.

## Development priorities

1. Preserve stability.
2. Preserve the current Choose Manga → Book Customization → Finalization workflow.
3. Complete The Emperor's local-book I/O work before expanding the source catalog.
4. Avoid UI regressions.
5. Keep long-running work off the Qt GUI thread.
6. Prefer small, reversible changes.
7. Run checks before reporting completion.

### Current Emperor priorities

1. CBZ import.
2. PDF import.
3. PDF export.
4. Additional manga sources after local import/export is stable.
5. Reliability and regression hardening for the expanded input/output paths.

## Safety

- Never modify the user's normal Calibre library.
- Development testing must use `C:\MangaNana-Dev\Test-Library`.
- Temporary downloads should use `C:\MangaNana-Dev\Test-Downloads`.
- Test data should use `C:\MangaNana-Dev\Test-Data`.
- Do not store credentials or secrets in the repository.

## UI rules

- No network operations on the GUI thread.
- No heavy image processing on the GUI thread.
- Prefer Qt layouts over hard-coded child positions.
- Support Windows DPI scaling.
- Preserve smooth scrolling.
- Keep Search Results visible.
- Preserve the round MangaNana selection controls.
- Preserve the current visual design during Emperor feature work.
- Do not perform the planned major UI/UX redesign during The Emperor; that belongs to Judgement.
- Avoid layout movement during asynchronous loading.

## Existing behavior that must be preserved

- MangaDex search
- Direct MangaDex URL loading
- Search filtering
- Individual and range-based volume selection
- Standalone Chapters support
- Language fallback
- Metadata and cover handling
- Portrait output
- Landscape paired-page output
- Pairing Preview
- Finalization gating before final output
- Download cancellation and cleanup
- Activity Log
- Calibre import

## Architecture direction

- New source integrations should use the existing SourceAdapter abstraction and remain isolated from unrelated UI code.
- Reusable logic should be separable from Calibre-specific UI code.
- Preview and final output should use the same image-processing functions whenever possible.
- Local CBZ/PDF imports must converge into the same Book Customization and Finalization pipeline used by downloaded manga.
- Do not create a second image-processing pipeline for imported books.
- New output formats should reuse the existing final page-rendering pipeline before format-specific writing.
- Large imported books should remain disk-backed where practical instead of loading every full-resolution page into memory.
- Do not add source-specific behavior directly into unrelated UI code.

## Git workflow

- `main` is public/stable.
- `dev` remains the development integration branch.
- The active Emperor feature branch is `feature/emperor-expansion`.
- Larger work should continue to use feature branches created from the appropriate integration checkpoint.
- Do not push or merge into `main` unless explicitly instructed.

## Before reporting completion

- Run Python syntax checks.
- Inspect the Git diff.
- Summarize changed files.
- Report anything that could not be tested.
- Do not claim GUI or Calibre behavior was verified unless it was actually run.
