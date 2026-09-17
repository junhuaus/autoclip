# SD-4 bounded implementation C1: persistent completion dispatch

Start from accepted B2. Before coding, trusted Main records a `C1_BASELINE` PASS
receipt with a full accepted-B2 per-path hash manifest in the new isolated
candidate. It names the exact B2 DONE run/fingerprint, inherited and Main-modified
paths, matching HEAD/toolchain and no copied source media. A blocked run is never
silently reused; only a new run or its exact recorded Coder session may proceed.
Freeze candidate STATUS/ExecPlan with this run ID before formal review, leaving
future results pending. Preserved root QA journals are excluded from read-only
assurance source snapshots; Reviewer checks root history before Tester requests
the fixed Runner, and Gateway checks actual receipts afterward.
Wire one CompletionRunner into bootstrap and the persistent
Worker. Reconcile both processing-only and delivery-target intents without a client
process. Keep all business transitions in application/repository services; the Worker
only dispatches fixed task categories. Worker shutdown unwinds owned work and leaves
recoverable task/attempt truth.
Construct the completion repository with the resolved `data_dir` so bound
manifest, ZIP and Asset inspection resolves only owned generated files.
Pass the configured `settings.max_stage_retries` to the completion delivery-enqueue
path, matching the existing DeliveryService bound even when it differs from the
default of three; cover at least one nondefault value in a disposable SQLite test.
Keep completion artifact-inspection renewal within the configured Worker lease
period, using its existing bounded monitor interval or the configured heartbeat
interval; preserve cancellation and lost-lease fences in the integrated Worker.
Preserve the accepted B2 replacement-master fix: an obsolete successful render
or newer failed optional final cannot mask a compatible queued/running master.
Keep its disposable SQLite deferral/one-bound-delivery regressions passing and
do not requeue historical failed/stale renders.

Replace the current stage-first dispatch with a bounded rotating round over stage,
render, delivery and completion. Try each category at most once per round, continue
past IDLE or transient BUSY, stop after one handled action and begin the next round
after that category. Preserve the single-heavy-task lease fence and `--once` behavior.
Map completion claim contention to a bounded BUSY outcome so it cannot abort the
Worker loop or skip the other categories. Keep the rotation cursor in the live
Worker loop and advance it only after a handled category; a fresh process may
start at a fixed category without falsifying any persisted task state.
A waiting manual goal is not polled; deferred work honors `not_before`, does not consume
failure retries and cannot monopolize the Worker. Foreground drive may use the same
service when requested, but observation/watch never dispatches or cancels work.

Test actual SQLite leases with work in all four categories, category starvation cases,
waiting manual/no-client, Worker restart before/after selection and delivery commit,
shutdown and lease recovery. Include a processing run completed while no CLI is alive.
Preserve existing Worker/stage/render/delivery behavior. Require fresh independent
Reviewer/Tester, fixed Runner lint/test, Gateway and trusted isolated publication.
No original product publication or full SD-4 claim occurs at C1 alone.
