# Agent Runtime v2 completed-evidence acceptance requirement

This is the bounded input for the official LiveClip formal engineering loop. It
is not an ExecPlan. The sole authoritative Living ExecPlan is
`docs/exec-plans/liveclip-agent-runtime-v2.md`; its milestone ordering, trust
boundaries, recovery rules, and publication gates control this requirement.

## Bound B1 checkpoint

The formal loop must begin from a byte-bound external candidate derived from
this accepted B1 checkpoint:

- Branch: `main`.
- HEAD: `2f361fcddc0e63ae62ee62826e27b54bb8204c53`.
- ExecPlan SHA-256:
  `66f260931f768b9607260686c79a6bd71cfff74cbe5164ef8cdc75ba3cce8f05`.
- `STATUS.md` SHA-256:
  `a822890ace12680ab4fa9e9416272f564fff3b35a30fef8c73fcadc209a80397`.
- Staged paths: zero.
- Modified tracked paths: 15.
- Ordinary-untracked paths: 153 at B1; adding this requirement alone creates
  B2 with 154.
- B1 modified-path-list SHA-256:
  `4eb73e05bc64263b87286ca22bfe7395b3b02c1a0d25422bebea99843a244d4b`.
- B1 ordinary-untracked-path-list SHA-256:
  `36f3878acfba1ece2cdc8a97aa4d22af6a12343b65c951bb652a9354da1e347e`.

The complete B1 path inventory and aggregate receipt methods are frozen in the
ExecPlan. A candidate with a different HEAD, different B1 document bytes, or
uncorrelated source receipt is invalid.

## Problem

A completed prompt-first Agent v2 full-transcript run exists, but the product
does not yet prove the complete technical checkpoint:

1. It lacks one dedicated, read-only validation surface that correlates the
   result, journal, provider record, transcript, run identity, completion turn,
   artifact conservation, and final candidate set.
2. The score-only benchmark evaluator can emit an undifferentiated `PASS` and
   does not enforce immutable/no-replace report output or separate mechanical
   findings from human-required adjudication and v1-only concepts.
3. Agent render/package entry points do not yet prove their all-30 correlation
   to a validated completed bundle under the required no-replace contract.
4. Deterministic tests do not yet cover the complete acceptance, tamper,
   collision, provisional-reporting, and all-candidate delivery contract.

The Planner must determine whether each gap requires code or is already
satisfied. No change is justified solely because it is listed as a possible
gap.

## User-visible technical outcome

Accepted candidate code must enable a later trusted operator, without new model
inference, to:

- Validate the exact completed run and reject missing, mismatched, stale,
  mutated, incomplete, or uncorrelated evidence.
- Generate an immutable technical/provisional benchmark report whose status is
  truthful while human review remains pending.
- Render and package exactly the completed result's 30 final candidates—20
  `short_highlight` and 10 `mini_lesson`—against separately supplied,
  hash-bound source/transcript evidence.
- Inspect machine-readable hashes, candidate identities, profile counts,
  stream/decode facts, and package correlation without treating mechanical
  success as editorial or audio-quality approval.

The formal loop itself performs engineering tests only. It does not access or
process the protected original evaluation/media evidence or perform the later
real-media validation/render/package milestones.

## Immutable completed evidence

The later product flow must accept only this exact evidence identity:

- Run ID: `agent_v2_oauth_full_v4_20260928`.
- Result path:
  `data/evaluations/agent-v2-oauth-full-v4-20260928/agent-run-result.json`.
- Result SHA-256:
  `0c226f6aa8ca52c15441fabb2a6be316f16cf09288be90c9d1d8370df3f25e6a`.
- Status: `completed`.
- Final event/turn: 83; event count: 83; artifact count: 61.
- Run identity SHA-256:
  `e16912ef6dd5b4569e5ce90cc35def0171ffc8142ffa705efd6e69a6bcf62440`.
- Skill version: `agent_clipping_v2`.
- Loaded Skill SHA-256:
  `f853b37b18476037d6e2b2653246bca2569e0b937d868cedf3c5f7d169e44e4f`.
- Selected set: exactly 30 final candidates, comprising 20
  `short_highlight` and 10 `mini_lesson`.
- Five-file completed-bundle aggregate SHA-256:
  `4b437fb69fd8fe5a290ba3400a483899f5d296bd08c42bb1a32a3173c0b308ef`.
- Transcript:
  `tests/fixtures/8-30-full-transcript.srt`, 182,653 bytes, 3,159 cues,
  duration 6,630,860 ms, SHA-256
  `29b8751643ecc38a7183ab0c837a011cbca1e70a56de0788cd66292dbf364120`.
- Source: `input/8-30.ts`, mode `0444`, 3,143,702,536 bytes, SHA-256
  `818b669972b4e3f75f5358685ec231cd7daaaaa250c6525188291151c1109943`.

The five completed-bundle members and their SHA-256 values are:

```text
agent-run-result.json  0c226f6aa8ca52c15441fabb2a6be316f16cf09288be90c9d1d8370df3f25e6a
state/journal/checkpoint.json  1b87ace23155660754b88b2ca2ae0649206769ee28c08edbf84d5b1e8a712aae
state/journal/completed.json  786e4136fa13f1a2b4d71d5598eb93fc5a65eff6b4b6cba1d633592a0f0dbaec
state/journal/identity.json  15d61047963e1c8cb5123a1953450d5f0c4a63a910b046fd9e171af8a914e0e5
state/provider/agent_v2_oauth_full_v4_20260928.codex-app-server.json  234fdfc1d48bdaada4ab31ed9111a1ac18bd5bae2d0c8833375cb4a4a90de787
```

These identities define later correlation behavior; formal-loop tests must use
synthetic fixtures or temporary copies. The formal loop must not read, copy,
rewrite, resume, or use the original completed run as model input.

## Exact Coder allowlist

Only the formal Coder may write product/test code, and only these paths:

```text
src/liveclip/agent_runtime/__init__.py
src/liveclip/agent_runtime/checkpoints.py
src/liveclip/services/agent_clipping_validation.py
src/liveclip/services/agent_clipping_delivery.py
src/liveclip/cli/app.py
scripts/evaluate_agent_benchmark.py
tests/unit/test_agent_runtime.py
tests/unit/test_agent_clipping_validation.py
tests/unit/test_agent_clipping_delivery.py
tests/unit/test_agent_benchmark_evaluator.py
tests/integration/test_agent_clipping_v2.py
```

`src/liveclip/services/agent_clipping_validation.py` and
`tests/unit/test_agent_clipping_validation.py` may be new. The other paths
already exist in B2. If correct implementation requires any path outside this
set, the role must report `BLOCKED`; allowlist expansion requires a trusted-Main
replan and controller approval.

`qa/pipeline.jsonl` and `qa/test-report.md` are not Coder paths. Only the
deterministic Runner may append correlated records through the checked-in
control plane.

## Required behavior

### Completed-evidence validation

Validation must be read-only, deterministic, bounded, and fail closed. It must
correlate the five-file bundle by schema and content hash; confirm run ID,
status, run identity, Skill identity, final turn/event/artifact counts; conserve
the Global Review/final candidate/title relationships; and confirm the exact
30-candidate, 20/10 profile split. It must bind the supplied transcript by hash,
cue count, and duration. Render-time validation must also bind the separately
supplied source by mode/size/hash.

Missing, malformed, duplicated, unexpected, stale, symlinked, non-regular,
mutated, or internally contradictory evidence must produce a nonzero failure
without changing inputs or leaving a success marker.

A CLI validation surface must accept an explicit completed state directory,
transcript, and new output root. It must publish a machine-readable validation
receipt atomically and refuse an existing output root. Paths from evidence or
model data are never executed.

### Technical/provisional benchmark

The benchmark remains score-only Agent v2. It must:

- Match candidates and gold anchors one-to-one within the applicable profile:
  each candidate and each anchor may contribute credit at most once.
- Preserve stable candidate/anchor identities and expose the mechanical match
  mapping.
- Separate mechanically verifiable findings, human-required
  semantic/editorial/audio adjudication, and legacy-v1 concepts that do not
  apply to score-only v2.
- Never fabricate approval, risk-routing, audio review, subtitle calibration,
  or v1-parity fields.
- Use only `TECHNICAL_PASS_HUMAN_PENDING`, `TECHNICAL_FAIL`, or
  `INVALID_EVIDENCE` as checkpoint-level technical status unless later genuine
  human evidence supports another explicitly versioned contract.
- Refuse an existing output directory and publish JSON/Markdown reports
  atomically without replacing prior evidence.
- Never report full benchmark `PASS` while any human-required condition remains
  pending.

### Render and package binding

The existing `agent-clipping-render` and
`agent-clipping-review-package` flows must preserve their current safe,
no-replace behavior while accepting or deriving a validated completed-evidence
receipt. They must reject mismatched run, transcript, source, candidate set, or
render manifest.

Omitting candidate selection must mean all 30 final candidates. A subset cannot
satisfy all-30 acceptance. The render manifest and review package must preserve
candidate IDs, 20/10 profile counts, artifact/title/subtitle provenance,
source/transcript/result/validation hashes, output hashes, and no-replace
publication. Existing output roots fail closed.

This requirement does not ask the formal loop to render media. Later
`liveclip:4` work performs actual source-bound rendering and packaging only
after candidate `DONE`.

## Compatibility and immutable paths

The candidate must preserve v1 and dual-profile behavior, imports, commands,
schemas, fixtures, and historical evidence. In particular, the following are
immutable and outside the Coder allowlist:

- `src/liveclip/pipeline/dual_profile.py`.
- `src/liveclip/services/dual_profile_evaluation.py`.
- `src/liveclip/services/dual_profile_delivery.py`.
- `src/liveclip/clipping_skills/dual_profile_v1/**`.
- `src/liveclip/clipping_skills/agent_clipping_v2/**`.
- `tools/loop_engineering/**`, `loop-engineering.yaml`, and
  `config/loop-engineering/**`.
- Dependency locks and setup policy, including `pyproject.toml`, `uv.lock`,
  `Makefile`, `apps/web/package.json`, and `apps/web/package-lock.json`.
- Database/schema/migration paths.
- `docs/SOLUTION.md`, `docs/adr/**`, this requirement, the ExecPlan, and
  `STATUS.md`.
- All `input/**`, `data/**`, credentials, environments, caches, and retained
  evaluation/delivery evidence.

The protected 95-file dual-profile delivery tree remains exactly 1,107,318,738
bytes with aggregate manifest SHA-256
`9d7be809ba878f03a66e3fb9b9b7cccfd3896d71a10744f06197f4cd3ab378a9`.
No v1/default-profile promotion or parity claim is part of acceptance.

## Trust and session rules

- Trusted Main in `liveclip:0` is the sole outer writer and formal-loop
  interface. It does not directly implement product code.
- The formal Coder is the sole product/test writer, only in its isolated
  workspace and only within the allowlist.
- The Coder's first recorded `coder_session_id` is the only session that may be
  reused by the loop's bounded repair cycles.
- Planner, Reviewer, Tester, and Gateway are fresh read-only sessions.
- `liveclip:3` may monitor read-only. `liveclip:4` is reserved for later
  completed-evidence/render work. `liveclip:2` is reserved for later
  post-publication QA. `liveclip:1` remains unused absent a replan.
- Never use `--last`.
- Model output never supplies executable commands, paths, code, SQL, or media
  filtergraphs.
- The loop's automatic publication targets only its external candidate
  repository. Publication to the original worktree is outside this requirement
  and remains a later trusted-Main CAS gate.

Formal development-role calls are authorized engineering assurance. They are
not authorization for LiveClip Agent/content-model inference.

## Deterministic test expectations

Tests must use temporary/synthetic fixtures and prove at least:

- Exact valid completed-bundle correlation and deterministic receipt output.
- Rejection of each relevant hash, identity, count, status, completion,
  transcript, candidate-conservation, profile-split, and manifest mismatch.
- Rejection of missing/extra/duplicate/symlinked/non-regular evidence.
- No input mutation and no success publication after failure.
- Atomic no-replace output and collision rejection for validation and benchmark
  reports.
- One-to-one benchmark matching with no duplicate anchor or candidate credit.
- Truthful mechanical/human/non-applicable classification and absence of plain
  full PASS while human conditions remain pending.
- All-30 render/package selection and validation binding without invoking
  FFmpeg, services, credentials, network, or a model.
- Existing Agent v2 resume/tamper/delivery behavior remains compatible.
- Existing v1 and dual-profile targeted regressions remain green.
- CLI help/argument validation exposes only explicit bounded paths and does not
  duplicate business rules.

The formal Tester chooses required Runner IDs only from the fixed checked-in
allowlist. Final required commands remain:

| Runner ID | Exact argv | Timeout |
|---|---|---:|
| `lint` | `make lint` | 900 seconds |
| `e2e` | `make e2e` | 900 seconds |
| `test` | `make test` | 2,400 seconds |

`doctor` is available as non-final `make doctor` with a 300-second timeout.
The formal budget is exactly two plan cycles and three code cycles. Each role
call retains the checked-in 3,600-second bound.

## Required formal evidence

A valid `DONE` candidate must retain and correlate:

- Requirement hash, exact formal run ID, candidate root, HEAD, B2 source
  fingerprint, and sealed toolchain fingerprint.
- Fresh Planner, Reviewer, Tester, and Gateway artifacts.
- Exact sole Coder session ID and every bounded repair-cycle artifact.
- Pre/post candidate path, mode, size, and content manifests proving the delta
  is a subset of the allowlist.
- Runner request/result IDs, argv identity, timeout, source/toolchain
  fingerprints, bounded logs, and required PASS results.
- Append-only QA suffixes correlated to this formal run.
- Gateway PASS consistent with deterministic evidence and no unresolved P0/P1
  finding.
- A final candidate receipt showing no immutable-path, v1, dual-profile,
  control-plane, Skill, evidence, credential, or dependency mutation.

Semantic Gateway PASS cannot override failed, stale, mutated, truncated,
uncorrelated, or incomplete deterministic evidence.

## Acceptance and stop conditions

The formal candidate is acceptable only when:

1. Every code/test change is necessary for the stated technical outcome and is
   within the exact allowlist.
2. Completed-evidence validation, one-to-one provisional benchmarking,
   no-replace output, all-30 binding, and compatibility behavior are covered by
   deterministic tests.
3. Required Runner commands pass under the fixed sandbox and timeouts.
4. Fresh read-only Reviewer and Gateway report no unresolved P0/P1 issue.
5. Source, toolchain, role, Runner, QA, and candidate receipts are complete and
   mutually correlated.
6. The loop reaches terminal `DONE` within two plan and three code cycles.

Stop and report `BLOCKED` on any required out-of-allowlist edit, immutable-path
change, original-worktree access, evidence ambiguity, hash/correlation failure,
credential request, product inference attempt, session mismatch, missing
deterministic evidence, exhausted budget, or non-`DONE` terminal state. Do not
silently broaden scope, relax a gate, overwrite evidence, or start a replacement
run.

Human editorial quality, listening/audio quality, and audio-grounded subtitle
calibration remain `PENDING_HUMAN`. They are not formal engineering-loop
actions and do not block a technically valid candidate `DONE`. Candidate
`DONE` still does not imply default promotion, v1 parity, editorial/audio PASS,
or full benchmark PASS.

## Absolute prohibitions

This requirement authorizes no product evaluation/model inference, new
LiveClip Agent run, completed-run resume or reuse, credential access, service
start, real-media render, benchmark execution against the original completed
run, source/evidence mutation, cleanup, commit, or push. Do not run
`resume_liveclip.sh`.

Do not change Skills, control-plane code/configuration, dependency locks,
schemas, migrations, `docs/SOLUTION.md`, ADRs, the ExecPlan, `STATUS.md`, v1 or
dual-profile paths, QA except through Runner append-only behavior, `data/**`, or
`input/**`. Do not use `--last`. Do not expand the allowlist without a new
trusted-Main replan and controller approval.
