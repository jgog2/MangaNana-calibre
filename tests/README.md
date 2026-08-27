# Regression tests

Run the Calibre-independent regression tests from the repository root:

```powershell
python -m unittest discover -s tests -v
```

`main.py` imports Calibre and Qt at module load time and combines API access,
selection rules, image processing, workers, and UI classes in one module. The
tests therefore extract and execute the existing pure helper definitions from
the source AST instead of importing `main.py` or duplicating their logic.

The download-language fallback in `populate_download_languages` directly
manipulates a Qt combo box and reads module-level GUI data, so it is not safely
unit-testable without Calibre/Qt. These initial tests cover the equivalent pure
metadata fallback helpers (`first_localized` and `choose_preferred_title`).

Standalone chapter ordering is requested from MangaDex through API query
parameters and is preserved by `fetch_chapter_entries`; it is not independently
sorted locally. The regression test verifies those ordering parameters, the
preserved response order, and duplicate translated-chapter removal.
