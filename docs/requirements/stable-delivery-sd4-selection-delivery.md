# SD-4 selection/delivery overview

This preparation is split into [B1 selection checkpoint](stable-delivery-sd4-selection-checkpoint.md)
and [B2 delivery binding](stable-delivery-sd4-delivery-binding.md) so each formal
run has a bounded, independently reviewable result. Start B1 only after A is formally
accepted. This overview is not itself a formal requirement or full SD-4 acceptance.

Continue a saved delivery-target intent for its exact project/run/generation. Reuse the
current review, delivery eligibility and immutable packaging services. Never treat a
completed processing run as a delivered ZIP, and never create an empty successful ZIP.
Read, watch, client disconnect and Worker shutdown do not cancel the goal.

Default selection must conditionally approve only still-pending, selected-for-review
candidate revisions inside the same BEGIN IMMEDIATE transaction as the decisions and
intent checkpoint. A human rejection on the same EditPlan revision remains excluded;
the earlier read in SelectionService is not commit authority. Manual selection requires
an explicit submission bit and exact candidate/revision set. An omitted submission parks
without attempts; submitted zero clips terminates with `no_selected_clips`, separate
from zero eligible candidates (`no_eligible_clips`). The checkpoint binds every selected
clip, revision and latest decision identity so later review-only changes cannot silently
approve a different delivery set.

At each effect and idempotent replay, check the current execution actor's active identity,
membership, action permission, archive state, run/generation and owned completion lease
on the SAME write connection. Review and deliver permissions differ; a saved requester
does not lend owner privileges to a later actor. Default selection, manual submission and
delivery enqueue use stable per-intent action identities. Commit each action result and
intent checkpoint together. A lost response after selection or enqueue must recover the
same decisions and one delivery ID/version. Reuse `load_eligible_delivery_set` and its
proxy/final master preference, quality/Asset/revision checks and snapshot fingerprint.
Observe an existing bound delivery rather than allocating another version. A failed or
stale render/delivery parks with a specific blocker; polling never resets their budgets.

Test an event-controlled same-revision human exclusion racing default selection, revoked
replay, actor downgrade, simultaneous reconcile, lost response after selection/queue,
changed revision or decision, missing/failed master, no candidates, explicit empty manual
submission, successful proxy master and final fallback, exact ZIP/manifest identity and
restarted Worker handoff on disposable SQLite and synthetic media. Preserve historical
review/delivery behavior and all A tests. Current formal lint/test and read-only review
remain required; full SD-4 waits for Worker/API wiring, real artifact inspection and final
trusted publication.
