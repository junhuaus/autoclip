# SD-4 bounded implementation B1: durable selection checkpoint

Start only from a formally accepted SD-4 A source snapshot. This increment does not
claim delivery, Worker integration, or full SD-4 acceptance.
Trusted Main must establish the mandatory `B1_BASELINE` gate in
`docs/verification/stable-delivery-sd4b1-preedit-receipt-v5.json`, backed by the
full accepted-A per-path hash manifest
`docs/verification/stable-delivery-sd4b1-accepted-a-hashes.json`. The manifest
is line-bounded for inspection; use a JSON parser and print only summary counts
and changed path names, never the whole map. The first B1 formal attempt
`20260913T201908Z-dd0630c1` ended BLOCKED without source edits. The second
`20260913T202937Z-0515231b` ended BLOCKED after Reviewer PASS and fixed Runner
lint/test PASS because Gateway output exceeded its cap; its final JSON also
identified missing retained SQLite inspection and stale candidate docs. The
third run `20260913T211217Z-428f0959` ended BLOCKED before Runner because
fresh Reviewer/Tester required B1 recovery guidance in the candidate. The
fourth `20260913T212143Z-e7316970` ended BLOCKED before Runner: Reviewer
mistook intentionally excluded assurance QA journals for root deletion and
asked for Runner results before Runner; Coder correctly declined an outer-owned
change. Reviewer also requested current-run docs and same-candidate SQLite
artifacts. Preserve all four records. This new isolated successor must use a fresh Coder session and
fresh role/Runner/Gateway evidence, not reuse the previous PASS receipts.

Trusted Main supplies current retained synthetic SQLite inspection at
`docs/verification/stable-delivery-sd4b1-retained-sqlite.json`, including exact
database identities under this same candidate's ignored diagnostic root. These independent
diagnostics do not replace the fixed Runner. The new Gateway should inspect
the named artifacts and current STATUS/ExecPlan and `docs/mini-lesson-recovery.md`,
keeping command output bounded.
The trusted candidate root retains append-only `qa/pipeline.jsonl` and
`qa/test-report.md`. `tools/loop_engineering/toolchain.py` deliberately excludes
these preserved control paths from read-only assurance source snapshots; their
absence in an assurance `git diff` is not a deletion from the trusted root.
Verify root file identities and history there. Reviewer runs before fixed
Runner, so it cannot require this run's lint/test receipts in advance; Tester
requests them, then Gateway correlates actual current receipts. Preflight
STATUS/ExecPlan must name the current run and frozen source while clearly
leaving future session/Runner outcomes pending; trusted Main records those
actual outcomes in original status/evidence only after the frozen gates finish.

For a delivery-target intent bound to one project/run/generation, reconcile processing
through the existing lease and attempt protocol. A failed or cancelled processing run
parks with a truthful blocker and does not reset its retry budget. A completed run with
manual policy waits without periodic attempts until explicit selection submission.
Submitting zero selected clips is a real submission and ends as `no_selected_clips`;
no submission remains waiting. A completed run with no selected-for-review candidates
ends as `no_eligible_clips`; candidates all rejected by a human also end as
`no_selected_clips`. Neither outcome creates a ZIP or delivery row.

Default selection conditionally approves only the current selected-for-review candidates
whose latest decision is still pending inside the same BEGIN IMMEDIATE transaction as
the decisions and intent checkpoint. An earlier read is not commit authority. Existing
human rejections, including same-revision rejections, remain excluded. Manual selection
accepts only the supplied exact current candidate/revision set, records explicit
submission, and preserves a deliberate empty selection. A wrong revision, duplicate,
unknown clip or changed generation conflicts without partial decisions.

The versioned checkpoint records mode and each selected candidate ID, revision ID/revision
number and latest decision ID, in stable order. It is written atomically with review
decisions and intent version CAS. A later decision or revision cannot silently retarget
that checkpoint, nor may a newly approved candidate be added to the eventual package.
Main has frozen `CompletionSelectionCheckpoint` and `CompletionCheckpointClip` as
strict version-one application DTOs. The stored JSON binds intent ID, exact run ID,
generation, mode, stable per-intent action key and selected clip/revision/decision
identities; the table's separate submitted flag distinguishes an absent request from
an intentionally empty set.
The strict DTO round-trips through JSON mode; load the persisted JSON with
`model_validate_json` (or equivalent validated JSON input), since Python-mode
strict validation intentionally rejects raw enum strings and lists.
Use stable per-intent action identity so a lost response or repeated lease recovers the
same decision batch. Reuse existing review validation/invalidation, connection-scoped
helpers and authorization; do not duplicate review rules in CLI/API or the coordinator.

Before both a new effect and an idempotent replay, check the current actor's active
membership, `review_clip` permission, archive state and bound run/generation on that
same write connection. Worker reconciliation also fences its owned completion lease;
explicit human submission instead checks expected intent version and the parked task
state in its own effect transaction. The requester grants no saved privilege. A
revoked or downgraded actor cannot replay a once-valid action key.
Submission wakes the same WAITING task through the legal QUEUED transition; an owned
reconcile attempt records a terminal empty-selection outcome. Do not write an illegal
WAITING-to-SUCCEEDED task transition or synthesize an attempt for a human request.
For this B1-only handoff, a nonempty committed selection remains `waiting_work` and
the owned attempt ends DEFERRED with a 60-second `not_before`, unchanged retry_count
and no delivery row. A later B1 poll authenticates the same checkpoint and defers
without recording review decisions again. B2 replaces that branch with delivery
coordination; no Worker is wired in B1, so this interim state is not user-visible.

Test disposable SQLite actual leases and deterministic event-controlled races: human
same-revision exclusion versus default selection, actor revocation/replay, generation
change, simultaneous claims, lost response, exact manual set, submitted empty versus
unsubmitted, zero candidates, and changed revision. Preserve A tests and existing
SelectionService behavior. Fresh Reviewer/Tester, fixed Runner lint/test and Gateway
must pass before trusted publication to the next isolated candidate. No original
product publication occurs at B1 alone.

The sole isolated Coder may edit completion service/runner/repository, TaskQueue,
SelectionService, review repository and focused unit/integration tests, and may add one
connection-scoped selection helper under `src/liveclip/db`. Main retains migration,
models, shared DTO/ports, bootstrap, Worker, API, policy, ADR, ExecPlan and STATUS.
No model output may supply executable commands; Runner uses only checked-in argv IDs.
