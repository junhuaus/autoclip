# SD-4 bounded implementation B2: one bound immutable delivery

Start only from accepted SD-4 B1. Continue the exact saved selection checkpoint; no
later review or generation change may silently select a different delivery set.
Before a B2 Coder edit, trusted Main must place the compact `B2_BASELINE` PASS
receipt at `docs/verification/stable-delivery-sd4b2-preedit-receipt.json` and
the full accepted-B1 per-path hash manifest at
`docs/verification/stable-delivery-sd4b2-accepted-b1-hashes.json` in the new
isolated candidate. Inspect the compact receipt rather than printing the full map.
Record the exact B1 DONE run/fingerprint, identical inherited paths, named Main-owned
contract/document differences, matching HEAD/toolchain and absence of copied media.
Preserve any prior B2 blocked attempt and start a fresh recorded Coder session;
do not treat a copied directory or a prose assertion alone as inheritance proof.
For the successor to blocked `20260913T215934Z-1041ea6b`, trusted Main must
also prove the exact final isolated Coder source map and five changed paths
against that run's frozen candidate, record its Reviewer/Tester failure and
zero Runner results, and issue a fresh compact baseline for the successor.
The prior B2 receipt remains historical evidence, not the new candidate's gate.
Initialize the formal B2 run before freezing its candidate STATUS/ExecPlan, so
those documents name the current run and inherited source while leaving future
role and Runner outcomes pending. The trusted candidate root retains append-only
`qa/pipeline.jsonl` and `qa/test-report.md`; assurance source snapshots deliberately
exclude these preserved control paths. Inspect the root history instead of
classifying their snapshot absence as deletion. Reviewer runs before fixed Runner
and cannot require this run's lint/test receipts in advance; Tester requests the
checked-in command IDs, and Gateway correlates actual later receipts. Trusted Main
records final outcomes only after the frozen gates complete.

The existing `CompletionIntentRow.delivery_action_key` and `delivery_id` fields are
the durable binding: use the stable action identity `completion-delivery:{intent_id}`
for the one first enqueue, then observe the exact saved Delivery row and its immutable
version. Load the strict B1 selection checkpoint through validated JSON mode and
compare its complete clip/revision/decision projection with the current eligible
delivery set inside the effect transaction. Any mismatch blocks instead of silently
rebinding. A saved `delivery_id` is never replaced by a later project version.
Reconcile under the owned completion lease, checking current actor `deliver` permission,
membership, archive and run/generation inside the effect transaction before a first
enqueue or idempotent replay. A requester or previous actor grants no inherited rights.

Reuse `load_eligible_delivery_set` and its current proxy/final master preference,
quality/Asset/revision checks and snapshot fingerprint. If selected masters are still
running, defer with bounded `not_before` and no retry increment. An exhausted failed or
stale render parks with a specific blocker; periodic reconciliation never requeues it.
In particular, a historical incompatible success must not mask a compatible
queued/running replacement, and a newer failed optional final must not mask a
compatible running proxy. Test both mixtures on SQLite and show that each
defers, preserves retry count and later binds exactly one delivery when the
compatible master succeeds.
Do not launch an unconditional final-render pass. Missing or stale masters require an
explicit bounded recovery action with a stable saved ID, or a truthful actionable block.

Commit a stable per-intent delivery action key, the single delivery ID/version and intent
checkpoint atomically with the delivery enqueue. A response lost after that commit must
recover the same row, including when a previous delivery version exists. Observe only
that bound delivery. Test the combined lost-response plus pre-existing-version case,
not only each condition separately. Keep B2 saved action-key/delivery-ID and
blocker/retry recovery guidance current in the Main-owned operator guide before
formal review. Success requires the immutable manifest and requested ZIP Asset IDs;
processing completion or a zero-clip package is not delivery success. A failed delivery
parks and polling does not reset its retry allowance. Cancellation and Worker shutdown
retain truthful lease and atomic-artifact behavior.

Exercise actual SQLite, leased tasks and synthetic media: proxy master, compatible final
fallback, missing/running/failed/stale master, changed review decision, changed revision,
simultaneous reconcile, revoked replay, lost enqueue response, failed packaging,
publication crash, restarted Worker and exactly one package/version. Inspect current
manifest/ZIP media and Asset hashes. Preserve A/B1 tests and existing delivery behavior;
fresh Reviewer/Tester, fixed Runner lint/test and Gateway must pass before subsequent
Worker/API/CLI integration. No original product publication occurs at B2 alone.

The sole isolated Coder may edit completion runner/repository, TaskQueue, delivery
repository/snapshot helpers and focused unit/integration tests. Main retains migration,
models, shared DTO/ports, bootstrap, Worker, API, policy, ADR, ExecPlan and STATUS.
Preserve the fixed deny-default Runner and exact Coder session recovery rules.
