# Mini-lesson lineage and recovery

Status: V13 is accepted and integrated; see the [SD-3 report](verification/stable-delivery-sd3-accepted-2026-09-13.md).
New mini requests use V13; historical V2–V12 runs retain their exact recorded contracts.
V13 extends the V9 lineage/V11 transport baseline with bounded invocation recovery below.

A V9/V11/V13 mini lesson preserves the Discovery proposals, their routes through Topic Chains,
derived teaching units and each final outcome. The five outcomes are selected, manual, blocked,
rejected and excluded by Top-N. A proposal can have multiple terminal paths. Report original
proposal, derived-unit and path counts separately; these numbers need not match.

## What is saved

The immutable lineage config carries schema9 (V9), schema11 (V11) or schema13 (new V13), semantic result schema5, lineage contract
semantic-v5-lineage-v1, quality contract semantic-v4-quality-v2 and five prompt versions/hashes.
V2–V8 run snapshots retain their original exact fields and fingerprints.

Within the current generation, candidates/rough-candidates.json stores the complete local and
namespaced Discovery outputs, Link requests/results, Topic Chains, source dispositions, derived
units and semantic-ID-to-slot mapping. editing/edit-plans.json embeds semantic_v5 with the full
typed ledger, actual quality groups, statistics and current persistent candidate IDs.

These are internal generated assets. Use the application's resource IDs and authorized queries
for media access. Never pass a model-supplied local path to the renderer or media endpoint.

## Restart and retry

Use the existing product commands after confirming the exact project/run from status:

```bash
.venv/bin/liveclip status PROJECT_ID
.venv/bin/liveclip retry RUN_ID --wait
```

`retry` resumes a failed/cancelled processing run. It does not create a durable
selection/Delivery goal. For the current high-level flow, use `liveclip auto
VIDEO` to save a versioned Completion goal and `liveclip resume PROJECT_ID`
to reconnect to that exact goal; API/Web offer the same service.
Current retry readiness checks only the capabilities required by remaining work, using the
persisted run contract and a transactional recovery snapshot. A completed run is not retried as a substitute for creating a new generation.

After a crash following candidate/edit commit, V9 reload validates the committed asset identity,
source hash, config fingerprint, transcript context, local window IDs, once-only namespacing,
complete lineage graph, candidate contents and slot/DB-ID mappings. Edit reload rebuilds the
ledger and reruns deterministic quality gates, then checks the selected revisions and captions.
A mismatch fails explicitly before accepting the stored result. Do not hand-edit JSON, database
rows or hashes to make a failed identity check pass.

A new generation on the same project may reuse compatible semantic caches. Cached Discovery
keeps local IDs; namespacing occurs once after retrieval. Semantic unit IDs remain stable while
new persistent candidate IDs belong to the new generation. Different source/config/prompt/
lineage/cache identities do not become compatible merely because their output text looks alike.

## Diagnose a failure

Keep the run and failed task/attempt identities, safe error code and diagnostic asset reference.
Current semantic failure audits retain complete indexed business errors and the single repair
attempt, with credentials and hidden reasoning excluded. The attempt diagnostic belongs to its
exact lease; a stale worker cannot attach or publish it under another attempt.

Do not delete successful sibling caches when diagnosing a failing unit. Do not repeatedly retry
deterministic invalid output expecting a different acceptance rule. Network retry, semantic
repair and stage retry are distinct; V12/V13 also enforce immutable per-unit invocation bounds.
A remote call completed before its local receipt was saved is an uncertain execution window,
not evidence of exactly-once provider execution.

## Evidence limits

Synthetic tests cover actual SQLite stages, candidate/edit post-commit interruption, cross-
generation cache reuse with zero new semantic calls, zero-candidate completion, typed mixed
outcomes and retained MP4/SRT/quality artifacts. The current formal acceptance report must name
the final source, toolchain, Runner request and inspected artifacts before this implementation
is considered delivered. Synthetic output does not establish real Chinese content quality,
source-audio accuracy, paid-provider reliability or Apple hardware performance.


## V10/V11 semantic request budgets

New non-mini V10 and mini V11 runs use lossless semantic-cue-table-v1 transport. Existing
V2–V9 runs retain their original configuration and behavior. Complete cues, candidate/risk
material, invalid responses and validation errors are never truncated to fit a request.

`<STAGE>_INPUT_BUDGET_EXCEEDED` and `<STAGE>_REPAIR_BUDGET_EXCEEDED` are deterministic.
The rejected request made no model call; other requests in the stage may already have run.
A blocked repair retains its original call ID, output and complete validation audit and
records no fabricated repair call. The task attempt points to a committed, hash-bound
semantic budget/failure diagnostic below its project directory.

Inspect `measurement_basis` before comparing estimates: `semantic_planning_estimate` reports
the planner payload and configured reserve; actual provider-wire diagnostics include the
serialized request/schema representation. Configured tokenizer estimates are not exact
server usage. OpenAI's actual output allocation is included; Codex's reserve is an estimate,
not an enforced output-token cap.

Unchanged automatic and manual retries are rejected for budget failures. Correct the input
or use a context configuration that the selected provider/model actually supports, then
create an explicit new run. Keep the failed run and its evidence. Do not edit stored config,
clear audit files, reduce risk/error authority, or reset retry/repair counters to force a pass.
Compatible verified ASR results may be reused; semantic cache identity includes the transport
contract and full context-budget settings. Real model context/quality evidence remains SD-6.


## V12/V13 bounded execution and recovery

New non-mini V12 and mini V13 add semantic-bounded-units-v1 to the accepted V10/V11
transport and quality contracts. Historical configurations retain their recorded behavior.
Each semantic unit performs generation, validation and at most one schema-or-domain repair.
At most the configured concurrency is admitted; an observed global authentication, permission,
quota or configuration failure prevents replacement submissions. Valid completed siblings are
saved promptly while another unit is still working. Failed requests retain actual call evidence.

The semantic_unit_invocations table is immutable execution authority. Outcome Assets retain
complete typed evidence under runs/gNNN/semantic-units/ with immutable attempt ownership.
Independent expected hashes, config/input/source/prompt identities and domain validation must
agree before reuse. Ordinary Asset metadata or a plausible filename cannot authorize a call.
Reuse from an earlier generation also verifies that success's complete originating invocation
history, including every preceding outcome. Keep transient failure records with the success;
a missing, reordered, reassigned or corrupted predecessor invalidates reuse.

| Observation / code | Meaning and operator action |
| --- | --- |
| Authenticated success | Reuse without another semantic call; keep its outcome and journal. |
| Authenticated transient before any semantic repair | The same unit may have at most three logical invocations, including the first. Existing network retry bounds remain separate. |
| SEMANTIC_UNIT_INVOCATIONS_EXHAUSTED | The fixed invocation allowance is spent. Preserve evidence and change the input/configuration only through an explicit new run. |
| SEMANTIC_UNIT_EXECUTION_UNCERTAIN | Reservation exists without authenticated completion, including crashes before entry or after a response. Automatic retry cannot safely infer whether the provider ran. |
| SEMANTIC_UNIT_EVIDENCE_INVALID | An outcome, owner, hash or identity check failed. Preserve the database and files; restore an intact matching backup or diagnose the corruption. |
| ACTION_NOT_READY | A capability needed by the actual remaining work is unavailable or differs from the stored run contract. Restore that capability, then retry the same run through the normal service. |

Deterministic invalid output, any spent repair and cancellation cannot buy another repair
by retrying the same unit. A crash after publishing an outcome file but before journal association
is still uncertain. Do not delete journal rows, edit outcomes or hashes, reset counters, or
force an active V12/V13 database through migration downgrade. Back up the database and its
referenced outcomes together before operational migration; development evidence uses disposable
copies only and does not authorize migration of existing user projects.

CLI/API retry now inspect immutable stored configuration and actual remaining stages. When
processing checkpoints are complete, local render/package recovery does not require unused
ASR/LLM credentials. Local source, storage and media validation still applies. When semantic
processing remains, its needed capability is checked before ASR expense and at the provider
boundary. Provider construction may still be needed during partial semantic recovery; this is
not a promise that every partially cached run works with all provider settings removed.

Version/login probes show configuration readiness, not successful inference or protection
against every host execution restriction. A known deterministic restriction remains a real
failure. Actual late calls may be accounted after lease loss, but an expired worker cannot
publish new business success or reusable outcomes. Pre-entry cancellation and a process that
never started do not fabricate a model call; previously executed initial calls remain recorded
if a later repair cannot start.
If a Codex process started and then its output pipe failed, the executed initial or repair
call remains recorded. That differs from a genuine failure to start the process.

Processing retry still does not create a durable selection/delivery goal. That user flow is
implemented separately by SD-4 completion goals. Synthetic SDK/process doubles and generated media establish
engineering behavior only; real inference, Chinese content, audio and hardware acceptance are SD-6.

## SD-4 B1 selection checkpoint recovery (isolated candidate)

These rules describe the historical isolated B1 engineering candidate, before
the integrated SD-4 publication; B1 alone did not wire a persistent Worker,
public API or Delivery. Back up a
disposable candidate database and its related Assets together before investigating; do not
migrate, downgrade or edit a user's existing project as a development diagnostic.

An unsubmitted manual goal with eligible clips is `waiting_selection`. Its completion Task
is `WAITING` and creates no periodic attempts. An authorized submission supplies the current
intent `expected_version` and exact candidate ID/revision set. A deliberate empty set is a
submission: it wakes the same Task through `WAITING` → `QUEUED`, and one owned attempt records
`no_selected_clips` without a Delivery or ZIP. Zero eligible candidates instead record
`no_eligible_clips`. Default selection only approves candidates still pending inside the
write transaction; it preserves prior human rejections, including same-revision rejections.

If a manual submission committed but its response was lost, retry the **same** intent, actor,
original `expected_version` and selected ID/revision set. The durable action record resolves
that identical request to the saved checkpoint even if later reconciliation advanced the
intent version. A different payload or version is a conflict, not a fresh selection. First
effects and replay both require current active membership, `review_clip` permission,
unarchived project and the bound run/generation. Restoring access, if appropriate, requires
an explicit authorized membership change; a saved requester identity grants no privilege.

A nonempty committed checkpoint binds each selected clip, current revision and exact latest
review decision. B1 parks it as `waiting_work`: each eligible owned poll records `DEFERRED`,
sets `not_before` about 60 seconds ahead and leaves `retry_count` unchanged. It neither
reviews again nor creates a Delivery. Do not repeatedly submit, reset task counters or
package a later live selection to compensate for this deliberate B1 handoff; B2 adds the
single bound Delivery action.

If a selected revision or decision changes, checkpoint authentication fails closed. Keep
the intent, task, review rows and checkpoint intact for diagnosis; ordinary resume cannot
retarget it to a new selection. Inspect current project/run/generation, the saved checkpoint
and latest review decisions on a backed-up disposable copy. Any new selection or generation
requires a separate explicit authorized product action when later SD-4 integration exposes
one. Failed/cancelled processing or lost authority parks a truthful blocker and does not
reset a spent processing retry allowance. Read-only observation or client exit never cancels
the goal; cancellation is a separate explicit action that respects the owned lease.

## Historical SD-4 B2 bound delivery recovery

At the historical B2 candidate stage there was no persistent Worker or public
goal API. The bound Delivery behavior described below was subsequently
published with SD-4; use the current CLI/API guidance later in this guide
for operator actions.
Keep the intent, its completion Task/attempts, the idempotency action, Delivery row and
generated Assets together when diagnosing a disposable candidate database. Back up the
database and related generated files before inspection. Do not edit a user's project DB,
reset counters or package a later live selection as a substitute for the bound goal.

The saved `selection_checkpoint_json` fixes clip IDs, revision IDs, decision IDs and the
run/generation. The first authorized enqueue uses
`delivery_action_key=completion-delivery:{intent_id}` and commits it with one `delivery_id`.
After a lost response, inspect that same action key and Delivery ID/version; subsequent
polls observe that row and cannot silently bind a newer project delivery. A newer human
delivery version does not change the intent. Current `deliver` permission, membership,
project archive state and run/generation are checked again on replay and before effects.
Reinstating access, if appropriate, requires an explicit authorized membership change.

`MASTER_MISSING`, `MASTER_STALE` and `MASTER_FAILED[_EXHAUSTED]` mean the saved revision
cannot currently produce an eligible master. Inspect that clip's render Task, spec and
retry count; any recovery render is an explicit bounded action on the saved revision.
`SELECTION_CHANGED` means the saved selection no longer matches current eligible work;
do not retarget the same intent. `DELIVERY_FAILED` requires explicit package recovery;
polling does not restart its retries. `DELIVERY_BINDING_INVALID` means the action key,
Delivery ID or immutable version history disagrees and needs backup-based diagnosis.
`DELIVERY_ARTIFACTS_INVALID` means the bound manifest/ZIP or owned Asset hashes fail
validation. Preserve those files and evidence; do not report delivery success from a
succeeded Task or empty package alone. A queued/running compatible master or Delivery
waits with `not_before` and no retry increment. A lost completion lease records its own
attempt and respects the configured recovery allowance.

## SD-4 C1 persistent Worker recovery (isolated candidate)

C1 persistent Worker recovery passed its isolated formal gates on 2026-09-14;
the following paragraph records that historical C1 boundary before full
SD-4 and its public goal API were published. Back up a disposable candidate's SQLite
database together with its
generated Project files before investigating. Preserve the intent, Task, attempts,
selection action, bound Delivery row/version, manifest, ZIP and Asset hashes.

The Worker tries stage, render, delivery and completion once each per bounded
round, starting after the last handled category. IDLE or transient BUSY does not
abort the round; `--once` performs one such round. A manual goal in WAITING makes
no recurring attempts. Only an authorized explicit selection or resume can wake
it. A DEFERRED Task is different: it becomes claimable at `not_before` and its
deferral does not increment `retry_count`. Repeated observation, browser refresh
or a departed CLI cannot drive or cancel either state.

On SIGINT/SIGTERM, the Worker unwinds owned work and waits for any in-flight
bounded SQLite lease-monitor operation to terminate before its file handles and
runtime are closed. A Task/attempt that was running when the process stopped
remains in history until its lease expires; another Worker then uses the normal
bounded claim/recovery rules. Do not manually rewrite lease timestamps or reset
retry counts. If a saved selection committed before a crash, replay its exact
action identity; if Delivery was already enqueued, inspect its one saved ID and
version rather than creating a newer package. A current successful ZIP still
requires valid manifest, ZIP and owned Asset hashes, not merely a succeeded Task.
Historical failed/stale renders require an explicit bounded recovery action and
are never requeued by polling. Rollback retains database, attempts, actions and
generated artifacts; it does not downgrade a user database for a development test.

## Published SD-4 completion recovery

For a current goal, record its `intent_id`, Project ID, bound run/generation,
`version`, status, selection state and any Delivery ID from
`GET /api/v1/completion-goals/{intent_id}`. This read is observation only. A
lost create response can be retried with the same caller, exact canonical body
and `Idempotency-Key`; it returns the original committed goal even if the
source has since disappeared or processing readiness changed. A different
body/key is a new request and must pass fresh source and Provider readiness.
Do not create a replacement Project or run just to observe a stuck goal.

`waiting_work` can reflect a deferred owned Task at `not_before`; deferral
does not consume retry budget. `waiting_selection` is parked without periodic
attempts. Inspect the current clip IDs/revisions and submit an explicit
`selection` request with the latest `expected_version`; an empty array means
intentional zero selection and produces no ZIP. If a version, review decision
or generation changed, refresh the goal and eligible clips rather than
replaying stale selection. `needs_action` requires diagnosis and an authorized
explicit `resume` with the current version. Resume cannot reset failed
processing, render or Delivery budgets. Only an explicit `cancel` changes
the goal to cancelled; browser close, GET polling and watch interruption do
not.

After a Worker crash, preserve the SQLite database, Task/attempt records,
saved selection/action keys, bound Delivery ID/version and generated files.
Restart the persistent Worker and let its lease-expiry and fixed reconciliation
rules recover the same intent. Never hand-edit leases, retry counters,
Project pointers or a successful package. Before restoring or investigating
on a disposable copy, back up its database together with Project-generated
files. A successful `delivered` snapshot provides a signed download URL only
when the bound ZIP Asset resolves; verify the retained manifest, member and
Asset hashes and full MP4/SRT rather than trusting Task success alone. The
`processed`, `no_eligible_clips` and `no_selected_clips` outcomes have no ZIP.
Do not downgrade a real Project database or replace its SourceMedia reference
to recover a development test.

## SD-5 A preset-create recovery

The published `POST /api/v1/completion-goals/from-preset` accepts only an
absolute source path, a frozen preset ID and default/manual selection. If
the browser loses the response after the server commits, leave the form
unchanged and retry in the same tab. After a reload, reopen creation and
re-enter the exact source path, preset and selection; tab-scoped storage
retains only the pending request key and canonical-form hash, never the
source path or a credential. The same caller/key/body recovers the same
Project, run and goal. Changing any form field starts a new identity; if
storage is unavailable, heed the warning and inspect existing Projects
before risking a new submission. A successful 202 means the goal was saved,
not that a ZIP exists. Open the returned Project or read its goal to observe
queued/waiting/terminal status; refresh and client disconnect are read-only.

## SD-5 B1 Delivery progress and Worker restart

`GET /api/v1/completion-goals/{intent_id}` is an authorized read of the
durable Delivery projection. `completed` and `total` are local to the shown
phase, and `total=null` means the total is unknown. A heartbeat with no
change to `business_advanced_at` is not package progress. After a Worker
interruption or lease replacement, the old attempt's count remains in
history; the current projection returns to queued or starts at a new
`attempt_id`. Do not add counts from different attempts or treat a stale
count as permission to publish a ZIP link.

Restart the documented independent `liveclip-worker` process. Its normal
lease expiry, retry budget and reconciliation rules recover the same
Delivery ID; a browser refresh or GET does not perform recovery. If the
goal needs action, inspect Task and attempt outcomes before using the
version-fenced explicit resume route. A cancellation arriving during
copy/hash is acknowledged only by the currently owned lease. Do not
manually edit Task leases, `delivery_progress`, Asset rows or package
files. On a disposable copy, verify `deliveries/vNNN/manifest.json`,
`checksums.sha256`, ZIP members, committed Asset hashes, SRT and full MP4
decode before treating a recovered package as complete. The source media
remains a read-only reference.

The high-level `liveclip auto VIDEO` now saves the same durable preset goal
as API/Web and only observes it; an independent `liveclip-worker` owns media
processing. Keep the printed request key when creation is uncertain. Retry
with the same source and options, or use `liveclip resume PROJECT_ID`
(`--intent-id ID` when several goals exist) to reconnect. Resume preserves
manual selection wait and exhausted coordination history; only an eligible
`needs_action` gets an explicit version-fenced wake. A CLI interrupt or Web
reload stops observation, not Worker work. The Web stores the confirmed goal
ID before clearing its pending create identity and hides stale links when
authorization is lost. B2's synthetic tests do not establish real Chinese
content/audio or distinct 2h/4h performance acceptance.
