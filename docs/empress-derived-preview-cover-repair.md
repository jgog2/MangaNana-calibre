# Empress: derived-volume Preview and cover integrity repair

## Confirmed causes and narrow repair

On `feature/empress-processing-foundation`, `_preview_sample_target()` discarded
the exact chapter membership already held by unified groups. PairingPreviewWorker
therefore queried a native volume range, which chapter-only providers cannot
resolve. The worker and provider adapters were correct; the handoff was not.

Selected Volume and Standalone targets now use `selected_unified_volume_groups()`
and copy their exact acquisition rows, retaining IDs, `_source_id` and other
metadata. The same helper supplies Finalization groups. Plans without
`volume_groups` still pass an empty planned tuple and retain the native-volume
or standalone fallback. No provider-specific branch or invented volume metadata
was added. Bounded Preview sampling itself is unchanged: membership describes
the selected group, not a promise to download every page of that group.

Both reference-cover merge sites used `update()`, overwriting selected-provider
exact artwork. They now use gap-filling `setdefault()`: provider exact artwork
wins regardless of arrival order, reference artwork fills missing volumes, and
the existing series/main fallback remains. No cover is added to reading pages.

BOOK WALKER artwork is normalized while building the publication manifest from
fresh or cached records. Recognized HTTPS rimg URLs with a single image-ID and
filename become `https://c.bookwalker.jp/<id>/t_700x780.jpg` for `url` and
`source_url`; `preview_url` retains the original thumbnail. Numeric and hashed
IDs work. Unknown hosts, HTTP, fragments and unexpected extra path components
are left unchanged. Edition artwork receives the same conservative normalization.
No image upscaling, network request, cache-contract bump or cache clearing is used.

The provided patch was implementation guidance, not applied blindly. The URL
matcher conservatively rejects extra path components/fragments, and artwork
preview/source fields use keyword arguments to avoid positional ambiguity.

## Files changed in this pass

- `main.py`: exact Preview target membership and two gap-fill cover merges.
- `publication_manifest.py`: BOOK WALKER metadata URL normalization.
- New `tests/test_derived_preview_covers.py`: 13 regression tests.
- New `tools/derived_preview_calibre_smoke.py`: real Qt acquisition/Finalization/CBZ smoke.
- This report. Earlier uncommitted work is preserved.

All other packaged files match the prior Brightness/Sharpness ZIP byte-for-byte,
including processing, native dithering, ctypes loader/ABI/DLL, bounded render pool,
Overview/Detail implementation, encoding, adapters and source policy. The earlier
orchestration report is reference only; no performance redesign was undertaken.

## Verification

- **67 focused / 548 broader / 734 full-suite tests pass.**
- **115** source/test/tool Python files compile. Git diff inspection/check passes.
- Derived synthetic inventories model Attack on Titan/WeebCentral (142 chapters,
  34 derived volumes) and Chainsaw Man/MangaPill and WeebCentral (232 chapters,
  24 derived volumes). Production projection/planning feeds Volume 1 and mid-series
  Preview targets. IDs match actual Finalization worker output groups, with no
  missing/duplicate membership and acquisition metadata retained.
- Exact planned membership prevents native range queries; Standalone uses its
  exact group. Unified Steel Ball Run-style 24-native-volume membership and legacy
  native plans without groups remain covered. Chapter mode is unchanged.
- Both cover arrival orders are tested, including provider exact Steel Ball Run
  Vol. 1 versus the reported BOOK WALKER URL and reference-only volume fallback.
  Manifest thumbnail/metadata fields and unknown URL forms are tested.
- Real Calibre Qt worker smoke covers Attack on Titan/WeebCentral, Chainsaw Man/
  MangaPill, Chainsaw Man/WeebCentral, and Steel Ball Run/MangaDex using synthetic
  pages. Preview → Finalization → valid ordered CBZ succeeds. Derived cases make
  zero native chapter-range lookups; legacy native makes its two expected lookups
  (Preview and Finalization). Adjusted output leaves cover bytes untouched.
- Existing real offscreen Qt smoke passes with native and simulated missing-DLL
  portable backends: local processing, provisional Detail, zoom, dirty Overview,
  Reset and closure, with zero external network calls.
- Existing pipeline and pool tests retain shared processing, cover exclusion,
  native/portable fallback, ordering, cancellation and progress/timing checks.

## Limitations and safety

Title cases use deterministic synthetic records, not newly downloaded live title
inventories or verified real chapter boundaries. No live rendition availability or
actual image dimensions were fetched; the requested public rendition is selected
by URL. Real provider and physical eReader/manual GUI qualification remain useful.
Normal tests do not depend on external services. Existing optional Numba/SciPy ABI
and Pillow deprecation warnings remain; no dependencies were changed.

No commit, push, tag, merge, branch change, release, normal Calibre-library access,
dependency installation, provider-adapter mutation or persistent-cache clearing.

## Final artifact

Built exactly once after source verification: `dist/MangaNana-Calibre-dev.zip`.

SHA-256: `F46DCBD69104DD09232F90B8AF01277E982B45F5B5EFFEA91DE605E821FD6673`.

ZIP integrity, exact 52-entry manifest, required runtime modules, source/resource
parity and compilation of all 46 packaged Python modules pass. Isolated Calibre
installation/loading passes; installed-ZIP native and portable smoke both generate
valid Portrait/Landscape CBZs, preserve covers and neutral output, and pass parity
checks with zero external network calls. The four title/provider worker scenarios
also pass against the installed ZIP, not only source modules.

The two disposable configurations created for this pass are removed after checks.
Existing persistent caches are untouched. Restart Calibre after installing.
