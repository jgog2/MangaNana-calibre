# MangaNana Agent Instructions

## Project

MangaNana is a Calibre GUI plugin for finding manga, preparing CBZ files, processing manga pages, and adding finished books to Calibre.

Current development branch: `dev`.

## Development priorities

1. Preserve stability.
2. Keep the current Choose Manga → Download Settings → Review workflow.
3. Avoid UI regressions.
4. Keep long-running work off the Qt GUI thread.
5. Prefer small, reversible changes.
6. Run checks before reporting completion.

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
- Preserve the orange MangaNana visual language.
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
- Review gating before final download
- Download cancellation and cleanup
- Activity Log
- Calibre import

## Architecture direction

- New source integrations should eventually use a SourceAdapter abstraction.
- Reusable logic should be separable from Calibre-specific UI code.
- Preview and final output should use the same image-processing functions whenever possible.
- Do not add source-specific behavior directly into unrelated UI code.

## Git workflow

- `main` is public/stable.
- `dev` is the development integration branch.
- Larger work should use feature branches created from `dev`.
- Do not push or merge into `main` unless explicitly instructed.

## Before reporting completion

- Run Python syntax checks.
- Inspect the Git diff.
- Summarize changed files.
- Report anything that could not be tested.
- Do not claim GUI or Calibre behavior was verified unless it was actually run.