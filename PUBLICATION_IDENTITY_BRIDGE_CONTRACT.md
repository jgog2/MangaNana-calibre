# Publication identity bridge v1

This is a separately versioned plugin-side artifact, **not** a reinterpretation
or migration of `catalog_schema_v1.json`. Catalog v1 still requires integer main
chapter IDs. No DDK database is read or written by this module.

The executable validator is `publication_identity.validate_bridge`. The JSON
schema describes the wire format; the validator additionally checks references,
exact scope, conflicting identity membership, duplicate acquisition bindings,
review state, evidence provenance, and bounds deterministically.

Each artifact has one exact `scope`: `canonical_work`, `edition`, `layout`, and
`language`. `revision` and `producer` are required. No edition folding or language
fallback is performed. Standard, colored, manga and webcomic identities must
have separate scopes. A work ID must be the canonical identity already established
by the plugin, not a fuzzy title match. Only one artifact/layout can be enabled.

`targets` name a publication identity consisting of exact string fields
`canonical_work`, `edition`, `layout`, `serialization_namespace`, `episode_token`.
Tokens are opaque: `0-01`, `0.01`, `0.1`, `0.10`, `Prologue 1`, and `1` are distinct.
An optional `reading_order` is an independently reviewed signed integer ordinal
(bounded to ±1,000,000), not an episode identifier or an inferred numeric alias.
It travels with approved mapped rows into volume plans, preview and output sorting.
Distinct approved episodes in one volume cannot share an ordinal. Authors must
review its relationship to any unbound legacy members, whose ordering is retained.
The Berserk export uses negative ordinals for its preliminary sequence and positive
ordinals for the regular sequence, preserving the accepted ordinary chapter order.
Without this optional field, the original sorting rules remain in effect.
The explicit collected `volume` is a non-negative decimal **string**; titles are
display metadata. No episode identity is derived from a title or list position.

`bindings` join an exact acquisition object to `target_id`. Acquisition fields:

| Field | Match rule |
|---|---|
| provider | Exact adapter ID |
| source_work | Exact selected manga URL; structural release aliases use the MangaDex manga UUID |
| record_id | Exact native acquisition ID, including a full URL when that is the native ID |
| url | Exact `source_url`, `url`, or HTTPS native ID, when the adapter supplies one |
| raw_label | Exact `original_label`, otherwise the preserved `chapter` string |
| numbering_namespace | Exact `numbering_group`, including an explicit empty string |
| language | Exact record language, otherwise the selected acquisition language |

An empty URL or label means **that field is absent**, not a wildcard. Legacy
adapters sometimes expose only a native record ID. That ID and source-work scope
remain mandatory. Original rows, source ordering, metadata, explicit volumes,
download IDs and URLs are retained untouched. No other provider's acquisitions
are substituted. The new identity travels in `_publication_identity` only when
an approved bridge matches; numeric output contracts are unchanged otherwise.

Targets and bindings each require `status` (`approved`, `pending`, `rejected`,
`conflict`), `revision`, and nonempty `evidence_refs`. Unapproved records require
an explicit `reason`; they cannot assign membership. Approved records require
`reviewer`, `reviewed_at`, and `relationship_verified: true`. Both the episode's
volume membership **and** the acquisition-content association must be approved.
Binding `content_relation` must be `one_to_one` to activate. Split/merged content
needs a future contract; it remains pending. Neither numeric offsets nor wildcard
or substring aliases are permitted.

Evidence entries require `id`, `source_url`, `revision`, `locator`, `inspected_at`,
and `authority` (`publisher`, `secondary_index`, `provider_metadata`,
`reviewed_content`). Review must distinguish those authorities. A JSON assertion
is not proof: DDK review must verify the cited evidence before export.

After association, multiple acquisitions of the same verified publication
identity remain ambiguous. Two verified distinct identities may safely reuse a
numeric label. Unassociated rows retain the conservative legacy behavior.
Provider-explicit volumes retain precedence. A conflict within a verified
structural identity blocks a bridge-derived membership; unrelated, unclassified
structural claims cannot contaminate it. All claims and integrity diagnostics are
retained; language/group alone never creates a serialization namespace.

Trusted packaged resources activate automatically when **Use verified publication mappings** is enabled (default). The package registry `assets/publication_identity/reviewed-registry-v1.json` explicitly lists reviewed artifacts with revision, exact scope and SHA-256. The worker validates both registry and artifact; it does not scan arbitrary directories, download updates, or consult a DDK database. Pending/rejected entries never activate. Multiple active artifacts claiming one scope fail closed. A new plugin package may replace or revoke entries through its registry without changing the identity engine. Restart Calibre after a package update so immutable ZIP resources are reloaded.

Work scope also accepts a strict subset of the reviewed scope's existing AniList/Kitsu identifiers. For example, `kitsu:8` identifies the same work as reviewed `anilist:30002|kitsu:8`; obtaining the AniList ID later must not remove eligibility. Every supplied identifier must occur unchanged in the reviewed scope. Contradictory IDs, duplicate service IDs, unknown services, titles, numeric chapter labels and substrings cannot establish this equivalence. The approved artifact and target identities retain their original full scope byte-for-byte. Edition, language, source URL, provider, acquisition ID, namespace, label and URL checks are unchanged. This comparison consumes high-confidence canonical identity already established by the existing discovery pipeline; it does not assign canonical identities or alter discovery ranking.

The saved preference disables automatic packaged mappings only. An explicitly set MANGAANKA_PUBLICATION_BRIDGE_PATH remains a development/testing override and takes precedence, including when automatic mappings are disabled. External files are not automatically trusted: they require explicit process configuration and the same strict artifact validation. Normal users need no environment variable. Normal logs identify the origin without exposing private paths.

Artifacts remain bounded to 2 MiB and 10,000 entries per array. Registry data is bounded to 64 KiB and 32 artifacts. Full artifact reads, hashes and compilation occur in the publication worker, with a bounded immutable LRU. Packaged registry digests, source resource stamps, preference values and external file stamps participate in generation inputs. Callback identity checks reject obsolete preparation. Preference changes restart the existing inventory/reference lifecycle and invalidate output preparation. Source-tree updates must replace resource files atomically; package updates take effect on restart. Malformed optional resources retain the conservative native/reference inventory and add a diagnostic; no partial artifact activation occurs.

Wikipedia parser version 11 preserves unnumbered bullets as title-only evidence,
including source document/revision, exact locator, raw text, volume and position.
The source edition is unassociated document scope, not an approved layout. Such
evidence never creates acquisition membership. The parser-version change requires
one normal bounded Wikipedia refresh; other reference caches retain their
existing contracts and TTLs. Fresh MangaDex responses retain every release claim
and available metadata. Older fresh caches remain usable without extra requests;
release-level evidence is unavailable until their normal refresh. Missing language
or content metadata remains unresolved.

The `mangadex-release-claims-v1` evidence container retains the raw aggregate and
bounded metadata response once. Exact release claims are expanded only when a
bridge needs classification. Its content digest participates in reference
fingerprints; it never supplies an upstream revision or grants approval.

Future DDK work is limited to authoring, reviewing, validating and exporting this
sidecar contract. No existing catalog producer must change. A future DDK editor
or richer split/merge contract is outside this plugin-side implementation.
