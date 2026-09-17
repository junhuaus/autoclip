# ADR045: Durable completion intent over existing business services

Status: accepted and published to the original worktree on 2026-09-14.
Date: 2026-09-13. The contract was based on accepted SD-3 source and
integrated through separately reviewed SD-4 A/B1/B2/C1/C2 candidates.

## User outcome and identity

A durable goal coordinates processing and optional selection/delivery after the initiating
client exits. It binds one exact project, run and generation. It neither creates a replacement
run on resume nor interprets the current project pointer as permission to follow a new run.
Historical runs without an intent retain their processing-only behavior.

Store versioned, strict intent options separately from immutable PipelineRunConfig: target
process_only/delivery, default/manual selection, ZIP option and optional preset identity.
Record the original requesting user, current execution actor, canonical request identity,
state/version, selection submission/checkpoint, fixed action keys, bound render/delivery IDs,
timestamps and safe outcome/error. Store no session token, credential or model instruction.
Original requester and current execution actor are distinct when an authorized resume changes
who is responsible for future actions. A later caller cannot borrow an earlier actor's rights.

Project/run/intent creation must share the existing project-create idempotency transaction.
Lost creation responses replay the same resource. Reusing a key with different canonical
options fails before mutation. Attaching an intent to an existing run is an explicit separate
operation; it verifies current identity and never silently creates a generation.

## Fixed reconciliation and task state

Add TaskKind.COMPLETION using existing ResourceClass.CHEAP and one identity-bound task per
intent. It performs bounded fixed actions over existing application contracts, without model
reasoning or generated commands. Observed resource state determines the next action:

| Durable observation | Action / visible result |
| --- | --- |
| Processing queued/running | Defer with real processing progress. |
| Processing completed, process_only | Succeeded / processed, with no delivery claim. |
| Processing failed/cancelled | Needs action with the exact bound failure; no recursive retry. |
| No eligible current candidates | Succeeded / no_eligible_clips; no package. |
| Manual selection not submitted | waiting_selection goal with a parked WAITING task; no recurring attempts. |
| Explicit submitted empty selection | Succeeded / no_selected_clips; no package. |
| Default selection not applied | Apply once, conditionally approving only still-pending clips. |
| Selection checkpoint and valid masters | Enqueue the exact delivery once and save its identity. |
| Required current render already queued/running | Observe the saved task; no duplicate enqueue. |
| Bound delivery queued/creating | Defer with actual packaging state. |
| Bound delivery succeeded | Succeeded / delivered with the authorized artifact identity. |
| Bound render/delivery exhausted or stale identity | Needs action with concrete reason. |
| Explicit goal cancellation | Cancel goal-owned coordination/work under current fences. |

An attempt that waits ends with the new DEFERRED outcome and returns its task to queued with
not_before. It increments truthful attempt history but does not consume retry_count. Keep
actual lost leases and transient failures distinct and bounded. Manual submission or explicit
resume can wake the task through CAS. Reconciliation never resets failed processing, render
or delivery budgets. Final poll intervals and needs-action wake behavior must be frozen with
the implementation, including an upper bound on idle writes.

Worker and foreground driving use a small fixed round-robin dispatcher for stage, render,
delivery and completion. BUSY in one category cannot indefinitely skip the others. Preserve
the existing single-heavy-task fence; adding a cheap category does not permit concurrent
heavy media work. Observation/refresh/Ctrl-C/client disconnect remains read-only and does not
cancel the goal. Explicit cancellation is a separate durable command.

## One transaction for authority and effects

Extract narrowly scoped connection helpers from the existing repositories so the completion
repository can compose existing review and delivery behavior inside begin_immediate. Do not
duplicate layout, revision, quality, eligible-master or delivery-version rules.

Before both a new effect and an idempotent replay, verify the bound run/generation,
current active user/membership and action permission in the same transaction. Worker
reconciliation additionally verifies its owned unexpired lease; an explicit human
submission instead checks expected intent version and parked task state. Reuse
require_project_action with database state. An earlier service check alone does not
close a membership-revocation race. Editor/reviewer permissions remain different:
permission to deliver is not permission to approve a clip.

Default selection must re-read the latest decision inside the effect transaction. A human
exclusion can change review status without changing EditPlan revision. Approve only clips
still pending at commit, preserve existing exclusions, and save the selection checkpoint in
that transaction. Manual submission binds an explicit candidate/revision set and submitted
flag; a missing submission is not an empty submission. Later changed revisions or decisions
cannot silently replace a frozen delivery set.

Selection and delivery effects use stable per-intent action keys. Save each action result
and intent checkpoint in the same transaction, so a lost response never allocates another
delivery version. Authorization and generation checks precede replay of those keys. Render
enqueue currently requeues matching failures; the coordinator must observe recorded IDs and
block exhausted failures instead of repeatedly entering that path.

For bounded B1, Main freezes a strict version-one `CompletionSelectionCheckpoint`
with intent/run/generation, mode, stable action key and an ordered tuple of selected
clip ID, exact EditPlan revision ID/number and latest decision ID. The table's separate
submitted flag distinguishes missing submission from an intentionally empty tuple.
After a nonempty B1 selection, `waiting_work` uses one honest DEFERRED attempt and a
60-second `not_before` without incrementing retry_count or enqueuing Delivery. A later
B1 poll validates the same checkpoint and defers without reapplying decisions. B2
replaces this interim handoff with one bound immutable Delivery. Manual pending remains
`waiting_selection` with a WAITING Task and no polling; submission wakes that Task to
QUEUED, and an owned attempt records the empty-selection terminal outcome.

Existing load_eligible_delivery_set already accepts qualified proxy masters with compatible
final-master fallback. Reuse them; do not add an unconditional second render. When genuinely
required, new rendering uses a frozen validated render profile and exact revision/epoch.
Cancellation cannot undo an already committed immutable delivery or cancel unrelated work
merely because it shares the project.

## Migration and cancellation boundaries to freeze

An explicit needs-action state must not create recurring attempts while awaiting a human.
Prefer a narrowly constrained WAITING task state for completion only, with a DEFERRED
attempt and no retry increment. Manual submission or authorized resume changes WAITING to
QUEUED under intent-version CAS. While processing/render/delivery is actually running,
ordinary bounded deferral uses not_before; distinguish this from parked manual/permission/
exhaustion work. Freeze the enum, transition and database constraint together in Main's
prerequisite, and update generic task cancellation/counting tests. Do not encode a parked
goal as a successful task, a fake failure, or an arbitrary far-future scheduling timestamp.

The existing janitor handles every non-running attempt joined through pipeline_run_id,
so completion attempts must retain normal temp_identity ownership and cleanup semantics.
The fair dispatcher tries each task category at most once per round; BUSY never terminates
that round. Stop after one actual handled action and rotate the next starting category.
Keep bounded polling separate from the CLI's read-only display refresh interval.

The current engine enables foreign keys on every connection and emits explicit BEGIN.
Both bootstrap and direct Alembic execution run transactional migrations; bootstrap supplies
a connection that is initially outside a transaction. Expanding the CHECK constraints on
tasks and task_attempts requires special handling: ordinary SQLite batch reconstruction of
these referenced parent tables with foreign keys enabled can cascade-delete child evidence.
Do not issue a no-op foreign_keys pragma inside an active transaction or rely on deferred
constraints to prevent cascade actions. The installed Alembic MigrationContext returns a null
transaction context when configured inside an external transaction. A supported narrow
approach is to disable FK enforcement through the migration connection's DBAPI cursor
before BEGIN, own one BEGIN IMMEDIATE around context.run_migrations(), run foreign_key_check
before that transaction exits, then restore FK enforcement after commit/rollback. Current
checked-in revisions contain no autocommit blocks or explicit commits. Prove this lifecycle
against both bootstrap's provided connection and direct Alembic entry, including injected
validation failure and restoration; do not assume configuration flags imply these guarantees. Before implementation, prove a narrowly scoped
migration connection lifecycle that temporarily disables FK enforcement outside a transaction,
rebuilds atomically, checks every foreign key before commit, and restores enforcement on every
success/error exit. Reject an already-active incompatible provided transaction. Application
connections must retain their normal FK behavior. This follows the [SQLite generalized
ALTER TABLE procedure](https://www.sqlite.org/lang_altertable.html#otheralter): create the
replacement, copy, drop the original and rename the replacement. Never rename the original
first, because SQLite rewrites incoming references. Verify populated parent/child rows, indexes,
CHECK constraints, rollback and re-upgrade on disposable copies; no user database is in scope.

Current request_run_cancel updates every queued/running task bound to a pipeline_run_id,
without filtering task_kind, and counts every running task before finalizing the run. Once
completion tasks share that run identity, processing cancellation must exclude completion tasks from
both task mutations and running-task counts, letting reconciliation surface processing_cancelled.
Preserve the preexisting stage/render/delivery cancellation behavior rather than narrowing
all historical operations to stage tasks. Otherwise the coordinator
could be accidentally cancelled or prevent run finalization. Durable goal cancellation is
separate and must preserve already committed artifacts and unrelated render/delivery work.

## Ownership and verification

Main owns the additive migration, constrained enums/models, shared DTO/ports, authorization
and transaction contract, bootstrap/Worker integration, ADR/ExecPlan/STATUS and publication.
One isolated Coder owns implementation paths under an explicit frozen allowlist; all other
roles are read-only. Preserve the existing deterministic Runner and gate budgets.

Test actual SQLite transactions/leases, including same-revision human exclusion, revoked
idempotent replay, disabled actors, generation/revision changes, lost responses after each
effect, simultaneous resume, explicit empty selection, no eligible clips, failed-task budgets
and bounded deferral. Verify old-data migration and FK/constraint parity on disposable backup
copies. Run a real synthetic API/Worker/FFmpeg flow with client disconnect and Worker restart;
inspect the actual immutable package and source read-only evidence. Require fresh formal
gates before trusted publication. Real model/content/audio/performance acceptance remains SD-6.

## C1 isolated Worker dispatch and shutdown decision

The C1 candidate reuses the shared queue and one CompletionRunner constructed by
bootstrap with the resolved generated-data directory and explicit configured
delivery retry bound. The Worker rotates stage, render, delivery and completion
in process memory. Each round attempts a category once, skips IDLE/BUSY and stops
after one handled action; only a handled action advances the cursor. `--once`
executes that bounded round. No persisted scheduler cursor or second business
transition implementation is introduced.

Manual WAITING has no polling; timed DEFERRED attempts honor `not_before` and do
not spend failure retries. A restart reclaims expired leases while retaining
selection/action and Delivery identities. Completion artifact inspection keeps
its bounded lease monitor active while files are checked, then must join an
in-flight SQLite heartbeat/observe operation before closing files or disposing
runtime. This includes a writer-lock wait that can outlive the normal poll interval.
The stopped monitor cannot renew a lease later. A shutdown does not mark an
interrupted attempt successful or erase its recovery history. Read-only clients
never dispatch or cancel. These rules were tested in isolated C1 acceptance
and carried into the published C2 integration.

## C2 fresh-create transaction decision

The new-project API body contains a nested JobCreateRequest and CompletionOptions;
existing-run creation contains only options. The public response contains the
authorized CompletionSnapshot and a nullable signed Delivery download URL.
Callers cannot submit trusted actor, project, run or Delivery IDs in a new-project
body. Strict versioned resume, manual selection and explicit cancellation are
separate from read-only observation.

CompletionService owns path syntax and fresh-source validation. It passes a
fresh-source guard to the repository, which invokes it under the same
BEGIN IMMEDIATE that first resolves same-key replay and current authority,
then inserts a genuinely new project/run/goal. Canonical idempotency uses the
original absolute request spelling before strict resolution. The guard returns
the resolved, allowed, readable regular file path for persistence. An API
supplied callback checks an already assessed Provider readiness snapshot only
for genuinely new work; it does not run a CLI login probe or inference while
holding SQLite's writer lock. Replays remain available after source or provider
loss, but changed requests conflict. Existing direct repository callers retain
their historical optional guard behavior. Fresh C2 formal lint/test,
Reviewer and Gateway PASS, independent source/retained-media audits and exact
original CAS publication are recorded in
`docs/verification/stable-delivery-sd4-accepted-2026-09-14.md`. The accepted
media evidence uses local synthetic content; real model/content/audio and
hardware acceptance remain separate SD-6 work.
