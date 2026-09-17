# SD-4: Durable completion intent

Living ExecPlan prepared 2026-09-13 during SD-1B acceptance. SD-4 was
accepted and published to the original worktree on 2026-09-14. The timeline
below preserves earlier isolated and blocked states as historical evidence.

## User outcome

A saved processing or delivery goal survives client disconnect and Worker restart. Resume
continues the same project/run/generation, respects manual selection, reuses valid work and
returns the one immutable delivery bound to that goal. Processing completion alone is not
reported as delivery success, and empty results never manufacture an empty successful ZIP.

## Existing components to reuse

SelectionService.select currently applies default decisions only to pending-review clips;
manual mode receives an explicit set. It delegates to transactional ReviewService batch
review, whose repository already accepts IdempotencyContext, but SelectionService does not
yet pass that context through. DeliveryService.enqueue already accepts IdempotencyContext.
Keep those business rules in their existing services/repositories rather than duplicating
them in CLI/API, a completion runner or model-generated instructions.

TaskRow already has unique operation_key, not_before, separate attempt_count/retry_count,
expected_generation/revision fields and a leased claim protocol. Task kind and attempt
outcome are constrained enums. A waiting completion poll can reuse not_before and retain
actual attempt history while leaving retry_count unchanged; freeze a specific DEFERRED
outcome and legal transitions before adding it. No external scheduler is necessary.

Worker currently dispatches stage, render, then delivery work. Completion reconciliation
must be integrated into the persistent Worker and foreground driver with bounded fair
dispatch; it cannot exist only in the CLI's observation loop or starve other work by polling.
Authorization rules already exist in application/authorization.py. Reuse those rules with
fresh database identity/membership state at action commit, not a saved session credential.

## Contracts to freeze before coding

Main owns the migration, model/DTO/ports and ADR. One thin completion_intents table should
bind id, project_id, pipeline_run_id, generation, requesting user identity, target
(process_only/delivery), selection policy (default/manual), ZIP/preset options, canonical
request/idempotency hash, current state/version, durable selection checkpoint, delivery_id,
outcome/error and cancellation timestamps. Preserve all historical runs as processing-only
when they have no intent. Do not add fields to old immutable pipeline snapshots by default.

Creation, read, resume, explicit selection submission and explicit cancellation need clear
application contracts. Creation/resume idempotency binds the same canonical request and
caller; a reused key with changed request fails. Resume of an existing project never creates
a new project or generation. Explicit new-run operations remain separate. A later caller
must hold current access; it cannot borrow the original requester's formerly broader rights.

Each intent has an identity-bound cheap completion Task. Reconcile claims its actual lease,
checks intent CAS/generation and permissions, then chooses one deterministic fixed action:
wait for processing, wait for explicit manual selection, apply eligible default selection,
enqueue/recover the exact delivery, observe delivery or record a terminal outcome. A deferred
poll releases the lease and records an honest completed deferred attempt with not_before;
it does not consume transient-failure retry allowance. Failed processing/delivery becomes an
explicit blocked goal; reconcile must not recursively reset existing retry budgets.

Selection and enqueue crash windows require transactional idempotency and stable per-intent
action keys. Check current authorization, generation/revision and intended action in the
same write transaction as the business mutation. Extract reusable connection-scoped helpers
from existing repositories if needed, preserving their public behavior; an authorization
check followed by an unrelated later transaction does not close the revocation race.

Default selection applies once to eligible current candidates and preserves existing manual
exclusions. Manual has an explicit submitted flag/checkpoint so no submission differs from
an intentionally empty selection. Empty eligible output and submitted zero selection have
distinct terminal outcomes and no package path. A new generation or changed revision cannot
silently retarget the intent or reapprove a clip. Stale masters use existing render/delivery
rules with exact revision/epoch checks. Bind one delivery ID/version and recover it after a
lost response rather than enqueuing another version.

Cancellation changes durable intent/task state and respects existing lease and atomic-media
publication rules. Read-only watch exit, Ctrl-C or API client disconnect does not cancel the
goal. Worker shutdown unwinds owned work and leaves a truthful recoverable checkpoint.

## Implementation boundaries

- Main: schema/migration, enum/Task ports, shared CompletionSnapshot/action DTOs, authorization
  integration, transaction/idempotency contracts, bootstrap/Worker wiring, docs and integration.
- Sole isolated implementation Coder: completion service/repository/runner and selection
  idempotency pass-through plus bounded tests after the shared contracts are frozen.
- Existing source-media, credential, model-output, asset-ID serving and FFmpeg safety remains.
  No real-project database migration or automatic downgrade is part of development testing.

## Acceptance and recovery evidence

Use actual SQLite/leases and synthetic media, not only service mocks. Inject faults around
processing checkpoints, selection commit/lost response, delivery enqueue/ID checkpoint,
artifact publication and completion-state commit. Resume must preserve the same project,
run, successful semantic cache, manual exclusions and delivery version.

Cover concurrent resume/CAS, new generation, stale revision/master, explicit no selection,
zero eligible candidates, archived project, requester disabled, membership removal and
permission downgrade at the actual action transaction. Exercise automatic creation with
the existing project-create idempotency contract so lost responses cannot duplicate projects.

Run API-started completion after client disconnect; finish all processing while no CLI is
running; restart Worker before/after selection and packaging coordination. Verify persistent
reconcile continues without a client, bounded polling does not burn retries, and waiting
manual intent stays waiting. Watch/inspect creates no task and mutates no state.

Verify migration upgrade and old data on disposable copies after backup, constraints/FKs,
and recovery procedures. Complete fresh role/Runner/Gateway gates, actual current media,
SQLite and browser inspection, then trusted original CAS publication. Record exact commands
and artifact identities; real-content/model/hardware acceptance still belongs to SD-6.

## Progress

- [x] Inspect existing Selection/Delivery idempotency, Task scheduling and Worker dispatch.
- [x] Bind accepted SD-3 source and implement the initial migration, DTO, transaction and waiting contracts in the isolated candidate; formal review may still require changes.
- [x] Accept bounded A identity/processing coordinator under fresh full Runner/Reviewer/Gateway evidence; preserve both prior BLOCKED runs.
- [x] Implement one complete persistent reconciliation flow and fault/recovery diagnostics.
- [x] Complete formal gates and current artifact inspection; publish the accepted package.
- [x] Update recovery docs and proceed to SD-5 shared presets and complete observation UI.


## Verified selection race to close in SD-4

Read-only source inspection during SD-2 formal4aa6346f found a second default-selection
race: SelectionService.select filters pending_review in an earlier read, while
SqlAlchemyReviewRepository.review_clips_batch checks only current EditPlan revision before
writing each decision. A human exclusion can change review status without changing that
revision. Durable default selection must check pending status inside the same transaction
as its conditional decision, so it cannot overwrite a concurrent human exclusion. Preserve
explicit manual selection behavior. Add an event-controlled same-revision exclusion test;
a revision-only conflict test would miss this case.

The batch review and delivery repositories currently load idempotent resource IDs before
business checks. New completion authorization/generation checks must run before returning
an idempotent replay as well as before first mutation. Existing idempotency caller_scope is
an identity namespace, not current authorization. Test a revoked requester replaying a
previously successful action key, plus a resumed intent whose project changed generation.
Reuse connection-scoped application authorization and the existing resource fingerprint
checks; never persist a session credential in the intent.


## SD-3 formal-time source inspection (2026-09-13)

The current CLI finish path calls SelectionService then DeliveryService directly. Delivery
load_eligible_delivery_set already prefers a qualified current proxy master and accepts a
compatible final master as fallback. Do not add an unconditional extra final-render pass to
completion; reuse that existing eligibility contract. If a master truly needs new work, use
existing RenderService/repository validation for exact revision/epoch and keep a durable
render action ID. Queue observation must distinguish an in-flight master from an exhausted
failed render or a stale revision.

SqlAlchemyRenderRepository.enqueue_render automatically requeues a matching failed render
when called without an already-recorded idempotency replay. The completion coordinator must
never repeatedly call that path and reset its failure budget. Reuse the stable action key,
observe saved render IDs, and block exhausted failures. Freeze any newly required render
profile in the intent instead of rebuilding dimensions/encoder from changed restart settings.
No failed existing render or delivery is automatically reset by periodic reconciliation.

Connection-scoped helpers should preserve current batch review, eligible-master selection
and delivery version allocation. One current actor/generation/revision guard must run within
the effect transaction and before idempotent replay, not only in an earlier API or service
read. A decision-changing human exclusion can leave EditPlan revision unchanged: default
approval must therefore test latest pending-review status inside that same transaction.
Project roles differ: editor can render/deliver but cannot approve review; reviewer can
review but cannot render/deliver. Saved intents must not collapse these permissions into
borrowed owner privileges or persist a session token.

TaskKind currently has stage/render/delivery; ResourceClass already has CHEAP, so completion
needs no new resource class. Explicit DEFERRED attempts should return completion tasks to
queued with not_before and leave retry_count unchanged. Actual lost leases remain distinct
LOST_LEASE attempts and use bounded retry/recovery. Worker currently only tries render when
stage is idle, and delivery when both are idle: introduce bounded fair dispatch before adding
a cheap polling category, so waiting completion cannot starve heavy work or be starved by it.

This is read-only preparation. No SD-4 product code or migration exists; SD-3 candidate and
formal Coder ownership are unchanged. Freeze the actual contracts against accepted SD-3.


### 2026-09-13 11:26 UTC — migration and cancellation prerequisite

Read engine.py, migrations/env.py, bootstrap.upgrade_database and request_run_cancel.
SQLite connections enable FK enforcement and explicit BEGIN; both Alembic paths are
transactional. Expanding CHECK constraints by ordinary parent-table batch reconstruction
can cascade through task attempts, Assets and journals. ADR045 now requires a migration-only
connection lifecycle, FK validation before commit and restoration after every exit, proven
on disposable populated copies. No migration source or user database was changed.

Processing cancellation currently touches all task kinds sharing the run and counts all
running tasks. Completion must remain observable after processing cancellation; exclude
completion tasks from processing cancellation/finalization counts, preserve all preexisting
task-kind behavior, and keep explicit goal cancellation separate. This is a required Main-owned integration change, not permission for polling to
reset failed jobs. SD-3 formal 58ee94e9 remains active; original product is still SD-2.


### 2026-09-13 11:33 UTC — bounded waiting and existing selection authority

Verified ClipQueryRepository and delivery eligibility both restrict candidates to the exact
current run and selected_for_review revisions. Reuse this set; do not approve rough/manual/
blocked records merely because they exist in CandidateClipRow. Existing successful proxy
masters remain usable under the quality/Asset/attempt checks already in delivery_snapshot.

Human waiting must produce no periodic attempt/temporary-directory churn. Proposed ADR045
uses completion-only TaskStatus.WAITING plus DEFERRED attempt; explicit authorized
selection/resume CAS wakes it. Active processing/render/delivery waits still use bounded
not_before, with no retry increment. Main must freeze the TaskStatus CHECK and transitions
with the existing kind/outcome migration before Coder implementation. Janitor already joins
all non-running attempts through pipeline_run_id; retain its temp_identity ownership rules.

A round-robin dispatch round tries each category at most once, continues across BUSY and
stops after one handled action; next round starts after the handled category. This preserves
--once behavior and the single-heavy-task fence without starving cheap coordination.
These are design prerequisites only, prepared while SD-3 formalff1afbdf runs.

### 2026-09-13 12:05 UTC — actual disposable Alembic experiment

While SD-3 formal4829347c owns product writing, an independent ignored diagnostic at
`.loop/development/sd4-migration-prerequisite/verify_fk_rebuild.py` exercised the installed
Alembic and project SQLite engine on four disposable databases. QA20260913120504Z-bf37
PASS0.622s: ordinary parent reconstruction with populated self-reference fails its DROP;
without that value it cascades away attempts/journals and clears Asset owners. The proposed
external BEGIN IMMEDIATE / FK-off-before-BEGIN lifecycle preserves every row, self-reference
and index, restores FK enforcement, and rolls back both DDL/data on injected FK-check failure.
The first diagnostic2f25 failed because it expected cascade for the self-reference case;
its actual IntegrityError and full log remain retained, and the corrected cases distinguish
both failure modes. No product migration or user database was changed. Actual SD-4 populated
schema, direct Alembic/bootstrap paths and re-upgrade still require implementation tests.

### Additional transaction checks from the accepted SD-2 source

Delivery-set-v2 already fingerprints each selected revision, latest decision ID, chosen render
and media Asset hashes. Preserve that authority. The selection checkpoint must also retain
the selected candidate/revision/decision projection before missing renders are available;
do not substitute a count or project revision_epoch, since review-only changes do not advance
that epoch. A changed human decision after selection must block a stale delivery set.

create_run's active-work guard currently counts every queued/running Task and reports active
render/delivery work. Exclude the new cheap completion coordinator from this guard while
preserving all existing stage/render/delivery checks. An explicit authorized new generation
can then make an old intent stale; that intent must observe its original identity and park,
not prevent the new operation merely by polling or follow the new project pointer.

### 2026-09-13 18:57 UTC — isolated SD-4 implementation checkpoint

Accepted SD-3 formal run `20260913T180522Z-532b2b05` is DONE and published. A fresh
ignored SD-4 candidate was copied from those accepted product paths; the original remains
at SD-3. Main added the completion task/status/outcome enums and transitions, thin intent
table, additive migration, versioned application DTO/port, and connection-scoped current
user/membership/action/run guard. Processing cancellation and new-generation active-work
checks now exclude completion tasks in the candidate. The task port defines an honest
DEFERRED attempt for bounded work waits or human WAITING without retry consumption.

Disposable empty and populated direct/bootstrap migrations passed, including all populated
Task, TaskAttempt, Asset and invocation rows preserved and FK validation rollback/restoration.
Targeted migration/model QA `20260913185357Z-4eb1` passed 15 cases; SQLite cancellation,
generation and current-role tests QA `20260913185635Z-0e73` passed nine selected cases.
The historical asset-scope test has an intentionally partial stamped schema and stays
targeted to its own revision; the no-blur fixture was repaired to full FK integrity and
passes the current head. Earlier failed preflight receipts remain retained. Local candidate
editable-import relocation was corrected; formal Runner uses its own sealed source snapshot.

Next: finish exact queue deferral and connection-scoped review/delivery composition, then
run the sole isolated formal Coder against frozen Main-owned contracts. The Coder must not
write migration, DTO, ADR, ExecPlan, STATUS or original product paths. Fresh read-only
Reviewer/Tester/Gateway, fixed allowlisted Runner, current artifact inspection and trusted
CAS publication remain mandatory. No user database or supplied long source media was touched.

### 2026-09-13 19:26 UTC — first bounded A review and successor

Formal `20260913T190010Z-7534e06c` ended terminal BLOCKED at plan1/code2; its sole
Coder `01a09c27-7613-7891-95cd-c5eb20670990` remained within seven allowed paths
and did not edit protected contracts. It implemented atomic goal identity and process-only
coordination, then added four real SQLite cancellation/expiry cases and corrected the
expired-owner queue path. Fresh Reviewer found one P1 in Main-owned
`pipeline_repository.py::_cancel_owned_stage`: processing-owner acknowledgement still
cancelled completion tasks. Reviewer P2 found `defer_completion` read the clock before
waiting for the writer lock. The Coder correctly reported BLOCKED for the protected P1;
no Runner command or original publication occurred. Preserve the full run and budgets.

A separate isolated successor copied all 2119 source paths exactly from the final blocked
Coder snapshot, with the old snapshot and run untouched. Main excluded completion tasks
from the remaining processing cancellation update and moved deferral's clock read inside
BEGIN IMMEDIATE. An event-controlled SQLite writer-lock case crosses lease expiry and
also checks a valid delay starts after lock acquisition. Successor QA
`20260913192359Z-3ac8` passed 74 targeted cases, `20260913192500Z-1461` passed the
lock case, and `20260913192523Z-482f` passed full lint; Doctor READY. One Coder-owned
long line was wrapped for lint. New formal `20260913T192617Z-2fb21a52` is active in the
successor. Those local diagnostics are not formal acceptance. Original remains accepted SD-3;
SD-4 A, the rest of SD-4 and SD-5–7 remain unaccepted.

### 2026-09-13 19:54 UTC — second A gate and historical-test successor

Successor formal `20260913T192617Z-2fb21a52` had fresh Reviewer PASS and no scope
breach. Fixed Runner lint failed one 101-character line; full test completed with
2147 passing and one failing historical migration case. That test enumerated all
current ORM tables against a database intentionally held at revision
`f3b6d9a2c841`, before the new completion table exists. Exact Coder
`01a09c3f-be43-7d33-9d0c-ed8db0d197d3` fixed the line, added a committed-
response-loss reconnect regression and honestly ended BLOCKED at plan1/code2
because the remaining test was Main-protected. No Gateway or original publication.

Separate isolated `successor2` copied 2121 final Coder source paths with matching
hashes, HEAD and ready local toolchain. Main changed only the protected historical
test's snapshot table set and relocated its Alembic parity check to the current
head, retaining the old journal upgrade/downgrade row comparison. Main formatted
the new completion migration test. Prior failing case diagnostic
`20260913195228Z-e253` PASS, full lint `20260913195254Z-5fbf` PASS,
151 targeted completion/migration/queue/cancellation cases
`20260913195316Z-de98` PASS. An earlier wrapper NameError was recorded as ERROR
before running a test. New formal A requirement is prepared; fresh full gates,
role review and Gateway are still required. SD-4 B1/B2 and C1/C2 are now bounded
separate requirements. Original product remains accepted SD-3.

### 2026-09-13 20:17 UTC — bounded A accepted

Formal `20260913T195517Z-dbc6dc0c` reached DONE with exact new Coder
`01a09c59-9669-7ae0-ba05-c14f3d76222f` making no source edits, fresh
Reviewer and Gateway PASS, fixed Runner lint `20260913T200157Z-e21c` PASS and
test `20260913T200226Z-9379` PASS. Full counts: 2149 Python, 58 Web and
two browser cases. Deterministic retained-file evaluation found no reasons;
candidate and assurance match the accepted source fingerprint
`f28edbcdfd9a62543d8d9f4164fe9e597f67a1087daaf5ecc5e7c2aa3cc078c7`.
Current synthetic browser ZIP hashes, archive contents and one contact sheet were
inspected. The detailed [bounded A report](../verification/stable-delivery-sd4a-accepted-2026-09-13.md)
distinguishes formal gates from local disposable SQLite diagnostics and keeps
both prior BLOCKED runs. This accepts only the A coordinator in its isolated
candidate; original product is still accepted SD-3. Next start B1 from this exact
DONE snapshot, then B2, C1 and C2. Full SD-4 requires current end-to-end
artifact/browser inspection, recovery docs and final trusted original CAS publication.

### 2026-09-13 20:19 UTC — B1 selection checkpoint started

The isolated B1 candidate copied all 2122 source paths from A's DONE delivery
workspace with equal hashes and HEAD. It added only the B1 requirement and current
Main-owned status/evidence documents, with no input media or user data. Loop Doctor
READY. Formal `20260913T201908Z-dd0630c1` is active; its sole Coder must keep to
completion/selection/review/queue helpers and focused tests. B1 remains unaccepted
until fresh independent roles, fixed Runner and Gateway all pass. B2/C1/C2 remain.

### 2026-09-13 20:25 UTC — B1 pre-edit evidence and shared shape

First B1 formal `20260913T201908Z-dd0630c1` ended BLOCKED at plan1/code1.
The sole Coder changed no files, correctly requesting an explicit trusted per-path
A→B1 inheritance receipt and a frozen v1 checkpoint/handoff convention. No
Reviewer, Runner or Gateway ran; the block and consumed budget remain retained.

New isolated `b1_successor` copied all 2122 accepted A paths from the DONE
candidate. Main added strict `CompletionSelectionCheckpoint`/
`CompletionCheckpointClip` application DTOs and a focused contract test, and
recorded the exact interim B1 behavior: after nonempty selection, `waiting_work`
defers the owned attempt for 60 seconds without another review decision, retry
increment or Delivery row. Manual pending stays WAITING until explicit submission,
which wakes the same Task. ADR045 and the B1 requirement now state this shape.
Next retain the complete source-map inheritance receipt, run local lint/targeted
tests, and launch a new formal run with fresh role/Runner/Gateway evidence.

### 2026-09-13 20:29 UTC — B1 successor preflight complete

The trusted `B1_BASELINE` v2 receipt and full per-path accepted-A hash manifest are
inside the new candidate under `docs/verification`. They verify all 2122 accepted
A paths, 2118 byte-identical inheritances, four existing Main-modified paths,
named new files, zero deletion, identical HEAD, ready local toolchain and no copied
source media. The receipt SHA256 is also retained outside the candidate. A strict
checkpoint JSON-mode contract test passed six cases `20260913202641Z-7d39`; full
lint passed `20260913202700Z-4c93`. The prior Python-mode fixture and Ruff format
diagnostic failures remain recorded. Loop Doctor READY. New formal B1
`20260913T202937Z-0515231b` is active, with fresh Coder/session and assurance
roles; no original product publication or B1 acceptance yet.

### 2026-09-13 20:39 UTC — B1 first review requires repair

Exact Coder `01a09c78-663a-7d60-befe-a1ea61a639ba` changed only five allowed
completion/review/queue/test paths. The first fresh read-only Reviewer found two
P1s: a failed final lease fence could commit review effects without the durable
checkpoint, and actual SQLite selection/race/replay tests were missing. It also
found two P2s: an identical manual submission could not replay after later
reconciliation advanced the intent version, and an empty current candidate set
could bypass authentication of a saved nonempty checkpoint. The formal loop is
resuming only that exact Coder session in code cycle 2. No B1 Runner or Gateway
evidence exists yet; keep B1 unaccepted and both review findings and source
identities intact.

### 2026-09-13 20:54 UTC — B1 repair under full Runner

Coder cycle 2 kept the exact recorded session, added a rollback-triggering
failed-lease fence and eleven groups of disposable SQLite selection tests. Its
local targeted claims are not formal evidence. Fresh read-only Reviewer `002`
PASS found no actionable defects; Tester READY requested the fixed lint/test
allowlist IDs. Fixed Runner lint `20260913T204922Z-137d` PASS in 26 seconds;
the full fixed test `20260913T204948Z-3f29` is running. Gateway and deterministic
retained-file verification are still required. No original publication occurred.

### 2026-09-13 21:04 UTC — B1 Gateway blocked despite passing Runner

Fixed Runner test `20260913T204948Z-3f29` PASS in 631.080 seconds: 2206 Python,
58 Web and two browser E2E cases. Source/head/toolchain identities remained
unchanged before and after lint/test. Fresh Reviewer `002` had no findings.
The Gateway final JSON rejected B1 because pytest's temporary SQLite fixtures
were deleted by the Runner sandbox and candidate STATUS/ExecPlan had not been
updated from pre-implementation. Its read-only command printed the entire
365,930-byte one-line accepted-A hash manifest, pushing the 1 MB agent log
past its hard cap. The trusted outer process correctly marked run
`20260913T202937Z-0515231b` terminal BLOCKED; no source publication occurred.

An initial blocked-source clone attempt encountered the assurance snapshot's
shared `.venv` symlink; its failed scratch was removed after retaining an ERROR
receipt. The corrected isolated `b1_successor2` copied the original candidate's
local toolchain and overlaid all 2129 tested assurance source paths, verifying
byte equality, HEAD and fingerprint `6862035ddfab6c318bd87dc20efe92807832c90680bfa7f63e58988857498d3a`.
It retained the prior QA records and copied no input media. Main must reformat
the inheritance manifest, record retained synthetic SQLite state and current
docs, then start a new formal run with a fresh Coder/session and all gates.

### 2026-09-13 21:09 UTC — retained B1 SQLite inspection

The new isolated successor reran the B1 selection file with a fixed ignored
`--basetemp` root. QA `20260913210737Z-ca7e` PASS, 54 cases in 11.90 seconds;
the immediately preceding attempt `20260913210703Z-a244` failed fixture setup
because its parent directory was absent, and remains recorded. Main inspected
six retained disposable SQLite databases in read-only mode and wrote exact
paths/SHA256, Alembic head, integrity/FK checks, goal/checkpoint/task/attempt,
review decision and Delivery rows to
`docs/verification/stable-delivery-sd4b1-retained-sqlite.json` in the candidate.
The default and manual nonempty checkpoints stayed `waiting_work` with actual
DEFERRED attempts and retry0; empty and no-eligible cases had distinct terminal
outcomes and no Delivery; the failed final fence left prior Delivery queued,
review decisions empty and completion intent unmodified. The candidate's
product-tree hash equals the formally tested assurance source. This diagnostic
supports independent inspection but cannot substitute new formal Runner gates.

### 2026-09-13 21:12 UTC — B1 successor v3 formal started

The accepted-A map was reformatted as 2131 bounded lines (only 7046 bytes in
its first 70 lines) without changing its 2122 path/hash entries. Trusted Main
issued a `B1_BASELINE` v3 PASS receipt: 2131 source paths before coding, zero
accepted-A deletion, only named documentation/evidence differences from the
2129-path tested blocked assurance, six retained SQLite hashes, matching product
code, HEAD and ready toolchain. Candidate fingerprint
`d47bd981b91eacd0eeb8d24fd596353e2b7a7c3a3ed2cf92b01a9e5ec84e37f7`.
Local `make lint` `20260913211111Z-bacb` PASS and Loop Doctor
`20260913211150Z-8faa` READY. Fresh formal B1
`20260913T211217Z-428f0959` is running with new roles and budgets. The prior
Gateway failure and diagnostic fixture setup failure remain retained; no B1
acceptance or original publication is claimed before fresh gates.

The [isolated B1 recovery guidance](../mini-lesson-recovery.md#sd-4-b1-selection-checkpoint-recovery-isolated-candidate)
now covers exact lost-response replay, current authority, waiting-task wake,
deferred retry preservation and stale checkpoint diagnosis. It is Main-owned
documentation for the next fully verified candidate, not a claim that the
active formal snapshot changed or that Worker/API/Delivery integration exists.

### 2026-09-13 21:19 UTC — B1 v3 stopped by Tester before Runner

Formal `20260913T211217Z-428f0959` reached Planner READY and exact fresh
Coder `01a09c9f-cc4a-72c0-acd4-b554ae1f8dba` made zero source edits. Fresh
Reviewer found one P2: the frozen candidate still lacked B1 guidance in
`docs/mini-lesson-recovery.md`. Tester returned BLOCKED on that prerequisite;
the run is terminal without fixed Runner or Gateway evidence. Its source,
findings and consumed budget remain intact. Main has now added the guidance
and links to the original worktree, but never modified the active formal
candidate. Copy the exact blocked source into a new isolated successor,
add only Main-owned docs/evidence, bind a new inheritance receipt and rerun
all gates with a new Coder session.

### 2026-09-13 21:22 UTC — B1 successor v4 formal started

`b1_successor3` copied all 2131 prior blocked source paths byte-for-byte,
including the tested product implementation; no source media moved. Main added
the recovery guide and linked it from STATUS/ExecPlan, refreshed the B1
requirement and issued `B1_BASELINE` v4 PASS. The receipt binds the accepted-A
full map, previous formal BLOCKED source, four named Main-doc differences,
six unchanged retained SQLite hashes, HEAD and ready toolchain. Its final
pre-edit fingerprint is
`fb2babd27533369fd0fa72803dffa075fef24f86c4e9d7a5db615cbc6fb2726e`.
Local lint `20260913212107Z-f04f` PASS and Loop Doctor
`20260913212129Z-3c2f` READY. New formal B1
`20260913T212143Z-e7316970` is active. Prior review/Runner evidence is
historical only; new roles, fixed Runner, Gateway and original publication
remain required.

### 2026-09-13 21:30 UTC — B1 v4 Reviewer/QA location block

Formal `20260913T212143Z-e7316970` had Planner READY, exact Coder
`01a09ca8-7552-79b2-a6a6-2e617376926f` with zero edits, then a fresh
Reviewer FAIL with one P1 and two P2. The P1 treated absent QA journals in
the read-only assurance snapshot as deleted and demanded current Runner
receipts before Runner. Coder's exact resumed session correctly returned
BLOCKED: `toolchain.py` deliberately omits those preserved control files,
`store.py` excludes them from source fingerprints, and `runner.py` appends
under the trusted config root only after Reviewer/Tester. Both QA files are
present at that root; the run ended before fixed Runner/Gateway and no source
publication occurred. The P2s remain useful: freeze the current run ID in
candidate docs before formal start, and retain/reverify six SQLite artifacts
under the exact candidate's ignored diagnostic root. The next successor must
also bind all historical root QA entries plus isolated Runner records without
editing, deleting or forging old results, and explain the snapshot boundary
to fresh reviewers.

### 2026-09-13 21:33 UTC — B1 v5 same-candidate evidence prepared

New `b1_successor4` copied all 2132 blocked source paths byte-for-byte, same
HEAD and local toolchain, no input media. Its trusted root QA journals now
start with the original 997-request append-only history and append the four
isolated formal Runner requests without altering either sequence. The merge
receipt records both source hashes and the merged hashes. The same candidate
ran 54 B1 selection tests PASS `20260913213114Z-956d`, with six retained
synthetic SQLite databases under its own ignored `.loop/diagnostics` root.
Read-only inspection records exact DB hashes, Alembic head, quick_check, FK,
goal/checkpoint/task/attempt/review/Delivery rows in its source evidence JSON;
that independent diagnostic is not fixed Runner evidence.

The next formal run ID `20260913T213239Z-1b3efdca` was initialized before
final source freeze so this ExecPlan and STATUS can name it honestly while
Coder/session and Runner/Gateway outcomes remain pending. Its v5 baseline
receipt binds the complete accepted-A map, prior blocked source, exact
Main-owned differences, current root QA identity and same-candidate retained
DB hashes. Assurance snapshots intentionally omit the preserved QA control
files; Reviewer must check the trusted candidate root for history, while
Tester/Runner/Gateway handle fresh command receipts in workflow order.

`B1_BASELINE` v5 finalized PASS at 21:34 UTC with 2133 source paths and
fingerprint `e1adc932d1cb2ce33c4a689ad288595d68dd4cf565e94eb771ed1d2b37373e66`.
The six local database hashes and initial 1002-entry root QA identity matched
the receipt after Loop Doctor READY. Formal
`20260913T213239Z-1b3efdca` is now running; its Coder, Reviewer, Tester,
Runner and Gateway outcomes remain pending and no original publication occurred.

At 21:39 UTC Planner reported READY. The sole isolated Coder session
`01a09cb4-9845-7123-b402-7358e030a5e3` reported IMPLEMENTED in coding
cycle one, changing only `completion_repository.py` and the focused SQLite
selection test in its disposable coding workspace. The fix preserves an
explicitly submitted empty checkpoint as `no_selected_clips` when live
eligibility later disappears. No Coder test PASS was claimed. Fresh read-only
Reviewer is active; the candidate and original product source remain unchanged
until deterministic and semantic gates accept publication.

At 21:42 UTC fresh Reviewer PASS had no findings and fresh Tester READY
requested only checked-in `lint` and `test` IDs. The fixed sandbox Runner
lint request `20260913T214209Z-7891` passed without source/toolchain mutation;
full test `20260913T214239Z-788a` is running. Neither Gateway nor final
publication is recorded yet. Main prepared independent post-gate verification
outside the frozen candidate; no formal evidence was edited.

At 21:54 UTC fixed `test` PASS completed in 687.304 seconds: 2207 Python
tests, 58 Web tests and both mock and real local API/Worker/FFmpeg browser
flows. The lint and test receipts use the same source fingerprint
`ee8a0cef500329512a2dcc96deadb46776e2fb43bbeefe3ed76cdd29914eb47f`
and unchanged post-command toolchain fingerprints. Gateway and independent
retained-file validation remain pending, so B1 is not yet accepted.

### 2026-09-13 21:58 UTC — B1 accepted in isolation

Fresh Gateway PASS with no blockers moved formal
`20260913T213239Z-1b3efdca` to DONE at 21:57 UTC. Independent deterministic
Gateway evaluation with retained-file verification passed with no reasons.
The accepted candidate and assurance snapshot match on all 2133 source paths;
the sealed Runner toolchain fingerprint, both QA command IDs and six indexed
same-candidate SQLite hashes, integrity checks, foreign keys and Alembic
revisions also matched. The trusted outer process published the Coder's two
changed source paths into `b1_successor4` only after all gates passed.
See [B1 bounded acceptance](../verification/stable-delivery-sd4b1-accepted-2026-09-13.md).
The first independent helper attempt compared the mutable candidate development
toolchain to the sealed Runner toolchain and failed locally; it was corrected to
hash the Runner's sealed external toolchain and then passed. The formal Gateway
and Runner were unaffected. Original product remains accepted SD-3. Next clone
the exact B1 DONE source to B2, freeze current B2 run/docs and full per-path
baseline, then implement immutable delivery binding through the sole isolated
Coder. C1/C2 and full SD-4 publication remain pending.

### 2026-09-13 21:59 UTC — B2 accepted-source handoff initialized

The trusted clone copied all 2133 accepted-B1 source paths byte-for-byte into
`b2`, with matching HEAD and toolchain readiness, no media, and only the
Main-owned B2 requirement added. Accepted B1 fingerprint is
`ee8a0cef500329512a2dcc96deadb46776e2fb43bbeefe3ed76cdd29914eb47f`.
B2 run `20260913T215934Z-1041ea6b` was initialized before candidate
STATUS/ExecPlan freeze so those documents can name the current run honestly.
The mandatory full accepted-B1 hash manifest and compact `B2_BASELINE`
receipt bind only named Main-owned STATUS, ExecPlan, B2 requirement and B1
acceptance-record differences. The receipt records the frozen candidate and
1004 trusted-root QA request identities; Loop Doctor READY. No B2 Coder edit
or acceptance exists yet. Final pre-edit fingerprint
`7090372ab2d3bcd1d3e492343e022d999985883b5df43fd366647f190b744f5c`
and receipt SHA256
`6d2988e79f90d9dd761d9e1c9d534b0550ec0d1c9e3d7f59699f03bb77558b39`
were independently rechecked with root QA hashes and no media copy before
formal `make loop-run` started at 22:02 UTC. Fresh B2 outcomes remain pending.

Read-only inspection of the active B2 Coder draft at 22:26 UTC identified an
acceptance check for later review: its first delivery enqueue currently passes
literal `max_retries=3` while the existing DeliveryService uses configurable
`settings.max_stage_retries` (0–20, default 3). The draft is not published or
accepted. Before B2 acceptance, verify that the final implementation preserves
the configured bound rather than only the default case. The same draft adds
connection-scoped enqueue and focused SQLite/FFmpeg tests; their local outcomes
and fresh formal gates remain pending.

At 22:37 UTC the sole isolated Coder
`01a09ccc-e72e-7eb1-a725-e2515079b88c` reported IMPLEMENTED. Its five
changed paths are completion and delivery repositories, delivery snapshot,
the new `test_completion_delivery.py`, and B1 selection tests updated for B2's
replacement of interim deferral. It reported local 204 regression tests, 44
B2 tests plus 11 guard tests, targeted lint/type checks, four inspected
retained SQLite/package fixtures, 27 Asset hashes and three ZIPs. These are
Coder claims and retained diagnostics, not fixed Runner evidence. Fresh
read-only Reviewer is active. The literal first-delivery `max_retries=3`
remains in the Coder source and needs review against configurable
`settings.max_stage_retries`; no B2 publication or acceptance has occurred.

At 22:39 UTC fresh read-only Reviewer `001` returned FAIL with one P1 and one
P2. The P1 is that synchronous delivery artifact inspection can exceed the
completion lease, burn its retry budget through repeated lost leases and never
finish a valid package. The P2 is that an obsolete successful master can mask
a compatible queued/running replacement and park the intent. The formal
control plane entered code cycle 2 and resumed only the recorded B2 Coder
session. Require a renewed owned lease during inspection, cancellation/loss
fencing, a multi-lease successful test, and mixed historical-success/current-
replacement SQLite coverage before accepting B2. Tester, fixed Runner and
Gateway have not run; original product remains accepted SD-3.

At 22:55 UTC formal B2 `20260913T215934Z-1041ea6b` ended terminal BLOCKED
at plan1/code2. The same exact Coder session closed the P1 with lease renewal,
cancellation/lost-lease checks and a multi-period SQLite test; it reported 50 B2
and 204 existing local cases passing. Independent read-only inspection found
50 valid retained SQLite files and 20 ZIP paths, one deliberately corrupt in a
tamper test. Fresh Reviewer `002` returned FAIL for the remaining P2: an
incompatible historical success, or a newer failed optional final render,
can mask a compatible active master and park the intent. Tester `001` BLOCKED
before fixed Runner, also requesting the combined existing-version/lost-response
regression and B2-specific recovery guidance. No fixed Runner, Gateway or
candidate publication occurred. Preserve the blocked run, all five final Coder
source differences and role evidence; clone only exact final isolated Coder
source into a fresh B2 successor with a new full baseline and Coder session.

At 22:58 UTC trusted Main cloned the five final isolated B2 Coder differences
on top of the frozen blocked candidate into ignored `b2_successor`. The exact
2138-path final Coder hash map, HEAD, QA history and local toolchain matched;
no input media was copied. The blocked result remains unaccepted. Fresh formal
run `20260913T225754Z-b71bf00a` was initialized before freezing its current
requirement, recovery guidance, STATUS, ExecPlan and successor baseline. A
preliminary `B2_SUCCESSOR_BASELINE` passed: all 2133 accepted-B1 hashes and
2138 blocked final-Coder hashes matched; exactly the Main-owned requirement,
recovery, STATUS, ExecPlan and new manifest differed, while root QA and
toolchain remained ready. The final `B2_SUCCESSOR_BASELINE` receipt passed and
Loop Doctor returned READY. Fresh Planner, sole Coder, Reviewer, Tester, fixed
Runner and Gateway outcomes are pending.

An independent read-only count check after formal start found a derived
receipt-field error: `identical_inherited_blocked_paths` says 2132 because the
new manifest path was subtracted as if inherited; the exact 2138-path map has
2133 identical inherited paths. The full per-path hashes, candidate
fingerprint, HEAD, QA identities and toolchain still match. The bound outer
correction is retained at ignored
`.loop/development/sd4-durable-completion-20260913/b2-successor-baseline-derived-count-correction.json`.
The frozen formal candidate is not mutated; report this count honestly at
acceptance or correct it in a fresh successor if a gate requires the derived
field to be exact.

At 23:05 UTC the successor's fresh read-only Planner `001` returned READY.
It verified both full hash manifests, preserved 1004-entry QA history and
named Main differences, while making no test/media claims. Its Coder scope is
the two mixed-master deferral regressions, combined prior-version/lost-response
recovery, nondefault delivery retry limits and retained SQLite/package checks.
It identified the derived count boundary as a documentation issue rather than
weakening the exact per-path proof. A new isolated Coder session and all later
formal gates remain pending.

At 23:11 UTC fresh sole isolated B2 successor Coder
`01a09d04-67c2-7c10-9147-de9d4124a25b` reported IMPLEMENTED. It changed
only completion repository, delivery snapshot and focused B2 integration tests.
Its local diagnostics reported 57 B2 and 166 compatibility cases passing,
plus targeted lint/type checks. The first pytest collection attempt lacked
`PYTHONPATH=src` and is retained; corrected runs passed. Independent read-only
inspection of the Coder's retained root subsequently passed 22 disposable
SQLite integrity/FK/current-head checks and five bound successful packages,
including Asset hashes, ZIP CRC/entries, nonempty manifests, MP4/SRT hashes
and actual ffprobe video streams. This is not fixed Runner evidence. Fresh
Reviewer is active; Tester, Runner and Gateway are pending.

Fresh Reviewer `001` returned PASS with no actionable findings after inspecting
22 retained SQLite files, 54 committed Asset files and five fully decoded
synthetic packages. Fresh Tester `001` returned READY and requested only the
checked-in `lint` and `test` IDs. The fixed deny-default Runner has started;
no Runner or Gateway outcome is yet accepted. The separate Main inspection
receipt binds the three changed Coder paths and the 22 SQLite/five package
checks to this isolated Coder source, but does not replace Runner evidence.
Fixed Runner lint `20260913T231507Z-a1b2` PASS in 25.193 seconds; its full
fixed test is active. The strengthened independent retained-data receipt also
correlates every saved bound intent to its action key, completed idempotency
record and exact Delivery ID/version, without altering the frozen candidate.
The full fixed Runner test `20260913T231533Z-cc53` then PASS in 834.025
seconds: 2269 Python tests, 58 Web tests and two browser flows, including the
real local API/Worker/FFmpeg case. Lint and test used the same source
fingerprint `747b7dded484fa640a0fcfa6943bb68c35557e3e6eed0344fbd2612fc4993541`
and sealed toolchain fingerprint
`608316b33f894762f45e0ad27471e596627f3295d4877a99407dd8e64e240e03`,
unchanged after execution. Candidate root QA has 1006 unique request IDs and
matching report sections, including both current Runner IDs. Fresh Gateway is
pending; do not publish or call B2 accepted before its deterministic decision.

At 23:33 UTC Gateway `001` PASS with no blockers and formal B2 successor
`20260913T225754Z-b71bf00a` reached DONE. Independent deterministic Gateway
evaluation with retained-file checks PASS matched all 2139 candidate and
assurance source paths, both fixed Runner receipts, HEAD and sealed toolchain.
The trusted process published the three Coder-changed paths into the isolated
`b2_successor` candidate only. Main appended its two accepted QA requests and
reports to the original append-only history, then copied 132 synthetic retained
diagnostic files into the candidate's ignored `.loop/diagnostics` with matching
hashes and no source change. The exact B2 behavior, bounded acceptance and
derived baseline-count discrepancy are documented in
[B2 bounded acceptance](../verification/stable-delivery-sd4b2-accepted-2026-09-13.md).
Original product remains accepted SD-3. Next use this exact DONE source to
prepare C1's full accepted-source manifest and fresh formal run, wire completion
into bootstrap/persistent Worker and test four-category fairness/restart.

At 23:36 UTC the trusted clone copied all 2139 accepted B2 source paths
byte-for-byte into ignored `c1`, with the same HEAD, ready local toolchain,
preserved QA history, one new Main-owned C1 Worker requirement and no input
media. Fresh formal C1 run `20260913T233546Z-9bcf4349` was initialized
before freezing candidate STATUS/ExecPlan and its full accepted-B2 baseline.
The clone is not C1 acceptance; all C1 implementation and fresh gates remain.
`C1_BASELINE` PASS verified the full 2139-path accepted-B2 map,
same HEAD and ready toolchain, 1006 retained root QA identities and only the
named Main-owned C1 requirement, B2 report, STATUS, ExecPlan and new baseline
artifacts; no inherited path was deleted. Loop Doctor READY. The final
receipt binds the current run and documents before formal C1 roles; no
Worker outcome is claimed yet.
At 23:39 UTC, still before formal roles, Main identified the missing runtime
bootstrap connection as an integration prerequisite. The isolated candidate
bootstrap now constructs a CompletionRunner over the shared SQLite task queue
and a CompletionRepository bound to its resolved `data_dir` and configured
delivery retry limit. Targeted completion tests are running. The earlier
pre-edit receipt must be replaced by a full baseline naming `src/liveclip/bootstrap.py`
before `loop-run`; only the Coder may then write C1 Worker implementation.
The replacement baseline PASS binds pre-edit source fingerprint
`0e89735e2fffa3d0cc1fedd5c41e1ec8d239cc515261aa7f0e0429501bfa7276`
and receipt hash
`0056e30d0b68cdd1ccda6ab7e7095323f2d7f1a12100182723008f1a5491b47a`.
Main's prerequisite passed 164 focused completion tests in 231.19 seconds;
a disposable SQLite runtime also verified the shared queue, resolved data directory
and configured retry bound 2. Loop Doctor READY, formal Planner READY and first
isolated Coder cycle started; independent review, fixed Runner and Gateway remain.
The first C1 Coder completed under recorded session
`01a09d28-16a5-7c52-9a30-d5e10bdeb173`. It retained 237-pass local completion
diagnostics and an indexed SQLite/Asset report. Main's read-only outer audit
of the final Coder workspace verified 224 focused disposable databases,
including one expected rejected-upgrade predecessor, and seven bound synthetic
ZIP/manifest/MP4/SRT packages with SQLite identity, checksums and ffprobe;
receipt `.loop/development/sd4-durable-completion-20260913/c1-coder-retained-outer-receipt.json`
SHA-256 `1db4e729c7a22d9d67ed775fb5ed39017478d2f690a7e17dede6ee28da2d8aa7`.
Fresh Reviewer `001` reported P2 lease-monitor shutdown with a blocked SQLite
heartbeat and P2 missing Main recovery/architecture handoff. Neither is waived.
Tester, fixed Runner and Gateway have not established C1 acceptance. Main will
preserve this run and complete the two fixes with new correlated gates.
Tester `001` subsequently marked formal C1 run `20260913T233546Z-9bcf4349`
terminal BLOCKED before any fixed Runner request. The exact isolated final
Coder source has 2146 paths and fingerprint
`6a672abb6b0ac09b6e67224f54c7004927ca2fe4eb98a62edae94bf7192f09b1`.
Trusted Main copied it to ignored `c1_successor`, preserving the prior run and
recording a PASS clone receipt. Main-owned SOLUTION, ADR 045, operator recovery,
STATUS and ExecPlan now describe rotation, bounded `--once`, manual WAITING,
timed deferral, joined monitor shutdown, interrupted lease recovery, immutable
Delivery replay and acceptance limits. The bounded successor requirement is
`docs/requirements/stable-delivery-sd4-worker-shutdown-successor.md`.
New formal run `20260914T000226Z-edd128f3` is initialized before its baseline
freeze. The successor must bind every blocked-Coder path and the accepted B2
ancestor, then let only its isolated Coder fix monitor shutdown and the actual
SQLite lock regression. Its roles, Runner and Gateway remain pending.
`C1_SUCCESSOR_BASELINE` PASS bound all 2146 terminal blocked-Coder source
paths, the complete 2139-path accepted B2 ancestor, the exact blocked Coder
session/fingerprint, eight named Main-only documents/receipts, unchanged HEAD,
ready local toolchain and no copied input media. Its 1006 QA requests and
reports match the trusted root by ID/content despite a historical ordering
difference; the candidate exactly preserves the blocked C1 QA files. Loop
Doctor READY. No new successor role or Runner evidence has been claimed.
The final frozen C1 successor source fingerprint is
`514f81ad21894734ee8177763fb0d6da17c55c64d25cdbd66bc92135e5b3205e`;
its baseline receipt SHA-256 is
`c0c08629d93bde17d66f8afdc79271db6d1d07af446d3c8e75843ef06ed294dd`.
An independent read-only check matched the full blocked Coder hash manifest,
receipt, HEAD and excluded source media. Loop Doctor READY, then the fresh
`loop-run` started. Future role/Runner/Gateway outcomes are still pending.
Successor Planner `001` returned READY. The sole new isolated Coder
`01a09d3e-5694-7352-948d-c9985cc39396` changed only
`src/liveclip/application/lease_monitor.py`,
`tests/unit/test_lease_monitor.py` and
`tests/integration/test_completion_worker.py`; 12 focused local tests passed.
Main's independent complete source-map comparison found 2149 paths with only
those three differences and fingerprint
`b98b25dbb6485300c2fb70c39183a82b845bb9b60a853fb345f340b0079196fb`.
The prior blocked C1 retained SQLite/media audit remains historical evidence.
Fresh independent review and fixed Runner/Gateway are required before C1
successor acceptance.
Second C1 successor `20260914T000226Z-edd128f3` ended terminal BLOCKED at
Tester before fixed Runner. Reviewer accepted the joined monitor implementation
and Main recovery/architecture documents, but its P2 inspection-background
test and interrupted-attempt/Delivery/Asset identity proof remained open. The
standalone lock test only blocked a foreground refresh; the separate shutdown
test used no writer contention. Trusted Main preserved all artifacts and cloned
the exact 2149-path final Coder source, fingerprint
`b98b25dbb6485300c2fb70c39183a82b845bb9b60a853fb345f340b0079196fb`,
into ignored `c1_successor2` with a PASS source-clone receipt. The bounded
`docs/requirements/stable-delivery-sd4-worker-inspection-successor2.md`
requires one actual Worker inspection-monitor background-heartbeat contention,
shutdown, resource-order and immutable recovery test. No prior P2 is waived.
Third C1 formal run `20260914T001553Z-44675925` was initialized before
freezing `c1_successor2` STATUS/ExecPlan and full blocked-source baseline.
It starts from the exact second blocked final Coder bytes, not from a previous
candidate's unaccepted published source. Fresh Coder and gates remain pending.
`C1_SUCCESSOR2_BASELINE` PASS bound the accepted B2 2139 paths, the first
blocked C1 2146 paths and second blocked C1 2149 paths, exact Coder session,
five named Main-only differences, 1006 per-ID QA records, matching HEAD and
ready toolchain. No source media was copied. Loop Doctor READY; all fresh
third-run role, fixed Runner and Gateway results are still pending. The final
frozen C1 successor 2 source fingerprint is
`03214245bc6230a70ee41bb3db30900b40318bdaad731441c5dc971794dbbbe0`
with baseline receipt SHA-256
`c9aaed02d1e2d6af846de40fb8394f9ed8b0b5a2afd506d33b5f0e43e7d355de`.
The formal loop has started from that frozen candidate.
The sole third-run Coder session
`01a09d49-d7ec-7d82-89e3-4544f30aae4e` changed only
`tests/integration/test_completion_worker.py`; local Worker/monitor focus
reported 22 PASS, final combined case PASS, and a two-second join negative
control failed at its live-background-thread assertion as intended. Its
retained trace records 2.202 seconds of locked stop contention below the
five-second SQLite busy timeout, successful renewal, ordered shutdown,
Worker exit 143, immutable Delivery/Asset identities and ordinary recovery.
An independent read-only 2152-path baseline-vs-Coder comparison found only
the authorized test difference. These local results require fresh independent
Reviewer/Tester, fixed Runner, Gateway and final artifact/source audit.
The fresh Reviewer returned PASS with no findings, explicitly closing both
prior P2s and checking retained SQLite integrity, immutable Delivery/Asset
hashes, one lease-expiry retry, valid ZIP and decodable MP4. Tester and
deterministic gates remain pending.
Trusted Main also ran a read-only retained-Coder audit outside the candidate:
`C1_SUCCESSOR2_CODER_RETAINED_OUTER` PASS bound all 2152 source paths, the
sole authorized test change, event ordering and 2.202-second contention,
SQLite integrity, historical/recovery attempts, one immutable Delivery,
owned Asset hashes, ZIP/manifest and playable MP4. Tester returned READY;
the fixed Runner lint request passed with sealed source fingerprint
`37a11972ef240e4b0c36a06e74301fd455b71218fe068a888cccdaf6b3e6f9dd`.
The full Runner test request passed in 892.165 seconds on the same sealed
source, with 2294 Python tests, 58 Web tests, one mocked-browser E2E and one
real API/Worker/FFmpeg browser E2E. Both command receipts have matching
pre/post HEAD, source and toolchain fingerprints. Gateway and final trusted
source/artifact checks remain pending.
Formal C1 successor 2 `20260914T001553Z-44675925` reached DONE after fresh
Gateway PASS with no blockers. The independent deterministic Gateway/source
recheck `INDEPENDENT_DONE_SOURCE` passed against all 2152 sealed source paths,
fingerprint `37a11972ef240e4b0c36a06e74301fd455b71218fe068a888cccdaf6b3e6f9dd`.
Trusted QA append carried lint `20260914T003238Z-8219` and test
`20260914T003304Z-c21d` into original history with unchanged 1006 old IDs.
The exact accepted C1 candidate was cloned into isolated `c2` with a PASS
2152-path source-copy check, matching HEAD and ready toolchain, no media, and
only the new Main-owned C2 public API requirement added. C2 owner-file edits,
fresh roles/Runner/Gateway and original CAS publication remain pending.
C2 began from the accepted C1 source in a new isolated workspace.
`C2_BASELINE` PASS created a complete 2152-path accepted-C1 hash manifest
and checked exact DONE/session, five named Main document deltas, 1008 QA
request/report IDs, HEAD, toolchain and absence of copied media. Before the
sole API Coder starts, trusted Main owns the frozen new/existing-run request
DTOs, goal response and version command, Runtime CompletionService, and a
transactional fresh-create guard. That guard keeps request spelling for
idempotency, checks same-key replay/current authority inside BEGIN IMMEDIATE,
and only then validates a genuinely new source and the already assessed
provider capability before insertion. Targeted 103 service/SQLite cases and
local `make lint` PASS; a temporary pytest basetemp setup error was corrected
before this green run. These are preformal checks only. Seal the final owner
files and C2 requirement, run fresh Planner/Coder/Reviewer/Tester, fixed
Runner/Gateway, real API/Worker/SQLite/FFmpeg/browser inspection, then trusted
original CAS publication. C2 and complete SD-4 are not accepted yet.
Fresh C2 formal run `20260914T010215Z-97882c96` was initialized before
the final Main owner-file/source freeze. The Coder's bounded ownership is
API route/exception wiring and focused API/browser tests. Main retains
bootstrap, schemas, Completion DTO/service/repository guard, shared tests,
SOLUTION/ADR/recovery, ExecPlan/STATUS, receipts and integration. The final
pre-edit receipt must name every Main difference from accepted C1, preserve
all 1008 QA identities, match HEAD/toolchain and exclude source media before
Planner/Coder begins. Formal C2 roles, fixed Runner, Gateway and original
publication remain pending.
The final `C2_OWNER_FREEZE` PASS receipt binds all 2157 pre-edit source paths,
the 2152-path accepted-C1 manifest, 16 named Main deltas, 1008 historical QA
request/report IDs, matching HEAD/toolchain and no copied media. Final frozen
candidate fingerprint is
`0ef79ee2e11533396b6eeac13bd69040579f61a84c3b9f192243cfb68299a500`;
receipt SHA-256 is
`4c88070a1c9f2969d07a133c6d638b0be492839920600313de232ba79202d341`.
Loop Doctor READY; formal run `20260914T010215Z-97882c96` has started
from the sealed source. Fresh role, fixed Runner, Gateway and full SD-4
publication outcomes remain pending.
After formal C2 start, a trusted Main read-only FastAPI TestClient probe found
that explicit JSON strings for the protected CompletionOptions enum fields
and a JSON list for CompletionSelectionSubmission.selected return 422 under
Python-mode strict validation. This blocks the required explicit-options and
manual-selection wire flows until corrected. The candidate/source seal remains
untouched; allow the current isolated cycle to produce its evidence, then
resolve any protected DTO correction in a freshly correlated successor rather
than mutating a running Coder workspace or waiving a known acceptance gap.
First C2 formal run `20260914T010215Z-97882c96` ended terminal BLOCKED at
sole Coder session `01a09d75-2fed-7151-9327-fb70859010fa`. Planner READY;
the Coder altered only `src/liveclip/api/app.py` and two focused completion
API/recovery tests. Local 27 API/recovery and 186 regression cases passed,
and its synthetic Worker produced inspected MP4/SRT/ZIP/Asset hashes; none
is fixed Runner assurance. The historical real-browser verifier accepts
exactly nine tasks and one Delivery and cannot certify the new completion
scenario. No Reviewer, Tester, Runner or Gateway ran; QA remains 1008 IDs.
Trusted Main preserved the run and cloned the exact 2159-path terminal Coder
source into ignored `c2_successor` with PASS per-path hashes, unchanged HEAD,
ready toolchain and no media copy. Final copied fingerprint:
`3b35c72d556ecb359119bc0f2e1b6d0a16c5564aa2242d3548efad46d939f149`.
The successor will introduce a distinct, strict browser verification mode,
retain the legacy assertions, add a real signed-download browser case through
the checked-in `make test` path, and require fresh role/Runner/Gateway evidence.
`C2_SUCCESSOR_BASELINE` PASS bound all 2159 terminal Coder source paths,
eight named Main fixture/command/test/document differences, 1008 per-ID QA
requests/reports, matching HEAD/toolchain and no copied source media. The
protected completion verifier passed a read-only replay against retained
synthetic SQLite/Assets: six stages, eight tasks, deferred completion
attempt, one bound Delivery, 13 Asset hashes, decoded MP4/SRT and ZIP
manifest. Local 39 focused tests and `make lint` passed; these are preformal
diagnostics, not fixed Runner assurance. Fresh formal successor
`20260914T013347Z-dfaec00b` initialized before `C2_SUCCESSOR_OWNER_FREEZE`
PASS sealed all 2163 source paths and 10 named Main differences. Frozen
fingerprint `b06cb67511d382eccb38ca42548bd0bb60d42906c1234cf6eeb092d257fe9515`;
receipt SHA-256 `06c3bc8769c98bf5c25ecc5862e78f0b0ab1faab81839dd5646d66606f5fa313`.
Loop Doctor READY; formal roles are running, with no fixed Runner/Gateway
result or original SD-4 publication yet.
Fresh successor Planner READY and the sole isolated Coder session
`01a09d90-d19c-7e22-9ac2-bf3c3a20be88` returned IMPLEMENTED. A read-only
hash comparison of frozen candidate to final Coder source found exactly two
actual differences: new real Playwright completion spec and strengthened
completion recovery integration test. The inherited API route/strict JSON
code remained unchanged. Coder local 27 focused tests and a corrected
missing-Asset negative regression passed, as did TypeScript and Ruff; these
are diagnostics, not fixed Runner assurance. Fresh Reviewer/Tester,
deterministic lint/test, Gateway and independent artifacts remain pending.
The first C2 successor run `20260914T013347Z-dfaec00b` ended terminal
BLOCKED after Reviewer FAIL and Tester BLOCKED on three P2 evidence gaps:
no confirmed processing while the browser observer was disconnected, no
page-download digest correlated with the bound ZIP Asset, and a project-root
symlink escape in recovery inspection. No fixed Runner/Gateway ran or QA was
appended. The exact 2164-path final isolated Coder source was cloned into
ignored `c2_successor2`, fingerprint
`0af49373e28a8c2f612bbe8196df2b99339bce0b2e798c0cc09bbde5378e66c1`,
with PASS source/HEAD/toolchain/no-media checks. Trusted Main extended only
the protected browser fixture and shell command to observe persisted
waiting/deferred lease state after a browser-close marker, and to require a
safe page-download SHA-256/size receipt equal to the bound ZIP Asset. Local
unit and retained-artifact negative controls passed; no formal successor-2
role has started. The new sole Coder is restricted to the browser spec and
recovery inspection test, with all three prior P2s carried forward.
`C2_SUCCESSOR2_BASELINE` PASS bound all 2164 exact terminal Coder paths,
six named Main fixture/command/test/document changes, 1008 QA identities,
same HEAD/toolchain and no copied input media. Formal successor-2
`20260914T015534Z-11dec4c4` initialized before
`C2_SUCCESSOR2_OWNER_FREEZE` PASS sealed all 2168 pre-edit source paths,
eight named Main differences and the protected marker/download verifier.
Frozen fingerprint `a3f98476afaf7232350e6df11669f01360dbffd639a385e7dbc3ce6b0bd74fe3`;
receipt SHA-256 `451917fe8867bb5a3c13d7aaeab081fb22a07cb0088a58bd20966dbae10b2a35`.
Loop Doctor READY. Fresh Planner READY and sole Coder session
`01a09da3-5bc9-7041-9822-dbbe3ab08ff7` IMPLEMENTED only the authorized
browser spec and recovery test; independent exact 2168-path comparison found
only those two changes, final fingerprint
`fa93ecf59248b6b082f3ef346ba3aa065a014253caaf74c0596f2717f411fc3c`.
Fresh Reviewer PASS/no findings explicitly closed the inherited offline
processing, page-byte ZIP digest and project-symlink P2s. Tester READY; fixed
Runner lint `20260914T020528Z-c72d` PASS 25.604s on the sealed source.
Fixed Runner test `20260914T020553Z-7dab` FAIL in 943.041s:
2325 Python passed and one failed before Web/browser. In
`test_concurrent_creation_commits_one_identity`, the shared fixture's two
threads can each write then unlink `synthetic.mp4`; the losing unlink raised
`FileNotFoundError`. This is test setup racing before the one-identity assertion,
not proof of a product identity failure. The fixture file is outside this
Coder's two-file scope, so formal code cycle 2 must not silently edit it.
Preserve the FAIL and repair in a new isolated successor if the current run
ends blocked. No Gateway, accepted QA append, retained browser/media audit or
original SD-4 publication yet.

The second C2 successor ended terminal BLOCKED at code cycle 2. The sole
recorded Coder refused a protected test edit, returned `changed_files=[]`,
and did not resume outside the trusted loop. The blocked run retains lint
PASS/test FAIL identities `20260914T020528Z-c72d` and
`20260914T020553Z-7dab`; no Gateway or original QA acceptance. Main's
trusted clone into ignored `c2_successor3` matched all 2168 sealed assurance
paths, fingerprint `fa93ecf59248b6b082f3ef346ba3aa065a014253caaf74c0596f2717f411fc3c`,
and retained the original 1008 accepted QA IDs without copying input media.
In that new candidate only, Main made the concurrent-create fixture source
exist before the two threads start and asserted its bytes remain after both
finish. The formerly failing focused test passed ten separate runs. This
is a diagnostic fix; new Reviewer/Tester/Runner/Gateway and browser/media
evidence are still required before publication.
`C2_SUCCESSOR3_BASELINE` PASS bound 2168 exact failed assurance paths,
four named Main differences, 1008 accepted QA IDs, same HEAD/toolchain and
no input media. Receipt SHA-256
`bb862f66cf98068d75104a7ceb1dca83551d451126713d0c41ef345fa7d5b41b`.
The full identity test file passed 96 cases in 18.55s, candidate `make lint`
passed, and Loop Doctor READY. Formal successor-3
`20260914T022845Z-5f824a44` initialized before owner freeze.
`C2_SUCCESSOR3_OWNER_FREEZE` PASS sealed 2172 paths and six named Main
differences. Frozen fingerprint
`8955af213f6b38f838497d84b2095d9bb240566493c6cd1f4ea6974093b017a7`;
receipt SHA-256
`a4305df8e18b216872424b9fd532879bc8b2fa0740ba0ba49effd674a0b4b31f`.
Successor-3 ended terminal BLOCKED at Reviewer FAIL/Tester BLOCKED with two
P2s and no Runner/Gateway/QA: toolchain baseline/freeze provenance was not
reconciled inside the candidate, and fixture cleanup removed all but the
ZIP summary needed for independent current Asset/durable-state inspection.
Sole Coder changed no file. Trusted Main cloned the exact 2172-path frozen
source into ignored `c2_successor4`, preserving 1008 accepted QA IDs and
excluding input media. The new protected reconciliation receipt proves the
17 YAML `.pyc` cache files generated between baseline and freeze account
exactly for the earlier fingerprint difference; it independently rehashes
the trusted snapshot and confirms unchanged dependency locks without
rewriting either historical receipt.

Main added bounded, no-follow, hash-verified retention of all committed
synthetic Assets plus strict raw close/wait/download markers and curated
transaction-consistent project/run/intent/stage/task/attempt/Delivery/Asset
rows. The create-once v2 manifest is published last; raw lease tokens,
credentials and signed URLs are excluded. Local 14 fixture tests, the
concurrent-identity case and `make lint` passed. A first real-browser
diagnostic failed 401 at page ZIP fetch under login-required auth; the
existing API calls used Bearer but this fetch omitted it. A separate ignored
diagnostic clone with Bearer in the request header passed actual
Chrome/API/Worker/SQLite/FFmpeg, retaining 16 Assets, 8 Tasks, 11 attempts
and 21 files. Independent local inspection rehashed every file, matched the
page ZIP/Asset, checked markers/SQLite integrity, fully decoded ZIP MP4 and
found no credential or signed URL in retained text. This is preformal
diagnostic evidence only. The next sole Coder may change only the browser
spec's authorized page fetch; fresh full gates remain required.
`C2_SUCCESSOR4_BASELINE` PASS bound 2172 exact terminal source paths and
six named Main differences, including only the protected retention fixture,
test and toolchain provenance receipt among code/evidence files. It retained
1008 accepted QA IDs, same HEAD/toolchain and no input media; receipt SHA-256
`e8bc278ab8bebf15e7b7b55750de7c7b8a3fbf53feaf098a6322ce9405e3f975`.
Prewarmed Loop Doctor READY; baseline toolchain fingerprint
`ff91cf3a2b55e8bab2fb47bd72506cc687ee9ccd91173d7b39833a50f9b5f815`
remained unchanged after formal initialization. Fresh run
`20260914T024940Z-00478c9b` was initialized before owner freeze.
`C2_SUCCESSOR4_OWNER_FREEZE` PASS sealed 2177 paths and 1008 accepted QA
IDs; frozen fingerprint
`f49380be7074977bc85cf07297d5837c8dbb6ba4d094a1a02cb13262025d0cee`;
receipt SHA-256
`6e8e1f2b9ff4ae3d8205ea95304c8eb94184ef3c23986bdea800ab1b33763a17`.
Baseline/freeze toolchain fingerprints match. Loop Doctor remained READY;
fresh formal gates now run from the sealed candidate.
Fourth successor `20260914T024940Z-00478c9b` ended terminal BLOCKED at
Reviewer FAIL/Tester BLOCKED with no Runner/Gateway/accepted QA. Planner
READY and sole Coder `01a09dd7-08f7-7f20-bdfb-c8ca3a97cabd` IMPLEMENTED
only the authorized browser-spec Bearer fetch. Reviewer verified the
toolchain reconciliation but found a new P2: retained stage rows lacked
IDs/run bindings, Asset rows lacked producer-attempt/clip bindings, and
delivery clip rows lacked Delivery identity. Once SQLite is cleaned, the
bundle cannot prove Asset producer → attempt → Task → Stage lineage. Main
must preserve exact terminal assurance source in a fresh candidate, expand
protected transaction snapshot and independent post-cleanup lineage tests,
then run all formal gates anew. Prior run, failure and budgets remain intact.
Main cloned exact fourth assurance source to ignored `c2_successor5`, 2177
paths at `dc9a0ebe2c8707faa5b803fb3b0fae50f447a9d6a409bd5581a04eb2f0765a30`,
with same HEAD, sole browser Coder edit and 1008 accepted QA IDs. Protected
fixture now retains Stage IDs/run, Task run/stage/dependency, Asset producer
attempt/clip/generation/revision and Delivery clip identity. Before
retention, the read transaction verifies each Asset's successful producer
attempt and expected stage/Delivery Task. The fixture command removes its
identity-bound temporary root before a separate checked-in verifier
reconstructs the full bundle, validates ZIP/media and deliberately tests
rejection of a ZIP Asset reassigned to another existing successful stage
attempt. A sanitized row fixture captured from the actual local verifier
supports fast wrong-attempt and wrong-run tests. Local `make lint`, 110
targeted Python tests plus 15 focused fixture tests, and two real synthetic
Chrome/API/Worker/SQLite/FFmpeg completion diagnostics passed; the second
observed actual temp-root absence and 16 Assets/21 retained files after
cleanup. These local checks do not substitute for fresh formal Runner,
Reviewer, Tester, Gateway or current post-Runner artifact audit.
`C2_SUCCESSOR5_BASELINE` PASS bound 2177 terminal source paths, eight
named Main differences, 1008 original QA identities, unchanged HEAD and
prewarmed toolchain fingerprint
`b90e45d43f0094e2b0ebfa124934d864f245f329633b8bec1b0b00af7c95ed04`;
receipt SHA-256
`4745da292860f4c04d53a4f9238573298b3af2d3f91bf1fbccd5b3e733725a5d`.
Fresh formal `20260914T030913Z-7a67521a` initialized before final owner
freeze; no role has started yet.
`C2_SUCCESSOR5_OWNER_FREEZE` PASS sealed 2183 paths and the same prewarmed
toolchain fingerprint, with frozen source
`45795e81f82f56761c09643342397c18568ad87c8965b649709f2a3ef0099eda`
and receipt SHA-256
`5b63f039360bf0736cd447ada0caeb7dd9672726b323baa1d774401b7758a157`.
Fresh formal gates now run from this sealed source; no acceptance yet.
Fifth formal `20260914T030913Z-7a67521a` ended terminal BLOCKED before
Runner/Gateway/accepted QA. Planner READY; exact Coder
`01a09de7-c264-7413-8c31-6af7077cb402` IMPLEMENTED with no edits.
Reviewer FAIL reproduced three P2s in protected validation: a broken
Task dependency graph is accepted when every referenced ID exists; Asset
generation/edit-plan revision is not checked; and the v2 verifier does
not compare actual tree entries with the manifest or scan every retained
text file. Tester BLOCKED also noted the wrong-stage regression actually
changes run identity and retained SRT check is only an arrow search. Main
must inherit all 2183 frozen paths exactly in a new successor, enforce
the expected six-stage chain and Asset scopes, exact no-follow inventory,
genuine same-run mutation tests and parseable retained subtitles, then
rerun fresh review, Runner, Gateway and current artifact audit. Prior
terminal failures and budgets are preserved.
Trusted Main cloned all 2183 fifth frozen paths to ignored
`c2_successor6`, same fingerprint
`45795e81f82f56761c09643342397c18568ad87c8965b649709f2a3ef0099eda`,
HEAD and 1008 accepted QA IDs, no input media/control state. Protected
pre-clean and post-clean verifiers now enforce unique ordered Stage/Task
chains, exact expected dependencies, run/selection Asset generation and
revision/epoch scope, no-follow manifest-versus-tree equality, all retained
and ZIP text leakage scanning, parseable Asset and ZIP SRT, and full MP4
decode. Focused tests mutate self/missing/wrong-existing dependencies,
same-run wrong producer Stage, Asset scope, extra file/directory/symlink.
Local 115 targeted Python tests and `make lint` passed. First browser
diagnostic identified a macOS `/var` symlink in the verifier's temporary
SRT path; a project-local controlled temporary directory fixed that.
Final local real synthetic Chrome/API/Worker/SQLite/FFmpeg completion passed
after actual fixture cleanup: 16 Assets, 8 Tasks, 11 attempts, 21 exact
retained files, page ZIP/Asset hash, parseable SRT, full MP4 decode and
wrong-existing-producer rejection. This is preformal only; sixth baseline,
freeze, fresh roles, fixed Runner and independent current artifact audit
remain.
`C2_SUCCESSOR6_BASELINE` PASS bound 2183 exact inherited paths and seven
named Main differences, 1008 accepted QA IDs, unchanged HEAD and prewarmed
toolchain fingerprint
`bea0db671d65f4ca5d896d68b6d4e2c5c9b2829c255f81ca13e97b220eb0387a`;
receipt SHA-256
`4126520d84f00a2fccc01f7388c76fc11530b822f19dcefd799fff58b8a49233`.
Sixth formal `20260914T032814Z-13664636` initialized before final owner
freeze; no role has started.
`C2_SUCCESSOR6_OWNER_FREEZE` PASS sealed 2187 paths, with frozen source
`65169db1f99f8590452d3ea9c5ea58aef35bf79ae45f5d98aba1dd6344be394b`
and receipt SHA-256
`be1b860f5801270ff79dad57cc3302ba9c007159f036e26e1354306f51f624a6`.
Baseline/freeze toolchain fingerprints match; fresh formal gates now run.

Sixth formal 20260914T032814Z-13664636 ended terminal BLOCKED at
Reviewer FAIL/Tester BLOCKED, before Runner/Gateway and without accepted
QA. Planner READY and sole Coder
01a09df9-11df-78a1-a377-e4397d59d980 IMPLEMENTED without editing the
frozen source. Reviewer reproduced two P2 assurance gaps: the
post-cleanup text scanner matched labels but accepted actual synthetic
credential values, raw lease tokens and X-Amz signed URLs; helper-only
negative tests did not exercise complete SQLite-backed or retained
verification. Prior budgets and failure remain. Trusted Main cloned all
2187 frozen source paths byte-for-byte to isolated c2_successor7 at
65169db1f99f8590452d3ea9c5ea58aef35bf79ae45f5d98aba1dd6344be394b,
with the same HEAD, 1008 original QA IDs and no input media/control state.
The seventh protected changes add shared pre-retention/post-cleanup text
rejection based on actual fixture credential values, hash comparison of
token-shaped strings to durable lease hashes and signed URL parameters.
Every permitted ZIP text member is scanned; unsupported types fail.
Disposable integration tests construct SQLite rows, real decodable MP4,
SRT, ZIP and markers, then call both public verifier entry points. They
prove valid controls before mutations and reject changed dependencies,
producers, generation/revision, unlisted files, correctly rehashed token
or credential Assets, malformed SRT and contaminated/unsupported ZIP
members. Local focused Python, Ruff and mypy pass. A fresh real synthetic
Chrome/API/Worker/SQLite/FFmpeg diagnostic passed after actual fixture
deletion with 16 bound Assets, 21 retained files, three completion
deferrals and full decode. Seventh baseline, owner freeze, fresh roles,
fixed Runner, Gateway and current Runner artifact audit remain.
C2_SUCCESSOR7_BASELINE PASS bound 2187 inherited terminal source paths,
eight named protected Main changes, 1008 original QA IDs and the same
HEAD. Prewarmed toolchain fingerprint
61476832bf7dfac43c7b468459e7b5c3ea1b0e6b26f067b3e2ed2c75d231c06a
and receipt SHA-256
a36acbbd38896419c4519ca19ce8e16eac7293d1836c6cddbafc30c127673560
are recorded. Local make lint PASS; formal source freeze and gates remain.
Seventh formal 20260914T034657Z-511d81ef was initialized before
owner freeze. C2_SUCCESSOR7_OWNER_FREEZE PASS sealed 2193 paths at
d6b697bfea4b346501adc997a9ee5fb9d610775676c5a34a7632b3a8b99b30b1,
with toolchain fingerprint unchanged from baseline and receipt SHA-256
a5ecf324a35a7663bb5d5052e950c5d07b312c20b29c9aee70e44ee35a94dc1b.
Loop Doctor READY; fresh roles and fixed Runner now operate only on
this sealed candidate. No seventh acceptance is claimed yet.
Seventh formal 20260914T034657Z-511d81ef ended terminal BLOCKED at
sole Coder 01a09e09-cca7-7f30-85d7-ac239e9eb1b8 after Planner
READY, before Reviewer/Tester/Runner/Gateway and without new QA.
Coder made no edit and found that both pre-retention rejection tests
stopped without restoring and fully revalidating the control sample;
the full integration suite also used only default fixture credential
values. Trusted Main cloned all 2193 frozen paths exactly to isolated
c2_successor8 at
d6b697bfea4b346501adc997a9ee5fb9d610775676c5a34a7632b3a8b99b30b1,
same HEAD, 1008 original QA IDs and no input media/control state.
Protected tests now restore and reverify both pre-retention controls
through the complete SQLite-backed verifier, retain the passing
package, delete the fixture and run the complete post-cleanup
verifier. Non-default configured token/password values are injected
as correctly rehashed text through both complete entry points.
The 23 focused tests pass locally. Runtime code and earlier local
real Chrome evidence are inherited unchanged; fresh eighth formal
gates are still necessary.
C2_SUCCESSOR8_BASELINE PASS bound 2193 seventh frozen paths, four
named Main changes, 1008 accepted QA IDs and unchanged HEAD. The
prewarmed toolchain fingerprint is
5059defcb585f7eb5ca62186372ed5df2188792ab744686b7b9779879b72863b
and baseline receipt SHA-256 is
3d35002b1e74d90d400e4153741c0ac360b532ffbcb1cd770e5e26c7571de4bc.
Local make lint PASS; owner freeze and formal gates remain.
Eighth formal 20260914T035449Z-d5fce2e8 was initialized before
owner freeze. Initialization added exactly 26 Python bytecode cache
files and two cache directories to the isolated toolchain. A
read-only replay of the checked-in fingerprint algorithm excluding
only those additions reproduced the baseline fingerprint
5059defcb585f7eb5ca62186372ed5df2188792ab744686b7b9779879b72863b.
Current prewarmed fingerprint is
d1d9eea92dc5891b6b1b50317d98acd8f6d2c94a0bc564209a6d70c13187cc36;
dependency locks rehash unchanged. Reconciliation PASS receipt
SHA-256 cf68a6e71fec42448896444c0e12aacd15792d4abed75235ccda68f9c2599894
is recorded before freeze. No role has started.
C2_SUCCESSOR8_OWNER_FREEZE PASS sealed 2198 paths at
58594d42f4767522b68faa7766f1f492a22887b93a160808bc6e6eb3188f69be
and the reconciled toolchain fingerprint
d1d9eea92dc5891b6b1b50317d98acd8f6d2c94a0bc564209a6d70c13187cc36,
with receipt SHA-256
57384e105dabd29b1076e1ef46e0c42495e1b51bc0176a106af53ab23be6ecfe.
Loop Doctor READY; fresh formal roles now run only on the sealed
candidate. No eighth acceptance is claimed yet.
Eighth formal 20260914T035449Z-d5fce2e8 ended terminal BLOCKED
at Reviewer FAIL/Tester BLOCKED before Runner/Gateway; Planner
READY, sole Coder 01a09e12-defe-7003-b191-eae99344052e IMPLEMENTED
without edits, and accepted QA remains 1008. Reviewer identified
two protected gaps: post-cleanup ZIP verification did not parse and
bind its internal manifest or require exact five-member inventory;
the integration tests injected non-default credentials into retained
Asset text, but not permitted ZIP text. Trusted Main cloned the exact
2198-path frozen source into c2_successor9 at
58594d42f4767522b68faa7766f1f492a22887b93a160808bc6e6eb3188f69be,
same HEAD and original QA, no input media/control state. The protected
verifier now binds internal Project, Delivery/version, selected
clip/revision, media filenames and video SHA, and requires exactly
manifest, HTML viewer, checksums, one MP4 and one SRT. Complete
post-cleanup mutations remove required members, add benign supported
text, alter manifest identities, and inject non-default token/password
and signed URL into existing ZIP text. All outer ZIP/Asset/download
hashes and retained manifest bindings are recomputed before rejection;
each exact restoration passes. Pre-retention complete verifier also
rejects configured token/password/signed URL in ZIP text, restores
bytes/SQLite/marker and passes through cleanup. Local 23 focused
tests, make lint and a fresh real synthetic Chrome/API/Worker/SQLite/
FFmpeg completion passed after actual fixture deletion, with 16
Assets, 21 files and full media decode. Fresh ninth formal gates and
current Runner artifact audit remain.
C2_SUCCESSOR9_BASELINE PASS bound 2198 exact eighth frozen paths,
five named protected Main changes, 1008 accepted QA IDs and unchanged
HEAD. Prewarmed toolchain fingerprint
e4c9d1de4e698732af8b71a6f606b374477eaa725d78ddf16702ef1836f013a0;
baseline receipt SHA-256
1931aadaeedc87a3b60e0d98a0acbc49de6ab4f2e75fc310b11d9789427513cc.
Owner freeze and fresh formal gates remain.
C2_SUCCESSOR9_OWNER_FREEZE PASS sealed 2202 paths at
66bae814c0e9ba890707f5382e40116567d24800ef9fd62b1598ecc7286bd406,
with baseline-matching toolchain fingerprint
e4c9d1de4e698732af8b71a6f606b374477eaa725d78ddf16702ef1836f013a0
and receipt SHA-256
3df191cbeba4c8d50ec61f61ebd9463113dda01d4a264914cdcddd4d313a3b3e.
Loop Doctor READY. Ninth formal 20260914T041011Z-f9c28238 now
runs fresh roles on this sealed source; no acceptance is claimed.
Ninth formal 20260914T041011Z-f9c28238 ended terminal BLOCKED
after two fresh Planner NEEDS_INPUT results exhausted its plan
repair budget. No Coder, Reviewer, Tester, Runner or Gateway ran;
accepted QA stays 1008. Both Planners found that the protected
complete-verifier test removed HTML and internal manifest but not
MP4, SRT or checksums.sha256. The ZIP helper would silently
regenerate checksums.sha256, so simply deleting it from the input
mapping would not test absence. This corrects the earlier local
diagnostic narrative; all failed evidence and the ninth seal remain.
Trusted Main cloned the exact 2202-path terminal ninth source into
isolated c2_successor10 at fingerprint
66bae814c0e9ba890707f5382e40116567d24800ef9fd62b1598ecc7286bd406,
same HEAD and 1008 QA IDs, without input media or previous control
state. Main changed only the protected test construction to permit
a genuinely absent checksum member and added separate MP4, SRT
and checksum omission variants. Every variant rebinds ZIP, Asset,
durable, download and retained manifest bytes and restores a
passing control. Four focused complete-verifier integration tests
and make lint passed locally. Fresh browser and formal gates remain.
Fresh local real synthetic Chrome/API/Worker/SQLite/FFmpeg completion
also PASS: observer closure preceded 3 durable deferrals, manual
completion fetched one v001 ZIP matching its committed Delivery
Asset; after exact fixture cleanup the retained verifier checked 16
Assets, 21 files, 11 attempts and full MP4 decode. This is a local
diagnostic, not formal Runner/Gateway or real-content acceptance.
C2_SUCCESSOR10_BASELINE PASS bound all 2202 ninth terminal source
paths, four named Main changes, unchanged HEAD and 1008 accepted
QA IDs; toolchain fingerprint
8837cd7549c93f9c0455d702af9ab38340ae2dea4daff9b97c6595834d3efab2;
baseline receipt SHA-256
162fdbe3babc013a50f8e72a746d36e37204822d99afd9869d4a80a8a1331394.
C2_SUCCESSOR10_OWNER_FREEZE PASS sealed 2206 paths at
784e4232a8914a3c13f8a5f0989301bb6dc2ceec978c5930afab91ed483b4aa3,
same toolchain fingerprint, freeze receipt SHA-256
295aadb59c350c777e7ab893068733f0136a0a5229d7c00842db06da105a27d3.
Loop Doctor READY; tenth formal 20260914T042335Z-281a2d3f now
runs fresh roles from this seal. No tenth acceptance is claimed.
Tenth formal 20260914T042335Z-281a2d3f ended terminal BLOCKED:
Planner READY, sole Coder 01a09e2a-6e44-7a92-b991-3020ee94a23a
IMPLEMENTED with no edits, Reviewer FAIL on one P2, Tester BLOCKED,
no Runner/Gateway and no accepted QA. Reviewer demonstrated that a
different valid MP4, with ZIP manifest hash, member checksums, ZIP
Asset, download marker and retained evidence consistently rebound,
could pass post-cleanup verification despite differing from the
selected committed review_proxy master. This violates exact master
reuse. Trusted Main cloned the exact 2206-path frozen tenth source
to c2_successor11 at
784e4232a8914a3c13f8a5f0989301bb6dc2ceec978c5930afab91ed483b4aa3,
same HEAD and 1008 original QA IDs, no input media/control state.
Both complete verifiers now bind the ZIP video bytes and hash to the
unique selected committed master Asset. Their integration tests
replace the MP4 with another FFmpeg-generated, fully decodable video,
recompute all inner and outer hashes, require the intended master
byte-mismatch rejection before any pre-retention manifest, then
restore and pass the controls. Four focused integration tests and
make lint passed locally. Fresh browser and formal gates remain.
Fresh local real synthetic Chrome/API/Worker/SQLite/FFmpeg also PASS:
the page ZIP matched the committed Delivery Asset; after actual
fixture cleanup the retained verifier accepted 16 Assets, 21 files,
11 attempts including 3 deferrals and full MP4 decode. Baseline,
freeze and formal gates remain; this is diagnostic evidence only.
C2_SUCCESSOR11_BASELINE PASS bound all 2206 tenth terminal paths,
six named Main changes, unchanged HEAD and 1008 QA IDs; toolchain
fingerprint
98f87ee2a02f526b71bb057dc0c387fc6955515822afada394e89a4a63ab8ddc;
baseline receipt SHA-256
076813003480686b2099aa24df2492b31f9f9eb9ca7020be8af7892315196f7e.
C2_SUCCESSOR11_OWNER_FREEZE PASS sealed 2210 paths at
1e79d4d682a01b0fd6747f7419d177eb201b36fd2eb0396c74fe1efff1d5629b,
same toolchain fingerprint, freeze receipt SHA-256
fd2282e0c980606d38b5185222f8372b79f96208d9bedf035d3a46f79fbada76.
Loop Doctor READY; eleventh formal 20260914T043403Z-a0b9d9b3
now runs fresh roles from the seal. No eleventh acceptance yet.
Eleventh formal 20260914T043403Z-a0b9d9b3 ended terminal BLOCKED
at Planner before any role artifact or Coder/Reviewer/Tester/Runner/
Gateway. Its read-only command printed the entire 2206-path inherited
hash manifest. The trusted control plane rejected the resulting
truncated bounded/redacted log; no QA was accepted. The Agent's
otherwise completed JSON cannot substitute for complete captured
evidence. Trusted Main cloned the exact 2210-path frozen eleventh
source into c2_successor12 at
1e79d4d682a01b0fd6747f7419d177eb201b36fd2eb0396c74fe1efff1d5629b,
same HEAD and original 1008 QA IDs, without input media or prior
control state. The twelfth requirement includes the precise clone
identities and directs Planner to hash/count/select keys instead of
printing large manifests. Product code, role grants, fixed Runner
argv/deny-default sandbox and log truncation policy remain intact.
Fresh formal gates remain.
C2_SUCCESSOR12_BASELINE PASS bound all 2210 eleventh terminal paths,
three named Main document changes, unchanged HEAD and 1008 QA IDs;
toolchain fingerprint
c3e16309d59c54609244328cde05d12d623e15d3c8e42fb34c6f86f247658130;
baseline receipt SHA-256
2c72314da23edd89a0d28d443900f5edd52f68584a659c9802212f42534a4846.
C2_SUCCESSOR12_OWNER_FREEZE PASS sealed 2214 paths at
fc5b3b06f4e8826a65200ad506f2d1869f5b5a63a78a041893f77781c98dd0c8,
same toolchain fingerprint, freeze receipt SHA-256
38984b91b5b2da1b0215c94b76775f2c52ef69e443d28a56cb504bccf97c3ce6.
Loop Doctor READY; twelfth formal 20260914T043821Z-926912c8 now
runs fresh roles from this seal. No twelfth acceptance yet.
Twelfth formal 20260914T043821Z-926912c8 ended terminal BLOCKED:
Planner READY and Coder 01a09e38-2982-7271-a8ff-5ab2847d6ef0
BLOCKED with zero changed files. Planner used bounded hash metadata,
but Coder's first raw `git status --short` exceeded its tool-result
display limit; it refused to claim incomplete verification. No
Reviewer/Tester/Runner/Gateway ran and no QA was accepted. Trusted
Main cloned all 2214 exact frozen source paths into c2_successor13
at fc5b3b06f4e8826a65200ad506f2d1869f5b5a63a78a041893f77781c98dd0c8,
same HEAD and original 1008 QA IDs, with no input media/control
state. The thirteenth requirement now directs every role to use
bounded status samples and hash-manifest metadata. Product code,
role scope, fixed Runner argv/deny-default sandbox and unchanged
truncation gates remain. Fresh formal gates are required.
C2_SUCCESSOR13_BASELINE PASS bound all 2214 twelfth terminal paths,
three named Main document changes, unchanged HEAD and 1008 QA IDs;
toolchain fingerprint
1439d5a1155c9eccd9bd8bfc51ac155c62b2bb805c71fe30f5fff19245e4b003;
baseline receipt SHA-256
88e9c7a1ba4b522e048e13bff7dd9dda2560acb2fea0a316ddbce30a8837c4ee.
C2_SUCCESSOR13_OWNER_FREEZE PASS sealed 2218 paths at
888278832cb30e92af8b9d01f147b8b20b793a9c0f6cc83cd6a1538c2e3f1673,
same toolchain fingerprint, freeze receipt SHA-256
7fd34e4d8a223dd5783169968d16b604259e0a64b0c590a12e7fa4ad60964711.
Loop Doctor READY; thirteenth formal 20260914T044321Z-8842ea5f
now runs fresh roles from this seal. No thirteenth acceptance yet.
Thirteenth formal 20260914T044321Z-8842ea5f ended terminal BLOCKED:
two fresh Planner NEEDS_INPUT results exhausted its plan budget.
Long Product Spec tool output was incomplete; both refused to claim
evidence. No Coder/Reviewer/Tester/Runner/Gateway or accepted QA.
Trusted Main cloned all 2218 exact frozen paths into c2_successor14
at 888278832cb30e92af8b9d01f147b8b20b793a9c0f6cc83cd6a1538c2e3f1673,
same HEAD and 1008 QA IDs, no input media/control state. Main then
performed a separate control-plane prompt maintenance: original
469-path code matched the prior CAS baseline byte-for-byte; exactly
the five Planner/Coder/Reviewer/Tester/Gateway prompts changed to
require size checks, segmented document reads and bounded status/
manifest evidence. The old baseline remains preserved, new CAS
baseline SHA-256 is
1a0488a3d293d3ebac404aa7e91579f49f24a87ddb2cf84d27b6c17830f9ced2,
and maintenance receipt SHA-256 is
b3123c43a3a9943777b3ea0f8f14f8f2f84069968fcef6ffb2e64146419fbbf8.
63 control-plane tests and original make lint PASS. Product code,
Coder grants, Runner allowlist/sandbox and log caps did not change.
Fresh SD-4 formal acceptance and trusted product CAS publication
remain required.
C2_SUCCESSOR14_BASELINE PASS bound all 2218 thirteenth terminal
paths, nine named Main differences including five bounded role
prompts, unchanged HEAD and 1008 QA IDs; toolchain fingerprint
338868fbc23a1ff8b7c897be31ed5007f670833c8683b8f41910eb39b5851aeb;
baseline receipt SHA-256
60ec02574bfa6fae73c150340078c59d0828d9627400c11815a5be115b93e18a.
Candidate control-plane 63 tests and make lint PASS.
C2_SUCCESSOR14_OWNER_FREEZE PASS sealed 2222 paths at
9013badb4dd5e68a976273708c5056b26e8098ee5237879d6e4eae78a8905efd,
same toolchain fingerprint, freeze receipt SHA-256
2f21963a8b9584c1ec96189ce4a04e372c73d7d9cb0be85958ac035c13675651.
Loop Doctor READY; fourteenth formal 20260914T045341Z-6730b93b
now runs fresh roles on this seal. No fourteenth acceptance yet.
Fourteenth formal 20260914T045341Z-6730b93b ended terminal BLOCKED
after fixed Runner test FAIL 20260914T050309Z-767e. Its lint PASS;
Python 2336, Web 58, Mock Chrome and legacy real Chrome passed before
the sequential completion Chrome fixture's port preflight raised
macOS Errno 48. Both real-browser scenarios had reused API 18765 and
Web 15174; the second never launched. The same exact Coder session
resumed, could not see a correlated Runner diagnostic in its isolated
workspace, and correctly made no page edit outside its scope. No
Gateway, accepted QA append or original SD-4 publication occurred.
Trusted Main cloned all 2222 terminal source paths into
c2_successor15 at the same sealed fingerprint and HEAD, restored only
the 1008 accepted original QA records and excluded input/control state.
The candidate-only Main integration repair gives the second browser
scenario distinct ports while retaining the preflight check. New
Planner, Coder, Reviewer, Tester, Runner and Gateway evidence remains
required; no failed result may be treated as accepted.
C2_SUCCESSOR15_BASELINE PASS: 2222 inherited terminal paths, four
named Main changes, QA1008; receipt SHA-256
908990cfe543e5393e780e51fea16c70b71adf77acc3d6e88e373116e9cda28f.
Local sequential legacy/completion real Chrome PASS, with one
committed/downloaded ZIP hash and postcleanup media verification;
this is a preformal probe only. Exact generated `.pyc` cache cleanup
restored the isolated toolchain fingerprint
4774abe73e5989257bd9a884365281941801bf46f41c6c9685a68b06dee7c350.
C2_SUCCESSOR15_OWNER_FREEZE PASS sealed 2226 paths at
a32107ca88c7ff8ea38ba9f03e2f8d802e03e333a744bcc03035382fafac49bd,
receipt SHA-256
f40d2c3e234ef0dfdd13d9317505457b0f5938247546979f9fd3a9103b9a87d2.
Loop Doctor READY; formal 20260914T052758Z-fb55229f requires fresh
roles, fixed Runner and Gateway. No acceptance or publication yet.
Fifteenth formal 20260914T052758Z-fb55229f reached DONE: Planner
READY, exact sole Coder 01a09e69-1d71-73f3-870f-35405dbebdda
IMPLEMENTED with no edits, Reviewer PASS with zero findings, Tester
READY, fixed Runner lint 20260914T053754Z-e306 PASS and full test
20260914T053823Z-fc69 PASS (2336 Python, 58 Web, Mock Chrome and two
real Chrome cases), Gateway PASS. Independent accepted-source audit
matched all 2226 paths to Runner assurance; current retained browser
audit verified 16 Assets, 21 files, exact ZIP/member/master bindings,
SRT, full MP4 decode and postcleanup evidence. Original QA appended
the two formal IDs; trusted publisher preflight matched original
469-path code CAS and exactly 47 scoped differences (22 new), then
atomically published and verified all 47. Postpublication lint
20260914T060159Z-8bd5 PASS and 43 targeted integration tests
20260914T060238Z-bcca PASS. Full report:
`docs/verification/stable-delivery-sd4-accepted-2026-09-14.md`.
Earlier terminal BLOCKED/FAIL records remain unchanged. No real
model/content/audio/hardware acceptance is claimed. Proceed to SD-5.
