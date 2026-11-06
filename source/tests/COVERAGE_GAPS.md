# Portable suite and retained-evidence tests

Run `python tools/run_source_tests.py --calibre-debug "C:/Program Files/Calibre2/calibre-debug.exe" --data-root <disposable-directory>` from the source root. This runner uses Calibre's Python and Qt, isolates configuration for each module, and blocks live networking. System Python without Qt is not equivalent validation.

`source_suite_policy.json` documents the individual methods requiring retained private captures. Both previously unavailable modules now import: eight portable Berserk optimization controls and two MADB bridge/registry controls execute. The fifteen methods in those modules that actually consume captures remain explicitly skipped. The catalog capture is never replaced by fabricated publication evidence.

Other gaps have different meanings:

| Category | Skip records | What remains unqualified |
|---|---:|---|
| Private provider/reference/native captures | 23 | Historical real-response comparisons, including the fifteen newly exposed methods. Portable parser, identity, mapping, cache and output controls still execute. |
| Separate popup laboratory packages | 13 | Test-only service simulation overlays absent from a normal source checkout. Production popup/updater contracts have separate current-source coverage. |
| Optional NumPy / Numba | 3 | Accelerated backend parity/failure paths on a runtime that does not supply those packages. Portable processing is exercised. |
| Historical frozen r4 comparison | 1 class | Old-versus-new implementation comparison requires the retained historical ZIP. Current large-inventory controls and installed-ZIP tests are separate. |
| Original absolute-path shader asset | 1 | Legacy external-file test; packaged resource preservation is checked by archive hashes instead. |

These are 41 skip records, including two class-level skips. `unittest.testsRun` counts methods but does not count a skipped `setUpClass`; subtracting all 41 from testsRun undercounts successful methods by two. Use recorded `outcome: pass` entries for the exact pass count.

Do not remove assertions, substitute invented provider memberships, or report these skips as passes. A synthetic fixture may add a deterministic behavioral contract, but cannot establish that an unavailable historical live capture matched. New portable controls should use small redistributable inputs, independent expected results, exact source identities, cancellation and ambiguous-data cases.

Native Windows tests are additional evidence. They do not establish Linux/macOS behavior, compatibility with an untested Calibre version, successful delivery of live manga images when marker pages were used, or long-session leak freedom.
