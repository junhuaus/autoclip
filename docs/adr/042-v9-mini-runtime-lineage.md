# ADR042: V9 mini runtime and persisted V5 lineage

Status: implemented, formally accepted and integrated in 20260913T072557Z-1fd20958; see SD-1B accepted report.
Date: 2026-09-12 PDT. Depends on ADR041 and accepted SD-1A quality/failure contracts.

## Decision

New mini_lesson requests use explicit `PipelineRunConfigV9`: semantic_windowed,
90/180/300 seconds, result schema5, `semantic-v5-lineage-v1`, and the unchanged
`semantic-v4-quality-v2` contract. Prompt identities are V2 Discovery/Chain/Boundary
and V1 Link/Global. All five prompt hashes are required and checked against installed
resources before use. Software version and historical run versions do not change.

`PipelineRunConfig` remains the exact V8 wire model. V2–V8 persisted field sets and
fingerprints remain exact; their in-memory adaptation ends at V8 with the recorded
quality contract. V9 is loaded through its own exact model and hash. `StageWork.config`
uses a schema_version-discriminated V8/V9 union so serialization preserves lineage
identity. Import changes run_scope through the actual config class and recomputes its
fingerprint. No database migration or automatic upgrade of a real run is performed.

Bootstrap activates V9 only for new mini requests, together with its actual Stage
dispatch. Other algorithms keep V8 defaults. Configuration and Stage implementation
are one publication package; an isolated intermediate configuration is not a release.

## Request and cache authority

Discovery request windows retain typed immutable IDs and time bounds. Complete raw
initial/sole-repair output must preserve both. The V4 validation-only projection receives
time ranges after the V5 identity comparison, preserving historical validation behavior.
Caller-owned request data is copied before Provider I/O/repair. Actual semantic cues keep
their original IDs/times, and every V5 call uses the same accepted raw diagnostics.

Stage caches store validated local Discovery IDs. Namespacing happens after fresh/cache
resolution, exactly once. V9 adds lineage contract and result version to affected cache
settings, including V4 Link/Global calls within that run. Historical records/keys remain
unchanged. A typed or rehashed cache still passes the current immutable context validator;
a syntactically valid changed window/ownership does not become authority.

## Persisted artifacts and final outcomes

The new `MiniLessonRoughArtifactV5` stores actual input plan, local and namespaced V5
Discovery outputs, Link requests/results, assembled chains, complete V5 Chain reviews,
candidate slots and source/config/run identity. Keeping both Discovery representations
allows a reloader to prove namespacing rather than guess or double-prefix IDs. SD-2 may
introduce a separately versioned compact transport; this decision does not truncate data.

Link uses an explicit V4 projection while V5 proposals and risks remain authoritative.
Every intersecting source/chain route and reverse derived-unit edge is validated. Boundary
receives complete sourced risk authority across its allowed expansion context. Existing
quality, duplicate, strict score and Top-N gates operate on explicit V4 quality views.

`UnifiedSemanticResultV5` embeds the typed full ledger, actual quality groups, exact semantic
unit-to-slot mapping and current persistent candidate IDs. The partition is built only
from the actual quality gate result. New statistics distinguish original proposals,
derived units and chain_new units; the ledger also counts terminal paths. A selected,
manual, blocked, rejected or Top-N-excluded unit is accounted for exactly once. A source
may have several outcomes. Empty Discovery/zero units remains a valid explicit result.

Long semantic IDs use the versioned `semantic_v5_` slot prefix plus the existing digest
strategy; every mapping is checked for collisions. No model identifier becomes a path,
command, SQL or filtergraph. Legacy V4 slot encoding remains unchanged.

On rough reload, recompute the actual input plan and validate local Discovery authority,
namespacing, required Link rounds, assembled chains, the complete graph and derived slots.
On saved edit reload, rebuild the ledger from the committed rough graph, rerun deterministic
quality gates against the actual transcript, and compare the recorded partition, persistent
IDs, selected edit plans and captions. Existing asset hashes, no-follow reads, lease fences,
atomic publication and idempotent state stores remain in force. A post-commit crash resumes
from this validated checkpoint without another semantic call.

New schema resources are `semantic_v5/rough-artifact-v5.schema.json` and
`semantic_v5/final-result-v5.schema.json`; the four ADR041 response/ledger schemas stay frozen.
Main owns both schema resources and shared config/DTO changes. One isolated Coder writes.

## Evidence and limits

Current diagnostics include actual V9 SQLite configuration/import/lease/StageWork roundtrips;
a 120-second synthetic MP4/SRT and complete two-source-to-one-unit ledger; post-candidate and
post-edit commit crashes followed by successful resume; and a second synthetic generation
reusing semantic caches with zero new semantic calls and unchanged first-generation bytes.
Actual shared quality gates also produced all five terminal groups on a many-to-many fixture.
A separate actual zero-candidate six-stage flow completed without downstream semantic calls.

These are diagnostic engineering results, not formal acceptance. Combined A+B1+B2 requires
fresh roles, unchanged deterministic sandbox Runner lint/test, current artifacts and Gateway,
followed by trusted original CAS publication. All27carried findings remain blockers until
that evidence is complete. Real content/model/hardware acceptance remains SD-6.

Acceptance update2026-09-13: [combined report](../verification/stable-delivery-sd1b-accepted-2026-09-13.md).
The preceding pending/diagnostic language records the decision at that historical point;
current implementation is integrated. Real content/model/audio/hardware acceptance remains SD-6.
