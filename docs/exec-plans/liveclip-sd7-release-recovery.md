# SD-7: Reproducible recovery and release evidence

Prepared 2026-09-14. This plan starts only after SD-5 B2 is accepted and
published. SD-6 real content/audio and distinct 2h/4h performance acceptance
is a separate prerequisite for any claim that the proposed profiles are ready
for those sources. Engineering release checks cannot substitute for it.

## Purpose and current boundary

An operator should be able to install LiveClip on the supported Apple Silicon
host, diagnose local dependencies, launch API/Web/Worker, create or reconnect
to one durable Completion goal, recover a failed/interrupted run, inspect an
authorized immutable package, and restore from a verified database backup.
The release record must distinguish verified local synthetic behavior from
real Chinese editorial/audio quality, cloud capability and long-source speed.

Product behavior is in `src/liveclip`, entry points in `src/liveclip/cli/app.py`,
`src/liveclip/api/app.py`, `src/liveclip/worker.py` and `apps/web`; installation
and recovery commands are in `Makefile`, `README.md`,
`docs/mini-lesson-recovery.md`, `docs/integrations/mlx-asr.md` and
`docs/exec-plans/liveclip-v1.md`. The authoritative contracts remain
`docs/PRODUCT_SPEC.md`, `docs/SOLUTION.md` and accepted ADRs. Source media
stays a read-only reference inside configured allowed roots. Local credentials
remain ignored; the previously exposed OpenRouter key is never used.

This milestone covers operational reproducibility, safe recovery and an
evidence-backed release classification. It does not add a model-generated
command path, grant the autonomous Runner network or user-data access, turn a
synthetic clip into a quality label, or promote experimental presets before
SD-6 evidence exists. Main owns shared schemas, locks, plans, status and
integration; the isolated formal Coder is the only role allowed to write a
candidate, and the fixed Runner and deterministic Gateway rules remain in
force for any source change.

## Milestones and work

- [x] Record the accepted SD-5 B2 source/QA/Gateway/retained-artifact receipt
  and publish operator documentation by compare-and-swap (2026-09-14;
  [evidence](../verification/stable-delivery-sd5b2-accepted-2026-09-14.md)).
- [ ] On the original delivery worktree, run `make doctor`, `make lint`,
  `make test` and `make demo` with one append-only QA ID/report per command.
  Record host/toolchain identity, observed outputs, generated media hashes and
  failure classifications. A prior candidate Runner PASS is retained as
  evidence but does not silently stand in for a required original command.
- [ ] Exercise one disposable recovery drill with an independent Worker:
  interrupted attempt, read-only reconnect, exact resume/retry, lease takeover,
  one immutable ZIP, source unchanged and current Asset lineage. Use checked-in
  fixtures; do not copy generated project state into the source tree.
- [ ] Exercise documented database backup/restore on a disposable destination
  and verify SQLite integrity plus representative Project/Completion/Asset
  read. Never restore over a live user database.
- [ ] Review `README.md`, recovery and integration guides from a fresh local
  install/operator path. Resolve wrong commands, stale foreground-auto claims,
  missing Worker startup or ambiguous request-key instructions.
- [ ] Run an independent read-only verifier over the Product Spec acceptance
  clauses. Classify each as implemented, tested, actually run, unverified,
  gap or risk, with direct evidence paths and no inferred PASS.
- [ ] Freeze release decision, exact source identity, dependency locks,
  host observations, known gaps and copyable recovery steps in `STATUS.md` and
  this plan. If SD-6 real or long-input evidence is missing, keep profiles
  experimental and label release readiness accordingly.

## Commands, evidence and failure meaning

Run from repository root with the project-local Python 3.12 environment and
Node LTS. `make doctor` checks actual host FFmpeg, providers, model bytes,
browser/runtime readiness and permission paths; a failure is an environment
or configuration finding, not a model-quality result. `make lint` checks
Ruff, formatting, MyPy, schema and Web types. `make test` runs Python, Web
unit and real Chrome fixtures. `make demo` must create its own copyright-free
source and inspect a current clean 9:16 MP4, SRT, contact sheet and ZIP;
capture the printed Project/artifact paths and independently verify them.
Record commands in `qa/pipeline.jsonl` before execution and append one
correlated result to `qa/test-report.md` afterward. Do not edit old entries.

Use `liveclip db-backup` and `liveclip db-restore --backup ABSOLUTE_BACKUP
--output ABSOLUTE_NEW_PATH` only against disposable drill data. For a durable
goal, preserve the caller and request key for uncertain creates, inspect the
exact Project/intent and authorization, run `liveclip resume PROJECT_ID
--intent-id ID` only for an eligible existing goal, and keep ordinary watch
read-only. Interrupting a watcher must not cancel a Worker or publish an
uncommitted package. If a step fails, retain its exact QA ID, command, exit
code, safe log excerpt and whether the cause is deterministic, environmental
or transient. Rerun with a new QA ID; do not overwrite a failure.

## Risks, decisions and recovery

The local development host can differ from a clean Apple Silicon operator
host in PATH, VideoToolbox and FFmpeg features. Record fallback behavior
observed here and leave a separate unverified host item where no test ran.
Model credentials, price and upstream behavior may change; verify current
capability only with bounded authorized calls in the supported product
environment, never through the developer Runner. Human review must inspect
and listen to real clips before quality acceptance. Distinct 2h/4h inputs
cannot be inferred from `input/8-30.ts` (about 110m34s).

Decision log, 2026-09-14: keep SD-7 engineering checks separate from SD-6
quality/performance evidence. This prevents a successful Mock/browser/demo
run from being reported as a real-source release result.

Surprises and discoveries: SD-5 B2's synthetic real-browser suite can pass
alone and later encounter a browser-navigation race when repeated inside
`make test`. Preserve both results and require the final UI and authorized
download assertions in the repaired test. The frozen local ASR reference
`input/8-30.ts` is about 110m34s, shorter than the distinct 2h/4h cases.

Outcomes and retrospective: open. Fill in the exact accepted B2 evidence,
original delivery-worktree command IDs, artifact identities and remaining
release classification only after those commands actually run.

2026-09-14 partial SD-7 evidence: the original worktree passed `make lint`
QA `20260914233622Z-09a1`, product `make doctor` QA
`20260914234349Z-3478`, and `make demo` QA `20260914234410Z-3c86`.
Demo produced Project `demo_20260914T234417_da84a28b`, three candidates,
a 12.000-second 1080×1920 H.264/AAC master and ZIP SHA-256
`811b28f28b7ce22a85ad35a8c104c7774b8366067031ce8f55af8d788bb98233`;
full decode, ZIP CRC/four member hashes and opened synthetic contact sheet
passed. `make loop-doctor` QA `20260914234523Z-7e5f` was READY. The
original-worktree full `make test`, recovery drill, backup/restore and
independent requirement classification remain open, so SD-7 is not done.

First remaining SD-7 task: run and record the original delivery-worktree
`make test` under a new append-only QA ID, then address the first concrete
failure without relaxing the Coder/Runner control plane. Record branch, HEAD,
worktree status and the next unambiguous step in `STATUS.md` on every pause.
Outcomes and retrospective remain open until the evidence above exists.

2026-09-15 original QA `20260914T235154Z-d6b3` remains **FAIL**. It passed
2425 Python tests, 78 Web tests, Mock Chrome, legacy real Chrome and durable
Completion Chrome, then the final B2 Worker correctly refused an inherited
nonempty OpenRouter credential in its disposable Mock fixture. Diagnostic QA
`20260915T002122Z-fc7d` passed the unchanged B2 scenario with that variable
explicitly empty, retaining 22 Assets, one authorized ZIP, full MP4 decode,
wrong-producer rejection and owned cleanup. This proves an environment
isolation defect in the harness; it does not relabel the failed full test.

Formal hermetic repair successor `20260915T002909Z-a9483528` uses sole Coder
session `01a0a27b-0012-7812-893c-6cda83339b2d` and an isolated candidate
without user source, Project, model or evaluation data. The sealed assurance
source differs from the original in exactly
`scripts/run_real_browser_e2e.sh` and
`tests/unit/test_b2_synthetic_worker.py`: both cloud credential variables are
emptied before any fixture process, with regression coverage, while the B2
Worker remains byte-identical and fail closed. Fresh Reviewer passed with no
findings; fixed Runner lint and full browser E2E passed. Full-test QA
`20260915T004233Z-e801` passed 2426 Python, 78 Web and Mock Chrome but failed
the first real release flow. A settings PATCH returned management version 2;
the card's immediate approval POST still used version 1 because its background
refetch had not completed, and the API correctly returned
`409 STATE_CONFLICT`. The formal run is terminal BLOCKED before Gateway and
unpublished. Its log, trace and screenshot hashes are preserved in
`../verification/sd7-release-version-race-2026-09-15.json`.

Successor `20260915T011709Z-e84c1e80` was cloned from current Main plus the two
sealed harness fixes, with the failed formal QA history and no user data. Fresh
Planner is READY and the new sole Coder is working only in
`apps/web/src/ReleaseWorkspace.tsx` and its Web test. Required behavior is to
apply successful authoritative release snapshots to the list cache before a
next version-consuming action, preserve preview URLs/unrelated rows and
background convergence, serialize card mutations, and keep real 409 conflicts
visible without retry. No candidate result is accepted until fresh review,
fixed lint/e2e/full test, Gateway, formal DONE and independent source/evidence
audit all pass.

A disposable Mock Project/Completion/Asset backup/restore drill script is
prepared under ignored `.loop/development/sd7-release-recovery/` but has not
yet executed. The initial [release classification](../verification/sd7-release-classification-2026-09-14.md)
is section-level only, with every missing real/cloud/long-input result marked
unverified. Operator-document review found two stale recovery references;
`docs/mini-lesson-recovery.md` now directs current users to `auto`/`resume`
and names the actual `liveclip-worker` executable. Finish the current QA
and postpublication full test before appending a new drill request so pipeline
order stays unambiguous.

The prepared recovery drill will run three existing, accepted-source scenarios
in one QA command: `test_independent_worker_survives_cli_exit_and_watch_interrupt`
for read-only reconnect/source identity; the nonempty
`test_disconnected_http_goal_survives_lost_responses_and_worker_restarts`
case for exact create/selection replay, current Assets and one downloadable
ZIP; and `test_publication_crash_and_expired_worker_recover_same_immutable_package`
for lease expiry, successor fencing and byte-identical publication recovery.
They use separate disposable Mock fixtures, so the result is a recovery
battery over the same contracts rather than one shared database history.
Preserve that limitation in the final classification.
