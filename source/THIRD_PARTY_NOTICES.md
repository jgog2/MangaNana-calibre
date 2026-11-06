# Third-Party Notices

## Choose Manga presentation assets

Geist Regular, SemiBold and Bold are bundled unmodified from Vercel's Geist
font repository, commit `10dc7658f13c38a474cde201bb09a4617267545b`.
The SIL Open Font License and font attribution are in `assets/ui/fonts/OFL.txt`;
provenance is recorded in `assets/ui/fonts/README.md`.

The five provider fragment shaders and original hero fallback are copyright
2026 E. T. Carter <support@shader.gallery>, MIT licensed. Their original SPDX
notices and GLSL are retained, with the full license in
`assets/ui/LICENSE.selected-work-hero.txt`.

`assets/hero_shaders/NoSelection_Shader.frag` is Oil — Iridescent Thin Film,
copyright 2026 E. T. Carter <support@shader.gallery>, MIT licensed. It is used
only when no manga is selected, independently of the five provider mappings.
Original source and SPDX attribution are retained. Its complete MIT license
is in `assets/hero_shaders/LICENSE.NoSelection.txt`. The same licenses apply
to rendered static PNG fallbacks derived from these shaders.

## MangaDex publication structure

MangaDex (https://mangadex.org/) supplies public manga and aggregate metadata
through https://api.mangadex.org/. MangaAnkā normalizes explicit chapter/volume
relationships as publication reference evidence, and explicit volume cover-art
metadata as artwork references. Cover images use the existing image worker/cache.
These reference roles do not supply reading pages or imply endorsement by MangaDex.

## Media Arts Database (Japan) — MADB Lab

Source: Agency for Cultural Affairs, “MADB Lab”
(https://mediag.bunka.go.jp/madb_lab/).
出典：文化庁「MADB Lab」（https://mediag.bunka.go.jp/madb_lab/）

MangaAnkā selects, processes, and normalizes publication bibliographic metadata
from the official public SPARQL service. No MADB artwork or images are bundled.
The processed results are not official government-authored information and do
not imply endorsement by MADB, the Agency for Cultural Affairs, or the National
Center for Art Research.

Terms and attribution requirements: https://mediag.bunka.go.jp/madb_lab/user_terms/

## Bebas Neue

`assets/covers/BebasNeue-Regular.ttf` is bundled unmodified for MangaAnkā covers.
Font copyright: Copyright 2019 The Bebas Neue Project Authors
(https://github.com/dharmatype/Bebas-Neue).
Upstream license copyright: Copyright © 2010 by Dharma Type.
Licensed under the SIL Open Font License 1.1;
the complete license is included in `assets/covers/OFL.txt`.
License source: https://github.com/google/fonts/blob/main/ofl/bebasneue/OFL.txt

## Tabler Icons

The vendored `images/tabler-book.svg` uses the Tabler BOOK icon geometry.

MIT License

Copyright (c) 2020-2026 Paweł Kuna

Permission is hereby granted, free of charge, to any person obtaining a copy of
this software and associated documentation files (the "Software"), to deal in
the Software without restriction, including without limitation the rights to
use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of
the Software, and to permit persons to whom the Software is furnished to do so,
subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS
FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR
COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER
IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION
WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
