# Contributing to MangaAnkā

Start with [BUILDING.md](BUILDING.md), [COMPATIBILITY.md](COMPATIBILITY.md) and the relevant source module. See [PROVIDER_DEVELOPMENT.md](PROVIDER_DEVELOPMENT.md) for adapters. Record the source commit, package SHA-256 and Build ID in results; application code lives under source/.

## Development rules

Use a branch and disposable Calibre configuration, empty library and output directory. Never test against personal libraries. Do not commit credentials, cookies, diagnostics, downloaded pages or databases. Preserve internal plugin/storage names, source IDs and output identifiers.

Preserve Choose Manga → Book Customization → Finalization, virtualized discovery, lazy cards, cancellation/generation checks and exact accounting. Network and expensive page processing belong in workers; Qt widgets and active Calibre database calls stay on the GUI thread. Non-modal work must respect the pinned library, nested decisions and shutdown. Do not introduce application-wide event filters or unbounded callback ownership.

Prefer small, reviewable changes and surrounding Python conventions. There is no mandated formatter, dependency lock or CI matrix yet. Avoid broad formatting diffs. Justify new dependencies and licenses. Preserve shader/audio bytes unless an approved asset change is the purpose of the work.

## Verification

Use the documented Calibre-based portable runner. It blocks ordinary network access, isolates module globals and explicitly reports unavailable private captures. Its result is not full historical/native qualification. The historical virtual-library-name failure remains visible until an owner-approved test or migration decision.

First reproduce defects deterministically. Use synthetic identities and marker images rather than manga pages. Include pagination, nonnumeric/repeated labels, partial failure, cancellation and stale responses where relevant. GUI changes require the actual installed ZIP/action; output changes require artifact and actual disposable database verification. An import success flag is insufficient.

The public startup smoke does not qualify acquisition, provider performance or long-session stability. Live tests must be opt-in, bounded and rate-limit-aware. Stop at denied access; do not bypass protection or download whole works for benchmarks.

## Issues and pull requests

Include exact build/hash, environment/DPI/manual scale, public source/listing identity, language/edition, reproduction and expected versus actual records. Describe the preceding mode/provider/library and close/reopen transitions. Redact secrets, personal information and book content.

A PR should explain the concrete problem, resulting behavior, affected identity/state ownership, validation and limitations. Include provenance for assets. Do not silently clear caches, invent membership, override contradictory trusted IDs or disable duplicate protections globally. Obtain owner review for persistent schemas, broad architecture, ranking or update-policy changes.

Rebuild after runtime edits and test the exact proposed ZIP. Preserve failing evidence. Release/publication requires explicit owner authorization.
