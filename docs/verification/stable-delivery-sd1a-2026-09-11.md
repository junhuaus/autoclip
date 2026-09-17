# SD-1A development checkpoint — candidate held

Continuation: see [September 12 checkpoint](stable-delivery-sd1a-2026-09-12.md) for
the implemented P2 follow-ups, persistent baseline and current verification.
The remainder of this file is the preserved September 11 checkpoint.

Date: 2026-09-11 PDT / 2026-09-12 UTC.
Result: isolated implementation and targeted offline checks complete; SD-1A is not
accepted or merged, and the full stable-delivery milestone is not complete.

## Locations and preserved baseline

- Delivery worktree: /Users/junhuaxu/Workspace/AGI/liveclip-ai-v2
- HEAD: 6009b23; branch: liveclip-v2/loop-engineering.
- Baseline clone: /private/tmp/liveclip-sd1a.lIT70b/baseline
- Persistent ignored candidate: /Users/junhuaxu/Workspace/AGI/liveclip-ai-v2/.loop/development/sd1a-20260912/candidate
- Baseline retained 1,997 paths: all tracked files plus explicitly scoped untracked
  code/config/tests/system documentation; no untracked real media, database,
  credentials or ordinary case output.
- Before edits the scoped content fingerprint matched original, baseline and candidate:
  6e836c755d1c79d185ca7c5331137af1b3d910e86f4a9f76d6cab4365f4e31ce.
- Baseline/candidate initial Git worktree fingerprint:
  933fa12ceaf93cf603ea2a28be7a32223ff29cccdab21705ac0cd24866f9bfc7.

Candidate was moved from the permitted temporary root into the ignored project
.loop/development directory because apply_patch rejected writes outside the project.
This is supervised isolated development, not an autonomous Loop session or gate.
Source/test text in the delivery tree remains identical to the baseline; existing
ignored Python bytecode is outside that comparison. No existing user edits were
reset, deleted or published over. Original QA logs were only appended.

## Candidate changes

See ADR 030 for the frozen compatibility decision. Relative paths below are inside
the candidate, not the delivery product tree:

| File | Change |
| --- | --- |
| src/liveclip/domain/semantic_validation.py | New explicit legacy/current identity |
| src/liveclip/application/pipeline.py | v8 configuration, exact v2–v7 adaptation |
| src/liveclip/pipeline/semantic_profiles.py | Boundary consistency, retained duplicate representatives, available-error preflight |
| src/liveclip/pipeline/semantic_cache.py | Affected-stage cache identity helper |
| src/liveclip/pipeline/stage_handlers.py | Persisted contract dispatch and request/audit identity |
| src/liveclip/providers/llm/structured.py | Immutable repair context, SDK raw business JSON preservation |
| tests/unit/test_semantic_profiles.py | Contradictions, cycles, representatives, SDK single repair and cache read/write |
| tests/unit/test_semantic_validation_contract.py | v7 mini preservation, v8 tamper rejection, legacy dispatch |
| tests/unit/test_pipeline_repository.py | Exact historical fixtures exclude v8 field |
| tests/unit/test_semantic_global_context_budget.py | Exact historical fixtures exclude v8 field |

No historical wire Schema, Prompt, ASR, renderer, database migration, dependency,
model setting, Loop gate or permission configuration was changed.

## Actual evidence

Commands and their exact candidate cwd are append-only in qa/pipeline.jsonl;
correlated outcomes and failures remain in qa/test-report.md. These are developer
diagnostics, not formal Loop gate receipts.

| QA ID | Command/result |
| --- | --- |
| 20260912032032Z-a101 | Quality red regression: 11 expected failures reproduced |
| 20260912033016Z-a102 | 102 pass, 1 new fixture setup failure; subsequently fixed |
| 20260912034104Z-a103 | Expanded run: 233 pass, 4 historical fixture field errors; subsequently fixed |
| 20260912034106Z-a104 | Targeted Ruff check passed (before final minor fixes) |
| 20260912034107Z-a105 | Mypy: 3 typing errors; subsequently fixed; report correction appended |
| 20260912034205Z-a106 | Seven related unit-test files: 237 passed in 7.28s |
| 20260912034206Z-a107 | Mypy: no issues in 168 source files |
| 20260912034208Z-a108 | Existing mini-lesson integration: 1 passed, 8 deselected in 15.65s |
| 20260912035200Z-a109 | Final candidate Ruff check and format check: passed, 10 files |
| 20260912035201Z-a110 | Updated tracked status/QA whitespace check: passed |

The integration used a 125-second synthetic source, real SQLite/FFmpeg, test-only
business models, all five mini-lesson semantic stages, and one rendered MP4 with
duration >=90 seconds. It is not real-video semantic, cloud or hardware acceptance.
The SDK contract regression uses the actual installed OpenAI SDK with local
httpx.MockTransport: nested missing title plus a duplicate cycle reaches one repair;
success and failure both produce exactly two calls. No external request or billing.

## Independent review and remaining acceptance gaps

Two read-only DevelopmentSubagents audited and re-reviewed the patch. Initial P1
(nested SDK JSON loss) and concrete P2 score/identity/cache findings were addressed.
Both second reviews reported no new P0/P1. They did not independently rerun tests
and are not formal Reviewer/Tester/Gateway receipts.

Open P2 acceptance work before freezing an accepted candidate:

1. Stage-level two-sibling regression: one succeeds, one exhausts sole repair;
   preserve successful cache and prove no cache/third call for failed output.
2. Codex-specific current-contract mixed-error repair regression.
3. Extend/verify raw aggregation for all available cue/time/reference errors;
   current final domain validation remains fail-closed.
4. Full required lint/test/Web/E2E and immutable Runner/Gateway evidence.

## Formal environment blocker

Actual make loop-doctor exited 2:

    NOT READY
    - macOS Runner sandbox cannot be activated
    - profile differs from reviewed template for coder

No loop-run, global profile overwrite, wider sandbox, paid model run or publication
was attempted. Resolving these checks requires an authorized compatible host/session
and review of the existing profile difference. Do not disable checks.

## Resume

Read AGENTS, the stable-delivery plan, ADR 030 and this checkpoint. Reverify the
candidate and original worktree. Finish the three bounded P2 tests/aggregation above
inside the same isolated candidate; do not restart from HEAD or overwrite dirty files.
Then use the existing formal workflow only after Doctor is genuinely ready.
Do not advance to SD-1B or claim performance/real-content acceptance yet.

Reproducible offline command (no product publication or paid calls):

    cd /Users/junhuaxu/Workspace/AGI/liveclip-ai-v2/.loop/development/sd1a-20260912/candidate
    PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 /Users/junhuaxu/Workspace/AGI/liveclip-ai-v2/.venv/bin/python -m pytest -q -p no:cacheprovider tests/unit/test_semantic_profiles.py tests/unit/test_semantic_validation_contract.py tests/unit/test_pipeline_repository.py tests/unit/test_structured_repair_preflight.py tests/unit/test_semantic_global.py tests/unit/test_codex_llm.py tests/unit/test_semantic_global_context_budget.py
