# Release checklist

This is a future publication checklist, not authorization to release this snapshot.

## Establish the candidate

- Identify exact source bytes, dirty/untracked files, Build ID and qualified installable SHA-256. Do not reconstruct a tested dirty runtime from HEAD alone.
- Review outstanding crash, responsiveness, output/accounting, upgrade and licensing risks. Resolve blockers explicitly; record unknown coverage.
- Confirm owner-approved stable semantic version, Calibre tuple, codename, supported platform/minimum-version policy and release notes. This candidate identifies as `1.0.0 — The World`; version naming does not waive outstanding compatibility or resource findings.
- Confirm plugin/storage names remain compatible. Decide how old MangaNana library tags and bibliographic-only books are handled; test a synthetic and copied-profile upgrade before promising migration.

## Validate source and package

- Stage only reviewed source/resources/docs/tests; scan hidden files, personal paths, keys/cookies, generated databases/books and asset permissions.
- Include root license and every required third-party notice; clear supplied audio/artwork/favicons/native handoff rights. Verify the installable ZIP contains root LICENSE and the required third-party notices.
- Build from a fresh extraction with no original-worktree paths; compare every entry/resource to the chosen reference. Explain only intentional generated metadata differences.
- Run all applicable portable/full regressions; account for historical failures and missing captures. Never count skips as passes. Test discovery itself must work.
- Test the **exact final ZIP** installed in disposable Calibre, including startup, all providers, cancellation/close/shutdown, Bookmarks, mode/provider/library switching, large selections, preview/output settings and all six shaders/sound.
- Verify CBZ/PDF images/order/metadata and selection → plan → generated file → actual Calibre records. Cover duplicate policies, partial outcomes, nonnumeric labels, same-title distinct outputs and independent Series # edits.
- Check cold/warm network/cache behavior with bounded requests, respect provider denials and document limitations.
- Exercise actual supported OS/Calibre/DPI combinations and physical multi-monitor behavior. A declaration in metadata is not a tested matrix.
- Test fresh install, supported upgrades, downgrade/rollback copies, credential preservation and corrupt/future cache/Favorites handling.

## Updater and assets

- Verify updater repository/channel and controlled newer/equal/older/dev versions, errors/rate limits, Later/ignore/manual checking and busy-workflow install gating.
- Name exactly one eligible official installable asset, e.g. `MangaAnka-v1.0.0.zip`; do not include `test`, `dev`, `beta`, `alpha` or `source` in that stable plugin asset name. The updater accepts only stable tags and a unique eligible ZIP.
- Name the contributor archive `MangaAnka-v1.0.0-GitHub-Source.zip`; keep it distinct from the plugin. GitHub automatic source snapshots are not the curated source artifact.
- Record SHA-256 for both archives, contents, build/toolchain versions, final validation logs and release notes. Rebuild/retest affected cases after any change.

## Publication — owner approval required

- Obtain an explicit GO decision and publishing authorization. Do not equate a source rebuild with runtime qualification or license clearance.
- Publish release notes covering compatibility, recovery/upgrade instructions, known limitations, source/installable distinction and checksums. Attach only approved assets to the correct repository/stable tag.
- After publication, independently download/check hashes, install into a fresh disposable profile and verify the updater chooses the intended installable asset rather than the source ZIP.
- Monitor actionable defects without exposing user data. Preserve prior release assets/evidence. If rollback is needed, document affected versions and restore matching plugin/config/library backups; avoid blind retries or irreversible identifier changes.
