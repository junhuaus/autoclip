# SD-1B-B2: Run and reload mini lessons with complete V5 lineage

Accepted and integrated in combined formal `20260913T072557Z-1fd20958` on2026-09-13.
See [accepted report](../verification/stable-delivery-sd1b-accepted-2026-09-13.md). Historical diagnostics below remain preserved.

## User outcome and package boundary

A newly requested mini lesson uses the complete Discovery → Link → Chain → Boundary →
Global flow and persists every original proposal's actual terminal paths and sourced risks.
Reload, cache reuse and retry preserve the same authority and outcome. Existing V8 runs
and deliveries remain readable under their original configuration and validation contract.

This is one bounded runtime integration package: activate the new configuration together
with the Stage implementation, final typed result and persistence tests. Do not publish
a V9 flag that dispatches into V4 artifacts, or defer reload verification to another package.
It completes SD-1B engineering acceptance; actual model/content acceptance remains SD-6.

## Configuration and compatibility decision

Introduce explicit `PipelineRunConfigV9` for mini/semantic_windowed only, with fixed
90/180/300 second bounds, result schema5, lineage `semantic-v5-lineage-v1`, and the accepted
`semantic-v4-quality-v2` quality contract. Its five frozen prompt identities are V2 Discovery,
V1 Link, V2 Chain, V2 Boundary and V1 Global. V4 Link/Global retain their own schemas and
quality behavior; they receive explicit projections without replacing V5 authority.

Keep `PipelineRunConfig`'s exact V8 wire shape and historical v2–v8 loaders/fingerprints.
Use an explicitly discriminated V8/V9 runtime type where serialization crosses a boundary,
including `StageWork.config`. A V9 subclass serialized through V8 fields must not silently
drop lineage identity. Persisted loaders validate exact fields, version and original hash.
Historical adaptation continues to V8 with its recorded validation contract; it never
silently upgrades a historical run to V9. Import changes run_scope by validating through
the actual config type, preserving every identity and recomputing the fingerprint.

Only new mini requests from bootstrap select V9. Other algorithms retain V8 defaults.
Freeze shared constants in the domain layer if needed; application code must not import
pipeline implementation to obtain a contract string. No database migration is expected:
existing immutable JSON snapshots and committed assets carry the new version explicitly.

## Runtime implementation

1. Dispatch mini rough/edit on the explicit config version. Retain the historical V4 path.
   V5 Discovery builders and providers return local IDs with full typed risks. Validate local
   immutable batch/cue authority on both fresh and cache results. Namespace once after
   cache resolution, so retries and cross-generation hits do not double-prefix identifiers.
2. Plan Link rounds from a deliberate V4 compatibility projection. Keep the original V5
   Discovery objects throughout. Assemble existing Topic Chains, then require every original
   to have all intersecting routes. Build V5 Chain requests with immutable originals, exact
   routes and attributed risks; validate the complete graph after all responses arrive.
3. Persist a typed V5 rough artifact containing Discovery outputs, links, chains, complete
   Chain reviews and units. Preserve a checked bijection between semantic unit IDs and DB
   candidate slots. Use a versioned deterministic slot encoding for oversized IDs and
   reject collisions; identifiers remain data, never paths or executable strings.
4. Reload committed rough bytes as the V5 model and revalidate against the actual transcript,
   source hash, config and persisted candidates. Reject missing/extra/changed slots and
   authority. Build complete Boundary risk authority from the entire allowed expansion
   context; validate fresh/cache/repaired output against that immutable authority.
5. Use the accepted quality/duplicate/score/Top-N gate with explicit V4 projections for
   Global Review. Preserve V5 units and Boundaries separately. Build `FinalPartitionV5`
   only from the actual validated selected/manual/blocked/rejected/top_n_excluded groups.
   Build the typed ledger from the complete source graph, authorities, treatments and
   that partition. Zero sources/units and explicitly rejected routes are legitimate.
6. Freeze a V5 final result schema that embeds the typed ledger and actual quality result.
   Serialization must retain V5 fields, source evidence and every terminal path. Report
   original proposal, derived unit and terminal path counts separately; do not rename a
   derived-unit count as original Discovery count. Verify JSON/API reload and edit metadata.
7. Continue through existing fenced state persistence, revision creation and media delivery.
   Existing immutable/redacted failure audit and sole-repair behavior remain mandatory.
   Add lineage identity to affected cache/model settings without changing old records.

Prefer a small `pipeline/semantic_runtime_v5.py` helper for typed artifact orchestration and
projections, keeping business authority in the accepted pure lineage module. Reuse existing
request/cache/fence mechanics rather than creating a second queue or retry coordinator.
The accepted B1 Provider is a dependency; a concrete required correction needs an explicit
scope update before a new formal freeze, not an unnoticed edit outside Coder ownership.

## Ownership and acceptance

Main's shared integration paths: `application/pipeline.py`, `bootstrap.py`, an existing
domain contract module if required, new V5 artifact schemas and any repository annotation
needed for the runtime union. Product implementation remains one isolated Coder at a time.
Bounded runtime paths: `pipeline/stage_handlers.py`, the new runtime helper, and dedicated
configuration/repository/Stage integration tests. Main freezes the exact manifest after
implementation; no active formal source, policy, lock, role input or proof is edited.

Required before formal acceptance:

- V9 config JSON/StageWork roundtrip and real SQLite create/load/lease/import preserve all
  exact identities. V2–V8 field sets, fingerprints, defaults and immutable assets still pass.
- A real synthetic persistent Stage flow exercises many-to-many routes and source-risk
  accounting. Its final saved/reloaded ledger matches actual quality gates and DB slots.
- Zero, explicitly rejected, manual, blocked and Top-N cases retain complete terminal paths;
  no fabricated selected result. At least one mixed source has multiple terminal outcomes.
- Fresh, cache, cross-generation and sole-repair results preserve local IDs and namespace
  exactly once. Tampered cached/rough/context/slot data fails before downstream mutation.
- A mock mini user flow generates actual MP4/SRT/manifest/ZIP and a V5 final ledger; inspect
  current artifacts, full media decode, screenshots and persisted records. Synthetic model
  output establishes engineering behavior only, not real semantic quality.
- Fresh Planner/Coder/Reviewer/Tester, unchanged allowlisted sandbox Runner lint/test and
  Gateway pass on one frozen source/toolchain. Keep2plan/3code budgets and1MB full logs.
  Trusted outer publication requires actual current artifacts and exact original CAS.

## Progress and next action

- [x] Inspect config loader, StageWork serialization, import and bootstrap activation points.
- [x] Inspect actual V4 rough/edit/cache paths and accepted V5 APIs; identify projection,
  namespace, final partition and persistence boundaries above.
- [x] Bind the exact terminal A+B1 assurance source and its unresolved window-ID finding.
- [x] Implement and run concentrated config/persistence/Stage diagnostics in one candidate.
- [x] Freeze schemas/source, complete formal gates, inspect artifacts and publish.
- [x] Update SD-1B acceptance/recovery docs and continue SD-2 request budgets.

No commit/push, paid model batch, source mutation, cleanup, global configuration change or
automatic migration of real projects is introduced. Retain all prior terminal Loop runs.

## Integration decision at 06:05 UTC

Combined A+B1 formal20260913T055146Z-84311696 reached terminal BLOCKED06:04:25 after
Reviewer FAIL/P2 and Tester BLOCKED. Source7e153212 includes the exact recorded Coder's
request-copy fix and four new tests. Reviewer found request logical-window IDs discarded
while response count/times were checked; an internally consistent rename can pass.
No Runner, Gateway or current artifacts exist. Outer5463 exit2/724.614s and all complete
role logs remain intact. Do not reset/resume the terminal run or reuse its evidence as PASS.

To avoid another standalone contract-only cycle, carry A+B1 and this concrete correction
into the actual V9 Stage/persistence package. First prove and fix immutable window IDs in
the shared validator/provider context, then implement the runtime above. All26carried A
findings plus this P2 remain publication blockers until combined fresh gates and artifacts.
This changes the implementation package, not acceptance, permissions or retry budgets.

## Implementation evidence at 06:27 UTC

Preparation3f96 verified all2050inherited source hashes/original431CAS; setup44f6PASS.
Window-IDb3206FAILbefore,972b542PASSafter. V9 config2d866FAILbefore; a08d50PASS/1historical
fixture failure corrected by explicitly authoring V1/V7 data. Actual V9 Stagecc81FAILbefore
dispatch; b1f8FAIL/e2fb audit identified typed-window versus legacy time-only equality,
corrected after V5 identity validation. b55bPASS produced120secMP4/12cueSRT with2originals,
1derived unit and2terminal paths; actual0.5/60/119.5sec contact frames inspected.

4965:34mixed-outcome/config tests PASS. c9b8:V8 plus V9 post-candidate/post-edit commit crash
recovery PASS.0321:actual second generation reuses all semantic caches with zero new semantic
calls, stable local/namespaced IDs, new persistent candidate IDs and unchanged first-generation
bytes/source.3e6b:16runtime/cache checks PASS, including rehashed but context-invalid caches.
da63:actual zero-candidate six-stage SQLite flow PASS, no downstream semantic calls or clips.
a665:834focused regressions PASS27.87s; ba71mypy6sources and0044ruff PASS.

Main schema beed preserves all four ADR041 resources and adds rough-artifact-v5 (46859B,
03e97bd2d7948ee01215fb3ec457d5df238b7cc96e8d0b8d3098295c4ae94d2b) and final-result-v5
(60347B,72f20a5f5f762ec74a0dd8523707793235033697456a188b04bd78c38392f4ea).
The historical fixture adjustment in tests/unit/test_semantic_validation_contract.py is
included explicitly in main's final publication scope. All27findings remain pending fresh
formal revalidation. No original product code published. ADR042 records the actual decision.

## Planner capture correction at 06:38 UTC

Formal20260913T063236Z-1a254213 terminated before Coder/artifacts: complete Planner output
reached1MB while repeatedly reading historical Product/Solution/v1/v0.2 documents. Outer3a09
exit2/146.064s, observer1d7dFAIL correctly recorded no coding workspace. No product source
changed; exact6b4fb1ac/all2059hashes and original431CAS remain. Preparation95e1 copies that
source into sd1b-runtime-bounded-context-20260912. One replacement attempt uses the explicit
role reading index and deterministic relevant-section reader; preserve full files and all
gates/caps/budgets. No findings are closed and no product code is published.

Replacement freeze9e81 PASS/all2060source paths, original431CAS and six identical schemas;
source03e4a99f,toolchain5b9a79d5. Create71d8 verifies toolchain before/after. Formal
20260913T063915Z-e72e391f started06:39:24; Planner01a0997d-fc5f-7473-94f4-cac566581b8a
READY with177600B complete capture. Actual coding-1 proofcd48 PASS06:42:18; Coder now active.
Outer artifact-helper38ab proves V8/V9 inspection/full decode mechanics on separate diagnostic
copies, never final evidence. Recovery notes and SD-2 transport plan are prepared in original
main-owned docs while this frozen candidate remains unchanged.

06:56UTC: Coder01a09980-9dba-7c62-827f-34a5ca990770 IMPLEMENTED/no edits,264943B complete.
Assuranceac58 verifies exact2060source paths and all six schema/model resources. Reviewer
FAIL/two P2 identifies missing adversarial persistent Stage reload regressions and missing
manifest-bound terminal mini SQLite audit. Tester READY keeps both actionable gaps. Current
Runner lint064931-bf1a PASS27.82s; test064959-aa3b PASS359.999s:1803Python/13warnings291.31s,
58Web and browser11.4s/24.9s. Mini observerad46 validates both actual120secMP4/12SRT and the
V9 reconstructed ledger; retainerb8fb preserves22SQLite/66JSON/twoZIP. Final Gateway is active;
both P2 must route through the same recorded Coder's remaining budget. No publication.
Separate next-cycle observers bind source_cwd to exact assurance iteration; archive first-cycle
artifacts before collection. Final evidence and visual inspection must use the repaired source.

07:05UTC: Gateway001 FAIL/REWORK_CODE preserved the two P2; same exact Coder resumed at
cycle1/code2. It changed only the two authorized integration-test files, adding six actual
rehashed persistent Stage faults and redacted terminal SQLite audits as eighth manifest files.
Initial import/exception diagnostics failed and were corrected; actual focused8PASS65.83s,
Ruff/format PASS. Coder002 complete97636B. Assurance2263 PASS/source70c4f627/all protected
paths and six schemas. Reviewer002 PASS/no findings. First-cycle artifacts archived6930
under cycle-evidence/1-1; separate v3 observers bind the next test to exact assurance-1-2.
Outer audit inspectorb93f PASS verifies safe row whitelists, terminal task/attempt topology,
candidate/revision/media bindings on separate Coder diagnostic copies. This is not final
evidence. Fresh final Runner/current visuals/Gateway and trusted publication remain required.

## Browser artifact retention correction at 07:23 UTC

Formal20260913T063915Z-e72e391f ended terminal BLOCKED at Gateway002 after current Reviewer
PASS and Runner lint/test PASS (1809Python,58Web,two browser flows). Sole blocker: the test
cleaned its browser ZIPs before independent review. Main's outer copies were inspected but
not found by Gateway. Preserve final70c4f627 source, all complete logs and the blocked state.
This is a concrete fixture-evidence prerequisite correction under documented Loop recovery,
not a retry-budget change or resumption of that terminal run. The prior one bounded-context
replacement remains a separate preserved event. Original product still runs accepted V8.

Preparationf45b verifies all2060final source hashes and431original non-document CAS entries.
Only scripts/e2e_fixture.py, scripts/run_real_browser_e2e.sh and their unit test change.
Verified immutable ZIP bytes are retained before cleanup in
apps/web/playwright-report/browser-packages/<productRunId>/{delivery.zip,release.zip}.
An atomic manifest binds the exact run/project/config/source identities, both file hashes,
sizes and versions; the final command prints its relative path. No-follow dirfds, exclusive
run directories and manifest-last publishing prevent path escape, overwrite and false
completion. Only known synthetic artifacts are retained; no credentials, logs or full DB.

Diagnostics:11unit testsb09d PASS, mypyd174 PASS, actual browserd9d4 PASS38.402s; after-cleanup
inspectiondfea reopens both ZIPs and validates all checksums against the exact command log.
New formal fresh roles/allowlisted Runner/Gateway and actual current artifacts remain
mandatory; all28carried runtime/artifact findings remain pending until full acceptance.
Current candidate: .loop/development/sd1b-retained-browser-evidence-20260913/candidate.

Freezeedc3 PASS33.031s/all2060source hashes/37scope/431original CAS/sixschemas; exact
source39405cbd5683cbc88dba2d74fb7585c886fee3adc83e62b7a82f28e0b46c3809,
toolchain954cb20d915a8e23e9a416718700e75b49efa37611831b5edfb9dce51d747bbe.
Create7fcf creates formal20260913T072557Z-1fd20958. Planner READY; actual coding prooff871
PASS07:28:42. Coder cycle1 active, observers bind only assurance-1-1. Fresh gates pending.

At07:40:exact Coder01a099ab-1e49-74b1-8551-e4a0d93c6414 IMPLEMENTED/no edits; Reviewer PASS,
Tester READY; assurance5383 PASS/sixschemas/source39405cbd unchanged. Runnerlint1477 PASS
27.544s; testfdae PASS382.509s (1818Python/13warnings315.09s,58Web,browser11.4s/23.0s).
Mini5450 PASS V8/V9/eight files/SQLite/full decode; both actual contact sheets viewed.
Retainerbecf PASS22SQLite/66JSON/twoZIPs;1aca independently verifies90indexederrors,
all current log-bound manifest identities, both ZIP checksums, media/SRT and five viewed
browser images. Browser product run7e596db61a9f4c7ba7d83e9a4fe01c20 survives cleanup in
the actual final report directory. Current Gateway and trusted publication remain pending.

## Final accepted outcome

Combined A+B1+B2 and browser retention accepted as source39405cbd5683cbc88dba2d74fb7585c886fee3adc83e62b7a82f28e0b46c3809.
Publication6e23/33actual paths and post-integrationcc19 pass. All28findings are resolved
with current full Runner/artifact/Gateway evidence. Continue SD-2; real acceptance remains SD-6.
