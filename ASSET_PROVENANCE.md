# Asset and dependency provenance — review required

This local source-distribution candidate is not permission to publish every asset. The project [MIT license](LICENSE) applies to code owned by its licensor; ownership of supplied material still needs confirmation. Keep [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and bundled licenses intact. No manga pages or user configuration are distributed.

| Material | Available evidence / open item |
|---|---|
| Project Python/C | Root MIT copyright jgog. Native kernel came from an earlier handoff according to development notes; owner should confirm original kernel authorship/license and static MSVC runtime redistribution conditions before public binary distribution |
| Five provider shaders, original hero and no-selection shader | Original SPDX/copyright E. T. Carter / MIT retained; full licenses in `assets/ui/LICENSE.selected-work-hero.txt`, `assets/hero_shaders/LICENSE.NoSelection.txt`. Static PNGs are derived shader fallbacks |
| Geist TTFs | Three unmodified files, pinned upstream commit recorded in `assets/ui/fonts/README.md`, with OFL. That README's old 'review-only' packaging description is stale; current builder includes these files. [Upstream OFL](https://github.com/vercel/geist-font/blob/main/OFL.txt) |
| Bebas Neue | Font and OFL in `assets/covers`; notice credits project/Dharma Type. [Upstream license](https://github.com/google/fonts/blob/main/ofl/bebasneue/OFL.txt) |
| Tabler book SVG | Full MIT notice in THIRD_PARTY_NOTICES |
| Other small UI SVGs | Retained from approved repository assets. Separate upstream authorship/license evidence was not found for every chevron/sort icon; owner confirmation needed |
| Provider favicons | Required for exact r10 reproduction. Provider names/icons are not covered automatically by this project's MIT grant; owner should confirm appropriate use and attribution/redistribution before publishing |
| Application icons, cover background/stamp/anchor | Owner-supplied/approved assets retained byte-for-byte. Authorship and redistribution grant are not documented in a separate asset license; confirm with owner. Anchor remains packaged for compatibility although generated covers no longer draw it |
| Completion MP3 | Exact owner-supplied 78,576-byte `assets/audio/mangaanka_complete.mp3`; provenance beyond selection/supply is unverified. Confirm copyright/redistribution rights. No external file is required at runtime |
| Publication bridge JSON / metadata fixtures | Required reviewed identity facts plus public provider/reference metadata, no reading-page bytes. Existing MADB attribution retained. Wikipedia-derived/other source text and provider terms require redistribution review; not all underlying metadata rights are established by project MIT |
| Two native test PNGs | Small deterministic RGB/gray pixel fixtures used for hash/parity tests; not manga scans |
| Calibre, Qt/PyQt, Pillow | Host dependencies, not vendored into the source ZIP; use the installed Calibre environment. Their upstream licenses remain independent |
| NumPy/Numba | Optional explicit benchmarking/test acceleration; not bundled and not required for ordinary operation |

Söhne font archives, illustrative manga screenshots, design reference image bundles, old ZIPs, crash evidence and downloaded books are excluded. Keeping required runtime assets in this **local review archive** enables exact rebuild comparison; it does not resolve the open permissions above. Do not publish it until the owner clears those items.

The 1.0.0 builder includes root LICENSE and THIRD_PARTY_NOTICES.md in the installable plugin. Earlier development packages omitted the root license. Inclusion of notices does not resolve the open asset-permission questions above.
