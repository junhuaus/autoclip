# SD-4 A third bounded gate after a protected historical test correction

This is a NEW formal run in a NEW isolated `successor2` candidate. Preserve prior
terminal BLOCKED runs `20260913T190010Z-7534e06c` and
`20260913T192617Z-2fb21a52`, their exact Coder sessions, evidence, budgets and
findings. Do not resume either old session or use `--last`. No SD-4 code has been
published to the original worktree, which remains accepted SD-3.

The new candidate copied all 2121 source paths byte-for-byte from the final second
run's sole Coder snapshot. That Coder stayed in scope, fixed one Ruff line, and added
a post-commit lost-response reconnect regression before correctly reporting BLOCKED:
the full Runner found 2147 passing tests and one historical migration test failure
outside its allowed files. Main then corrected only that historical test's source
schema assumption: the row-preservation snapshot now freezes the tables actually
present at the legacy revision, rather than querying the new completion table before
its migration. The journal upgrade/downgrade still checks those historical rows;
Alembic model parity is checked at current head after re-upgrade. Main also applied
Ruff formatting to the new focused completion migration test. Isolated diagnostics
`20260913195228Z-e253` passed the prior failing test, `20260913195254Z-5fbf`
passed full lint, and `20260913195316Z-de98` passed 151 focused
completion/migration/queue/cancellation tests. These do NOT replace formal gates.
The earlier diagnostic `20260913195213Z-89e8` had a wrapper NameError before test
execution and remains retained as ERROR.

Read AGENTS.md mandatory documents in order, then the SD-4 Living ExecPlan,
ADR045, the original bounded A requirement and its first successor requirement.
Review the COMPLETE A source, not only this correction. Verify atomic same-key
project/run/intent creation and lost-response replay, current authorization before
replay/effects, exact actor/run/generation/version identity, resume adoption without
resetting leases/schedules/retries, read-only observation, owned completion attempts,
processing cancellation and expired-owner behavior, DEFERRED/WAITING accounting,
process-only completion, unsupported delivery goals pending, populated migrations,
foreign keys and legacy migration row preservation. Report an actual defect with
reproducible evidence; do not infer full SD-4 acceptance from bounded A.

Only the new sole Coder may write the A implementation/test paths listed in the
original requirement inside its isolated coding workspace. Main-owned migration,
models, DTO/ports, historical `test_semantic_unit_recovery.py`, cancellation
integration, ADR/ExecPlan/STATUS, dependencies and control plane are frozen. If any
protected change is needed, report exact evidence as BLOCKED instead of widening
scope. A new first Coder call has null session ID; subsequent repair resumes only
this run's explicit recorded ID. Planner, Reviewer, Tester and Gateway are fresh
read-only sessions. Fixed Runner alone resolves checked-in lint/test argv inside
its deny-default macOS sandbox and appends correlated evidence. Require fresh full
lint/test PASS, no P0/P1, exact source/toolchain integrity and semantic Gateway PASS.
A Gateway PASS cannot override failed, stale, mutated or uncorrelated Runner evidence.

This gate can accept bounded SD-4 A only. Selection, immutable delivery, persistent
Worker/API, synthetic artifact/browser inspection, recovery docs and final original
CAS publication remain subsequent SD-4 obligations. No user DB, source media,
credentials, global configuration, real/paid batch or SD-6 claim is authorized here.
