# SD-1A continued development — offline verification, publication held

## Current continuation: reviewed isolated prerequisites, full Runner pending

The user's latest instruction authorizes continuous development through completion;
individual Coder tasks and real-model cost limits remain bounded. Original source,
media/data and blocked Run20260912T160102Z-12b7777d remain unchanged.

Four isolated prerequisites preserve full baseline manifests under `.loop/development`:
CLI host/resume/effective-policy compatibility; sealed Python entrypoints and private
build caches with exact ancestor metadata reads; secure-file O_SEARCH intermediate
traversal; and offline pinned tokenizer data plus same-sandbox process cleanup.
Fresh read-only reviews of all four pass. The fourth review01a09697-e2f6-7ea2-87b6-0ff8eb743a8e
has one P3 concurrent-cache-publication test gap to close after its active Runner exits.
No final five-role acceptance is claimed by these bounded reviews.

Latest workspace: `.loop/development/loop-offline-runner-20260912/candidate`.
63 focused regressions and full static checks pass. Actual sandbox QA20260912170752Z-4723
passes15 observations: source nofollow reads and own/orphan process-group cleanup work;
foreign supervisor signal0, HOME listing/private data, source+QA writes, synthetic.env
read and external network remain denied. Exact fixture/script hashes and complete output
are retained in parent `sandbox-probe-20260912T170752Z/receipt.json`.

Actual prior combined test e904 had44 failed/1043 passed due missing tokenizer cache
and denied own-group signals; preserve that failure. Latest existing AllowlistedRunner
run20260912T170850Z-3fdd7dcf has lint563f PASS and test2bdf in progress on fingerprint
d0d374d15f3f80286bdd9d94149742a4be40ef082afa5605d1109f591022b34a. Its candidate stays frozen.
Runner now rejects incomplete/truncated capture even for exit0; no log cap, command ID,
Gateway requirement, Coder authority or retry limit is relaxed. No product publication.

The sections below are historical checkpoints; their former next-step instructions
are superseded by STATUS.md's current focus.


Date: 2026-09-12 PDT. This supersedes the open coding/test gaps in the September 11
checkpoint, not its historical evidence. No formal Loop PASS or publication.

## Final result of this continuation: Planner tool compatibility blocked

The exact command `make loop-run RUN_ID=20260912T160102Z-12b7777d` was executed
from the prepared candidate after both Doctor checks passed. It ended with make
exit 2 and durable state `blocked` after the configured two plan cycles.
Both fresh Planner artifacts are `NEEDS_INPUT`: the actual CLI tool event says
`Code Mode is unavailable because code-mode host is disabled.` The installed CLI
is 0.154.0. `CODEX_DISABLED_FEATURES` in `tools/loop_engineering/config.py` contains
both `code_mode` and `code_mode_host`; this reviewed policy was not altered.
This is a newly demonstrated role-tool compatibility gap, not the earlier
Coder-file write or macOS Runner sandbox blocker. Doctor currently checks sandbox,
profile equality and parser compatibility, without a real role-tool access check.

Durable evidence is below candidate `.loop/runs/20260912T160102Z-12b7777d/`:
`state.json`, `events.jsonl`, `artifacts/planner/001.json`, `002.json`, and both
`agents/planner/*-events.jsonl` files. A separate immutable observation with their
SHA-256 identities is retained at
`.loop/development/sd1a-20260912/formal-attempt-20260912T160102Z-12b7777d.json`.
No state or role receipt was manually edited. No new Run was created to bypass
budget exhaustion. Both Planner model sessions returned artifacts; they could not
inspect repository files. These are development-model attempts, not product
Provider/video acceptance.

The terminal state has code_cycle=0, coder_session_id=null, command_results=[].
No Coder, Reviewer, Tester, Runner lint/test or Gateway ran; no candidate was
published. All ten SD-1A source/test hashes still match the checkpoint. The
original product source/tests still match the persistent baseline. Ordinary
focused diagnostic 20260912160429Z-9fee passed 33 control-plane tests in 10.76s;
this does not prove actual Planner tool usability or formal acceptance.

Next concrete task: a separately reviewed Loop/CLI compatibility prerequisite.
Determine a supported role-tool configuration/runtime and prove real read-only
repository access, Coder-only isolated writes, exact-session resumption, and
unchanged Runner authority. Keep the current SD-1A product candidate intact;
its requirement explicitly forbids changing Make/locks/Loop policy within this
work package. Do not simply remove disable flags, migrate permission policy,
downgrade global CLI, edit a blocked run, or rerun unchanged conditions. After a
verified prerequisite change and its independent security review, form a new
reviewed baseline and start a bounded new formal run citing this failed attempt.

Recovery documents and QA tails are synchronized into the candidate after the
blocked run ended. The recorded run requirement/artifacts remain immutable;
handoff-manifest.json describes the updated handoff, not an accepted snapshot.

## Earlier in this continuation: host readiness repaired

At 2026-09-12T15:58:08Z the already-authorized repair was applied from a session
with actual target write access. Only the dedicated Coder profile was replaced,
atomically, after checking the previously recorded hashes and regular-file identity.
Backup (no overwrite, mode 0600):
`/Users/junhuaxu/.codex/liveclip-loop-coder.config.toml.sd1a-backup-20260912T155808Z-7dd9`.
Its original SHA-256 is 7a5b1b3de1f20b25bccc89c0889375c8cc820f3e9936f2d292fe392d3b3482e0;
the installed file now equals the template SHA-256
cdb1e0ae94c3300c1b435354a74a56c31188037d73f9119344b216bb8339616f.
Only model_reasoning_effort and projects differed. Model, sandbox_mode=workspace-write
and approval_policy=never were preserved. Other role profiles and the main config
retain their hashes; credentials were not read, copied or modified.
The private metadata receipt is
`.loop/development/sd1a-20260912/profile-alignment-20260912T155808Z-7dd9.json`.

Original-worktree doctor 20260912155814Z-75a5 and isolated candidate doctor
20260912155930Z-ca22 both return READY, exit 0: the actual Runner sandbox activates
and installed role profiles match. Candidate-local make setup
20260912155847Z-e97e passed (Python 3.12.14 arm64, SQLite 3.53.1 WAL-safe;
63 Python and 220 Web packages). Source and lock bytes remain unchanged. npm
reported two moderate and one high dependency advisories; these are recorded,
not silently resolved by changing the frozen locks.

Before this update, all ten source/test hashes and seven handoff hashes matched,
both old QA prefixes were intact, and original/candidate handoff copies matched.
A complete candidate/baseline path comparison found only the ten approved
source/test files and five handoff documents changed. The persistent baseline
is unchanged. Shared recovery documents and this requirement continuation will be
included before the formal freeze; subsequent QA writes remain append-only.

The prepared candidate was then submitted to the configured bounded Loop. It uses
fresh read-only assurance roles, one isolated Coder with exact session resumption,
and unchanged Runner policy. No formal gate, product publication or real model/video
acceptance is claimed by setup/doctor. Historical environment blocks below are
superseded by these actual host checks, not erased.

OpenAI Docs verified the distinction between sandbox execution and approval policy
in the [official permission documentation](https://learn.chatgpt.com/docs/permissions).
No permission-policy migration or relaxed role/Runner setting was used.

## Result

The three outstanding bounded work items are implemented and independently
reviewed. Final full Python verification passed under QA item
20260912151507Z-b011: 1064 tests passed, 13 deprecation warnings, 254.32 seconds.
All ten accumulated source/test hashes still match the checkpoint after the run.
This is offline verification, not formal acceptance or publication.

1. Actual Stage execution now has regression evidence for one valid sibling plus
   one invalid sibling: successful cache survives failure, the invalid result
   creates no cache, the semantic repair budget is spent only once, and explicit
   generation-2 recovery requests only the failed sibling.
2. The real Codex Structured Provider parsing/repair path is tested with a replaced
   subprocess boundary, unchanged strict Schema and exactly two calls for mixed
   nested Schema/duplicate errors, on both success and failure.
3. Boundary/Global raw preflight and final validation share local cue/reference
   checks. Global interruption evidence is now checked under the current contract.
   Missing/incorrect output Profile cannot change the authoritative duration gate.
   Missing decisions do not create inferred keep obligations. A malformed ID
   cannot hide another row's known unknown/duplicate ID.

The following positive cases remain valid: 90/300-second endpoints, local
background evidence, DROP without a retained interval, and original Boundary
evidence outside the shifted Global context after an authorized boundary repair.
Global contexts stay candidate-local and retain original global cue IDs.
Historical wire models, Prompt bytes, old contracts and Deliveries remain unchanged.

## Persistent checkpoint

- Candidate: /Users/junhuaxu/Workspace/AGI/liveclip-ai-v2/.loop/development/sd1a-20260912/candidate
- Baseline: /Users/junhuaxu/Workspace/AGI/liveclip-ai-v2/.loop/development/sd1a-20260912/baseline
- Hash manifest: /Users/junhuaxu/Workspace/AGI/liveclip-ai-v2/.loop/development/sd1a-20260912/checkpoint.json
- Original baseline /private/tmp/liveclip-sd1a.lIT70b/baseline is retained, not deleted.
- Baseline copy was checked with checksum-based rsync dry-run: no differences.
- Delivery worktree source and tests were checked against the baseline: no text
  differences; ignored bytecode excluded. Existing user edits were preserved.
- Branch remains liveclip-v2/loop-engineering at HEAD
  6009b23859564b2bfdc193eee366afd990b9ef5d.

Only semantic_profiles.py and test_semantic_profiles.py changed inside the candidate
on this continuation. The full accumulated SD-1A patch consists of six source
files and four test files, listed in the previous checkpoint and hash manifest.
No configuration, dependency, Prompt, wire Schema, renderer, ASR or permission
changes were introduced. The five SD-1A handoff documents and append-only QA logs
have subsequently been synchronized from the original worktree into the candidate,
as recorded below. Formal acceptance gates must still run against a newly frozen
snapshot, not reuse these diagnostics as their evidence.

## Test evidence

Exact commands and candidate working directories are in qa/pipeline.jsonl;
matching outcomes are appended to qa/test-report.md via qa-test-pipeline.

| QA ID | Result |
| --- | --- |
| 20260912150737Z-b001 | 59 Profile tests passed before sibling test addition |
| 20260912150738Z-b002 | Loop doctor ERROR, exit 2, same environment blockers |
| 20260912150908Z-b003 | 248 passed, 2 test assertion failures; fixed to inspect exception code instead of safe message |
| 20260912150910Z-b004 | Mypy passed, 168 source files |
| 20260912150955Z-b005 | Full Python suite: 1054 passed, 13 deprecation warnings, 254.00s; before final partial-JSON refinements |
| 20260912150957Z-b006 | Ruff checks passed, 319 files |
| 20260912151140Z-b007 | Expanded Mypy passed, 177 application/script/tooling files |
| 20260912151142Z-b008 | EditPlan Schema drift check passed |
| 20260912151445Z-b009 | Final partial-JSON/Profile tests: 72 passed in 3.02s |
| 20260912151447Z-b010 | One Ruff SIM102; fixed without changing semantics |
| 20260912151507Z-b011 | Final unchanged candidate: 1064 Python tests passed, 13 deprecation warnings, 254.32s |
| 20260912151509Z-b012 | Final Ruff check/format: 319 files; Mypy: 177 files, passed |

These are ordinary supervised diagnostics, not formal Runner receipts. Network
responses are local MockTransport fixtures and Codex subprocesses are intercepted;
neither paid models nor user videos were run. The Stage-only failure fixture
intentionally removes request cue authority to reach the final Stage guard: it is
fault injection, not a normal production request.

The OpenAI Docs skill was used to confirm the
[official Codex exec JSON interface](https://learn.chatgpt.com/docs/developer-commands#codex-exec).
Tests preserve the existing production adapter boundary and do not introduce a
new transport or replace runtime AI with development-Agent decisions.

## Independent review

Two read-only DevelopmentSubagents reviewed their bounded areas. The Stage/Codex
review closed its two test gaps. The reference review found three partial-JSON
preflight P2 issues; all were fixed with ten parameterized regressions and the final
review closed all three without new findings. Reviewers did not run tests and these
are supplementary reviews, not formal Loop role receipts.

## Remaining blocker and next action

Formal Loop doctor still fails:

    macOS Runner sandbox cannot be activated
    profile differs from reviewed template for coder

Read-only comparison identifies differing installed Coder configuration fields:
model_reasoning_effort and projects. No field values or credentials were logged.
Expected template SHA-256:
cdb1e0ae94c3300c1b435354a74a56c31188037d73f9119344b216bb8339616f.
Installed profile SHA-256:
7a5b1b3de1f20b25bccc89c0889375c8cc820f3e9936f2d292fe392d3b3482e0.

The user subsequently authorized aligning the dedicated Coder profile with the
reviewed template. This session still cannot write the global profile directory
or request escalated execution; user authorization does not change tool access.
Do not weaken the checks, run against an unreviewed dirty tree, or directly publish.
The next action is an authorized compatible host/session and explicit resolution
of the Coder profile difference, then verify the integrated handoff, freeze the candidate,
and execute required make lint/make test (including Web/browser E2E) plus formal
Reviewer/Tester/Gateway evidence. No SD-1B work or real-content acceptance is claimed.

Safe offline reproduction, from the persistent candidate:

    PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 /Users/junhuaxu/Workspace/AGI/liveclip-ai-v2/.venv/bin/python -m pytest -q -p no:cacheprovider

## Authorized host repair: still blocked by session access

User response: authorization granted on 2026-09-12. QA request
20260912152344Z-c001 reran `make loop-doctor`: exit 2, the same two blockers.
Read-only comparison confirmed the same profile hashes and differing key names
shown above; the target is a regular file, not a symlink. No global file was
modified or backup created in this restricted session. No product or candidate
source changed, and no model or paid run was started.

The authorization covers only this target:
`/Users/junhuaxu/.codex/liveclip-loop-coder.config.toml`.
From a host/session that actually permits that write, preserve an independent
no-overwrite backup with private permissions, then align the file byte-for-byte
with `config/loop-engineering/profiles/liveclip-loop-coder.config.toml`. Verify
the expected hash above. Leave the main config, credentials, other role profiles,
reviewed template and sandbox rules untouched. If source or target bytes have
changed, re-inspect rather than using stale assumptions.

`make loop-profiles` alone cannot repair the difference: the existing installer
deliberately refuses to overwrite differing files (tools/loop_engineering/cli.py,
lines 151–167). The Runner probe is independent (lines 71–85); Coder alignment
does not prove sandbox readiness. Rerun `make loop-doctor` on the compatible host
before any formal gates. A supplementary read-only audit confirmed this scope;
it is not formal Gateway evidence.

OpenAI Docs was used to check the
[documented permission boundaries](https://learn.chatgpt.com/docs/permissions):
workspace write access is not permission to mutate arbitrary global paths.
No permission-profile migration or broad-access workaround was introduced.
The remaining action is an environment/session change, not another request for
the same user authorization.

## Handoff materials synchronized without source changes

On the subsequent continue request, doctor item 20260912153037Z-d001 again exited
2 with the same two environment blockers. No permission or configuration write was
attempted. A read-only supplementary audit found that candidate STATUS, the stable
delivery ExecPlan and QA files still matched the persistent baseline; ADR 030 and
both SD-1A verification documents were absent. There were no candidate-only changes
to these seven paths. All ten source/test checkpoint hashes remained valid.

The following exact original-worktree materials are now in the candidate:

- STATUS.md
- docs/exec-plans/liveclip-stable-delivery.md
- docs/adr/030-versioned-semantic-validation-contract.md
- docs/verification/stable-delivery-sd1a-2026-09-11.md
- docs/verification/stable-delivery-sd1a-2026-09-12.md
- qa/pipeline.jsonl
- qa/test-report.md

QA synchronization only appended the missing tail: all seven existing pipeline
lines and 214 existing report lines were preserved byte-for-byte. Commands retain
their original request IDs, working directories and diagnostic qualifications.
No historical result was converted into a formal Runner receipt. Candidate and
original copies were checked for exact equality; source/test hashes were rechecked.
The separate `.loop/development/sd1a-20260912/handoff-manifest.json` records these
material hashes and leaves formal_gate_pass/published false. It is not an immutable
Runner snapshot, permission grant or release approval. Future QA appends require
the handoff hash to be refreshed before a formal freeze.

Remaining action: use an actually permitted host/session for the already-authorized
single-file Coder repair and independent Runner readiness check, then obtain formal
lint/test/Web/E2E/Reviewer/Gateway evidence. Repeating offline Python tests or user
authorization cannot resolve those host restrictions.
