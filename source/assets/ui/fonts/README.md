# Geist Sans — review-only bundled fonts

Unmodified static Regular, SemiBold and Bold TTF files from Vercel's official
repository, pinned to commit `10dc7658f13c38a474cde201bb09a4617267545b`:

https://github.com/vercel/geist-font/tree/10dc7658f13c38a474cde201bb09a4617267545b/fonts/Geist/ttf

Copyright (c) 2023 Vercel, in collaboration with basement.studio.
Distributed with the accompanying SIL Open Font License 1.1 in `OFL.txt`.
No font has been renamed or modified. Final validation records file SHA-256 values.

The isolated review loads these files with `QFontDatabase.addApplicationFont`.
It does not install system fonts or change Calibre's global font preference.
Missing/corrupt bundled fonts produce an explicit error rather than silent
substitution. Qt's requested fallback list is Yu Gothic UI, Microsoft YaHei UI,
Segoe UI and sans-serif. Native shaping tests on this Windows machine identify
Yu Gothic UI for Japanese glyphs and Geist for the Latin title widget.

The review source and assets remain outside the normal plugin entry point and
packaging. A future production promotion would need to package the three TTFs,
this attribution and the OFL license together with the new UI modules.
