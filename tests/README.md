# Regression tests

Use `python tools/run_source_tests.py --calibre-debug calibre-debug` from the source root. See [BUILDING.md](../BUILDING.md) for environment, module selection and reports.

The runner executes each module in a fresh Calibre process, with assertions enabled and ordinary network connections blocked. `source_suite_policy.json` explicitly records historical private-capture modules and methods that a public extraction cannot execute. Their absence is not a pass. Some tests already skip optional NumPy/Numba or private denial captures. One known historical test still expects the old MangaNana library tag.

The source archive includes original test modules, deterministic metadata/HTML fixtures, and two synthetic native-dithering PNGs. It excludes private build/profile evidence and manga page images. The distribution's staging manifest records fixture-path redaction in test copies; production Python and resources are copied byte-for-byte. `test_provider_template.py` exercises an unregistered network-free adapter scaffold.

Many old tests extract definitions from main.py's AST to avoid importing Calibre. Others need real Qt and Calibre. A system-Python discovery result without Qt is not equivalent to native validation. `unittest discover` against this archive also attempts private-capture modules and does not isolate global test imports; the portable runner is the documented entry point.

The startup smoke checks actual installed entry/resource initialization only. Provider delivery, GUI lifecycle stress, CBZ/PDF correctness and actual library conservation require separate installed-build qualification.
