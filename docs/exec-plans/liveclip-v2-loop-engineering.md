# LiveClip v2 loop-engineering Living ExecPlan

This plan follows `.agent/PLANS.md` and implements ADR-026. It is independent from the product's fixed
media Pipeline.

## Purpose / Big Picture

Given a self-contained development requirement, LiveClip can autonomously produce and revise a plan,
implement code, obtain independent review and test analysis, run deterministic project gates and reach
an evidence-backed `done` or honest `blocked` state. A new operator can recover a run from repository
files without relying on chat history.

## Context and Orientation

The source project is `/Users/junhuaxu/Workspace/AGI/liveclip-ai`. The v2 sibling is
`/Users/junhuaxu/Workspace/AGI/liveclip-ai-v2`, branch `liveclip-v2/loop-engineering`. It was cloned with
full history at `6fe729c`; catch-up commit `6009b23` captured the product code now committed by the
source as `27691aa`, while
excluding runtime `data`, source media, ignored environment, credentials, caches and build output.

Control-plane code is under `tools/loop_engineering`; configuration, Prompts, Schemas and profile
templates are under `config/loop-engineering`; runtime state is ignored `.loop/runs`; append-only test
coordination remains `qa/pipeline.jsonl` and `qa/test-report.md`. `src/liveclip` never imports the
control plane.

## Scope and non-goals

M0 includes one durable bounded state machine, strict role artifacts, named Codex profiles, explicit
Coder session resumption, fresh read-only assurance roles, allowlisted Runner, evidence freshness and a
hybrid semantic/deterministic Gateway. It includes CLI/Make entry points, unit tests and documentation.

M0 does not schedule concurrent requirements, create per-task Git worktrees, commit/push/deploy changes,
call LiveClip media Providers, auto-merge branches or modify global profile files without the explicit
`install-profiles` command. Those are later milestones after one-loop acceptance.

## Progress

- [x] 2026-08-23 Read Product Spec, Solution, ExecPlan rules, v1/v0.2 Living plans and STATUS.
- [x] 2026-08-23 Clone full local Git history and create `liveclip-v2/loop-engineering`.
- [x] 2026-08-23 Transfer exact tracked diff and all non-data untracked code/doc context.
- [x] 2026-08-23 Verify tracked binary diff hash and filtered untracked path equality.
- [x] 2026-08-23 Pass migration baseline Ruff/format/mypy, 102 semantic tests and diff check.
- [x] 2026-08-23 Commit catch-up baseline as `6009b23`.
- [x] 2026-08-23 Implement M0 control-plane code, contracts, config, Prompts, Schemas and docs.
- [x] 2026-08-24 Run 33 focused loop-control tests plus Ruff and strict mypy; repair CLI import,
  Schema, session, evidence-tamper, bounded-output/process-group, status-recovery and routing gaps.
- [x] 2026-08-24 Complete the first independent read-only review and repair its P0/P1/P2 findings:
  deny-default Runner sandbox, frozen writable-role policy, sealed external toolchain/source execution
  snapshots, protected/correlated evidence, identical before/after fingerprints, explicit role BLOCKED
  routing, pre-cap streaming redaction, orphan process cleanup and strict YAML types. Coder now writes
  only an isolated candidate; assurance uses a separate snapshot and trusted publication is delayed
  until every gate accepts it. A final read-only scan is in progress.
- [ ] Complete append-only `make lint` and `make test` final gates. Lint passed. Python 862/862 and Web
  58/58 passed twice; the managed sandbox denied the Mock E2E Vite bind with `listen EPERM` before a
  browser assertion, so full `make test` remains an environmental `ERROR`, not a product PASS.
- [x] 2026-08-24 Receive follow-up independent read-only PASS: no remaining P0/P1 in the detached-Coder
  path; the abandoned coding tree cannot mutate assurance evidence, the delivery worktree or forge DONE.
- [x] 2026-08-24 Reconcile against the source project's newest local `origin/main` (`27691aa`): product
  source/tests/Schemas/locks were already identical; synchronize the newer v1 plan and `8-21-1`
  verification evidence and merge its STATUS facts without overwriting the v2 control-plane record.
- [ ] Create the local M0 implementation checkpoint; do not push without a new v2 remote.

## Work breakdown and ownership

The main Agent owns every file for M0 because the control plane, Make gates, AGENTS, Solution, this plan
and STATUS are shared integration surfaces. Review is read-only. No parallel writer is active.

Dependency order is contracts/config/store, Codex adapter, Runner/Gateway, workflow/CLI, tests, docs,
then independent validation. Product schemas, migrations, dependencies and `src/liveclip` behavior are
not changed by this milestone.

## Commands and expected observations

From the v2 repository root:

```bash
.venv/bin/python -m pytest -q tests/unit/test_loop_engineering.py
```

Expected: config/Schemas, persistence, explicit sessions, allowlist rejection and Gateway facts pass
without invoking Codex.

```bash
make loop-profiles
make loop-doctor
```

Expected: reviewed named profiles exist without overwriting different user files, and Doctor reports the
Codex executable plus five profiles ready. This is an environment gate, not a paid model call.

```bash
make lint
make test
```

Expected: all existing product and new control-plane checks pass. Each requested command is appended to
the QA pipeline before execution and receives a matching report entry. Browser-host permission failures
are `ERROR`, not product FAIL or hidden PASS.

## Acceptance criteria

- A requirement initializes a unique durable run and every transition/event is recoverable.
- Role boundaries use named profiles, strict Schemas and correct read/write sandboxes.
- Coder repair uses one explicit recorded session ID; no command contains `--last`.
- An unknown command ID fails before subprocess execution.
- Runner resolves checked-in argv, uses `shell=False` plus an outer deny-default OS sandbox, strips
  Provider/API secrets and records bounded redacted evidence.
- P0/P1, missing/failed/stale gates or semantic Gateway failure prevents `done`.
- Plan/code budgets end in `blocked`; there is no unbounded loop.
- Product runtime does not import or depend on the developer control plane.
- Lint, full tests and independent review pass with current evidence.

## Idempotency, retry, crash recovery and rollback

Run IDs and artifact sequence paths are no-replace. State writes use fsync plus atomic replacement;
events, QA requests and QA reports append. Agent final output is accepted only as bounded JSON matching
the CLI Schema contract. Re-entering a Coder repair uses its exact session ID. M0 does not resume a
half-finished Agent process: it records `blocked`; after inspecting evidence, create a new run.

Rollback is a normal Git revert of the M0 implementation commit; `.loop` is ignored and can be retained
for audit. Profile installation refuses to overwrite a different file, so rollback never deletes user
Codex configuration.

## Surprises and Discoveries

- The source working tree contained M22 code and 111 total changed/new files, not merely the older
  `6fe729c` snapshot. Local clone alone would have lost the current semantic implementation.
- `data/evaluations` and `data/exports` were untracked rather than ignored. Migration therefore used an
  explicit `data/**` exclusion instead of assuming Git ignore rules protected them.
- Current Codex CLI profile layers are named files under `$CODEX_HOME`, while explicit `exec resume`
  retains session configuration and does not expose the same root/sandbox flags. This makes persisted
  exact session identity part of the contract.
- 2026-08-24 Codex CLI 0.149 exposes many external feature surfaces from mutable user configuration.
  New sessions and exact-session resumes now ignore base user config/rules, explicitly disable those
  surfaces, and Doctor verifies every disable name without making a model call. Full generated argv
  for both paths passed the installed CLI parser.
- 2026-08-24 `make setup` could not download Python because managed DNS is unavailable. An exact
  existing local arm64 Python environment and a local copy of lock-matched Web dependencies allowed
  all non-browser gates to run without network or source-repository writes. The sandbox then denied
  `127.0.0.1:5174` binding before Playwright began.
- 2026-08-24 The independent security review found that `shell=False` alone did not contain untrusted
  repository test code. Runner now requires an outer deny-default macOS sandbox with localhost-only
  networking, a private HOME and fixed scratch/browser-output write roots. This managed Codex sandbox
  forbids applying a nested Seatbelt profile (`sandbox_apply: Operation not permitted`), so Doctor
  correctly reports NOT READY here and current Runner gates must remain environmental ERROR.
- 2026-08-24 Follow-up review proved that ignored `.venv`/`node_modules` could forge PASS even inside
  Seatbelt, and that hashing them in place left a detached-child race. The loop now verifies a genuine
  project-local environment, seals dependencies outside Coder authority before Coder starts, freezes
  Make/locks, and runs every gate in a retained external source snapshot whose Git worktree fingerprint
  must equal the exact pre-command value. The temporary sibling wrappers and copied Web dependencies
  used for offline framework validation were removed afterward; a normal `make setup` is required.
- 2026-09-14 SD-4 C2 successor11 and successor13 exposed a role-output limit issue: printing a full
  inherited hash manifest exceeded the control-plane redacted log cap, and printing a long Product Spec
  caused a role tool result to be truncated. Successor12's Coder also refused a truncated raw `git status`.
  The trusted state machine correctly blocked these runs before Runner. Main added bounded-read guidance
  to the five role prompts only: inspect file size first, read long documents in small sections and use
  hashes/counts/samples for machine evidence. It did not raise a log limit, widen Coder writes, alter
  Runner argv or its deny-default sandbox. The original 469-path CAS baseline matched exactly before the
  change; a separate five-prompt maintenance receipt and successor baseline preserve both versions.
  The focused control-plane suite (63 tests) and original lint passed. Product SD-4 still requires a fresh
  accepted candidate and all formal gates; the prompt maintenance is not product acceptance.
- 2026-09-14 SD-5 A formal `20260914T080446Z-bced5e5c` exposed a distinct evidence-visibility gap:
  fixed Runner lint and 2349 Python/70 Web/three browser tests passed with complete QA/log/ZIP cleanup,
  while fresh semantic Gateway returned FAIL because its assurance snapshot omitted the current `.loop`
  and QA control records. Independent forensic checks verified the sealed source and retained media,
  but the run remains BLOCKED. In successor 5, trusted Main added a Gateway-only read-only inspection
  bundle created after a full deterministic precheck. The bundle contains only current correlated
  requests, reports, bounded redacted logs and command results, is outside the source fingerprint, and
  is checked for mutation after the role. The canonical outer Gateway, Runner sandbox/argv allowlist,
  sole isolated Coder and exact-session policy remain unchanged. Successor 6
  added empty-directory tamper detection before freeze; the focused
  control-plane suite passed 65/65. Formal successor 7
  `20260914T091046Z-d9794226` is DONE with fresh semantic Gateway PASS,
  fixed lint/test Runner PASS (2351 Python, 70 Web and three browser
  cases), canonical deterministic correlation and a separate 2250-path
  source/evidence-bundle audit. Its product bytes were published by trusted
  code-only CAS. The bridge does not change the protected QA/Runner rules.

## Decision Log

- 2026-08-23: preserve full history plus current worktree in a new sibling branch; rationale: auditability
  and no mutation of the user's dirty source repository.
- 2026-08-23: keep developer orchestration outside `src/liveclip`; rationale: product runtime has a fixed
  Pipeline and must not gain a general workflow engine.
- 2026-08-23: combine a semantic Gateway with deterministic evidence; rationale: architecture needs
  judgment, while exit status, freshness and unresolved severity are facts.
- 2026-08-23: use finite replan/recode budgets; rationale: autonomy must converge or stop honestly.
- 2026-08-24: bind pre-existing `.loop`/QA evidence and Git HEAD across every Agent call; rationale:
  Coder's necessary product-worktree authority must not include authority to rewrite control-plane proof.
- 2026-08-24: ignore base Codex config/rules and disable nonessential external capabilities; rationale:
  named model profiles must not inherit mutable MCP/plugin/app side effects.
- 2026-08-24: freeze all loop policy bytes before Coder and contain every deterministic command in an
  outer OS sandbox; rationale: neither writable model code nor test code may rewrite its own authority or
  the evidence used to declare success.
- 2026-08-24: execute gates only from a retained source/dependency snapshot outside Coder authority;
  rationale: ignored developer tools are executable inputs and must be as immutable and attributable as
  the checked-in argv.
- 2026-08-24: give Coder only an isolated candidate workspace and delay trusted publication; rationale:
  a detached Coder descendant must never retain write authority to either assurance evidence or the
  delivered worktree.
- 2026-09-14: instruct every fresh role to keep tool results small and complete; rationale: a long
  read-only shell result can be truncated before the role sees it, so bounded evidence is required
  without weakening the deterministic truncation gate.
- 2026-09-14: make current Runner evidence inspectable to semantic Gateway through a trusted
  read-only assurance-local copy after canonical deterministic verification; rationale: a role that
  cannot read the current logs must not guess whether the actual components and cleanup passed.

## Risks and Mitigations

- Agent writes outside intent: dedicated branch, frozen policy, workspace sandbox, no approval
  escalation, independent review and deterministic gates.
- Secret exposure: requirements forbid credentials; child environments remove project/provider keys;
  logs are bounded/redacted and `.loop` is ignored.
- False success: deterministic Gateway cannot be overridden by role prose.
- Stale review/test: fresh assurance sessions plus HEAD/worktree fingerprints.
- Global profile drift: checked-in templates and refusal to overwrite a different installed profile.
- Concurrent loop collision: M0 documents one run per branch; per-run worktrees/leases are deferred.

## Recovery Notes

The next task is product development through the configured framework. This managed host cannot apply
the required nested macOS sandbox, so run final autonomous gates from an ordinary host terminal before
claiming a loop run PASS. Do not invoke a paid autonomous `loop-run` merely to retest plumbing. Do not
push because no v2 remote is configured.

## Outcomes and Retrospective

The framework implementation, 33 focused tests and final independent P0/P1 review PASS establish the
engineering baseline. Ordinary-host full gates remain environment-specific verification; product
development may proceed and the framework can be iterated when real use exposes a concrete gap.
