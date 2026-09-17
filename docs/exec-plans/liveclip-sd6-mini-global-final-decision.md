# SD-6 mini Global Review final-decision Living ExecPlan

Prepared 2026-09-15. This plan follows `.agent/PLANS.md`, ADR051 and the SD-6 real-acceptance plan.

## Purpose / Big Picture

Global Review treats the interval delivered by Boundary Review as final for the current stage. A model
can accept a previously repaired interval with `keep` without copying the upstream repair history into
a decision that the deterministic gate rejects.

## Scope and evidence

Attempt 5 is preserved by `docs/verification/sd6-mini-attempt5-content-rejection.json`. Its second
candidate retained the exact repaired Boundary interval, scored 86 and then hit `content_keep_gate`
because Global Review returned `repair_boundary`. The formal slice changes only the current Global
Review Prompt and its direct prompt-contract test. Historical schemas/runtime behavior stay immutable.

The stage resource is
`src/liveclip/clipping_skills/semantic_topic_chain_v1/stages/global_review.md`;
`src/liveclip/clipping_skills/semantic_topic_chain_v1/__init__.py` composes it
with the selected Profile and Clip Profile. The only test in scope is
`tests/unit/test_semantic_lineage_prompts.py`. The first isolated candidate was
`.loop/development/sd6-mini-global-final-decision/candidate`; formal run
`20260915T215821Z-d1ef69c8` is terminal BLOCKED. Successor run
`20260915T231518Z-3cc4a9a1` is also terminal BLOCKED after its trusted clone
rewrote copied tool shebangs from the wrong source root. Successor 2 formal run
`20260915T233253Z-b58e24b3` is terminal BLOCKED after all Runner gates passed
but Gateway required an authenticated pre-change negative baseline. Successor
3 formal run `20260916T203659Z-c84d35d7` is terminal BLOCKED after one existing
Web test failed during a host-load spike. Successor 4 formal run
`20260916T213742Z-56deb953` is terminal BLOCKED after six asynchronous Web
failures across five files. A focused five-file rerun reproduced one loading
failure. Successor 5 is
`.loop/development/sd6-mini-global-final-decision-successor5/candidate` and owns
the current acceptance evidence. Main owns this plan, ADR051, STATUS,
independent audit and publication.

Runtime validators, schemas, Python selection logic, scores, duration limits,
quality/risk gates, model settings, retries, guards, dependencies and the Loop
control plane are explicit non-goals. The correction does not promise that a
model will keep a candidate or that a mini Delivery will exist.

## Progress

- [x] Preserve attempts 5 and 6 with matching append-only QA and read-only failure audits.
- [x] Isolate the final-decision Prompt contradiction without changing model output or gates.
- [x] Clone current delivery source into a fresh isolated candidate without source media/model data.
- [x] Preserve first formal run `20260915T215821Z-d1ef69c8` as terminal BLOCKED after lint FAIL, E2E PASS and full-test environment timeout.
- [x] Preserve successor 1 `20260915T231518Z-3cc4a9a1` as terminal BLOCKED after the cloned toolchain pointed outside its Runner sandbox; no product assertion failed and nothing was published.
- [x] Clone the sealed successor-1 product source to successor 2 with candidate-local tool shebangs and a role-visible hash-indexed handoff.
- [x] Preserve successor 2 `20260915T233253Z-b58e24b3` as terminal BLOCKED after fresh roles and all three Runner gates passed but Gateway required authenticated negative-baseline evidence.
- [x] Prove the identical four clauses absent in both exact pre-change compositions and present in both accepted compositions, correlate the proof to successor-2 Runner PASS, and record it in append-only QA.
- [x] Clone the sealed successor-2 product source to successor 3 and freeze the proof, raw baseline, script, QA, parent artifacts and logs in a 22-file role-visible handoff.
- [x] Preserve successor 3 `20260916T203659Z-c84d35d7` as terminal BLOCKED after lint/E2E and 2,471 Python tests passed but one out-of-scope Web test failed while the page remained in loading state.
- [x] Reproduce that exact Web test against byte-identical successor-4 code: focused QA `20260916T213452Z-wdiag` passed 1/1 without modifying frontend code or overriding the parent FAIL.
- [x] Clone and freeze successor 4 with the parent failure, focused diagnostic, inherited negative baseline and fresh candidate-local toolchain.
- [x] Preserve successor 4 `20260916T213742Z-56deb953` as terminal BLOCKED after lint/E2E and 2,471 Python tests passed but six asynchronous Web tests failed under sustained host load.
- [x] Reproduce the affected surface against identical sealed bytes: focused QA `20260916T222802Z-wdg5` passed 47/48 and reproduced `review-flow` waiting on loading state.
- [x] Clone and freeze successor 5 with a central bounded Web-test timing repair authorized in addition to the two Global Prompt paths.
- [x] Complete successor-5 fresh Planner, sole Coder, Reviewer, Tester, fixed Runner and Gateway roles.
- [x] Independently audit formal DONE and publish only its authorized paths by CAS.
- [x] Pass focused postpublication prompt-contract and affected-Web regressions.
- [x] Update SD-6 plans and STATUS with accepted engineering and real-run limitations.

## Commands and expected observations

From successor 5, the trusted outer process initializes a fresh run from
`docs/requirements/sd6-mini-global-final-decision-successor5.md`, then resumes
only that explicit run ID. Planner, Reviewer, Tester and Gateway are fresh
read-only sessions. Exactly one newly recorded Coder may write or resume;
`--last` is never used. The fixed Runner executes allowlist IDs `lint`, `e2e`
and `test` from a sealed assurance source under the deny-default macOS
sandbox. A Runner failure routes back to that exact Coder and is retained in
append-only candidate QA.

After DONE, Main runs the independent read-only audit at
the successor-5 `verify_done.py`, creates and checks a compare-and-swap
publication preflight, atomically publishes only the accepted authorized
paths, appends only the accepted final Runner QA and runs focused prompt and
Web timing regressions in the delivery worktree. A later real mini probe
requires its own frozen guard, plan, QA request and hardware preflight.

## Acceptance and recovery

Both composed mini-profile Prompts must contain the final-boundary rule, forbid copying or returning
`repair_boundary`, and preserve all existing editorial gates. Formal lint/e2e/full-test and semantic
roles must agree on one sealed source. A failed formal run remains unpublished; resume only the exact
recorded Coder session when the state machine requests code repair. Never use `--last`, widen Runner
argv, reset real-run guards, or turn model output into a command.

The first Runner lint result is intentionally preserved as FAIL: six `RUF001`
findings came from literal full-width commas in the new Python assertions, and
one assertion line exceeded 100 characters. The product Prompt itself was not
the lint failure. E2E passed. Full test collected 2,471 items but reached only
24 percent in 2,450.001 seconds under host load averages above 60; Runner sent
SIGTERM and correctly classified this as environment ERROR. Formal run
`20260915T215821Z-d1ef69c8` is terminal BLOCKED before Coder repair or Gateway.
Its exact source, three QA results and failure log stay immutable. The next
legal action was a fresh successor cloned from assurance source fingerprint
`a0dec4913fece8b40478f2b5710925629d5c34597f5c25d883bb038679fa8fd4`,
with the lint and timeout evidence made role-visible. The successor gets a new
Coder session; the blocked run is never resumed or published.

That first successor repaired the regression lint without changing the Prompt
SHA, and its fresh Reviewer returned PASS with zero findings. Its three fixed
Runner commands failed before product execution because the trusted cloner
rewrote copied `.venv` shebangs as though the assurance snapshot were their
source. The sandbox correctly denied the resulting Main-owned interpreter.
Run `20260915T231518Z-3cc4a9a1` is therefore terminal BLOCKED and unpublished;
its product assurance fingerprint
`bdc9b93fb55db73c336e7c78e8d7d5fdefeef89453f53bbd02679004344a9569`
became successor 2's product source. Successor 2 rebuilds the toolchain from
Main and rewrites embedded paths from the actual Main root into the isolated
candidate. Its freeze verified candidate-local `mypy` and `pytest` shebangs,
2,260 source paths, no source media/model data and the complete two-parent
handoff.

Successor 2 then produced clean formal engineering evidence on one sealed
source: Planner READY, sole Coder no-op, Reviewer PASS with zero findings,
Tester READY, lint PASS in 39.640 seconds, E2E PASS in 250.665 seconds, and full
test PASS in 1,604.684 seconds with 2,471 Python and 80 Web tests plus required
browser/media checks. Gateway still returned FAIL because the role-visible
bundle proved only current-source success, not the same regression's failure
against the exact original Prompt for both profiles. Run
`20260915T233253Z-b58e24b3` is terminal BLOCKED and unpublished. Trusted Main
therefore froze the pre-publication Prompt and accepted assurance source,
proved `[false,false,false,false]` to `[true,true,true,true]` for both profiles,
correlated that evidence to the three Runner PASS IDs, recorded QA
`20260916T203108Z-gneg`, and placed the raw resource, verifier, receipt, QA and
parent evidence in successor 3 before formal initialization.

Successor 3's fresh roles all accepted the unchanged Prompt and negative
baseline. Lint and E2E passed. Its full Runner then passed all 2,471 Python
tests, including all 18 semantic Prompt cases, but Web finished 79/80: the
atomic batch-selection test could not find `编辑详情` while its rendered workspace
still showed loading states. Host load had risen above 180. The exact Coder
resumed, made zero changes and returned BLOCKED because the frontend test was
outside the authorized paths. Run `20260916T203659Z-c84d35d7` is terminal
BLOCKED before Gateway and remains unpublished. Trusted Main cloned identical
product bytes to successor 4 and ran only that exact failed test; QA
`20260916T213452Z-wdiag` passed 1/1 in 1.48 seconds. This diagnostic does not
replace fresh full Runner coverage and does not change the parent FAIL.

Successor 4 again accepted the Prompt with fresh semantic roles. Lint and E2E
passed, and all 2,471 Python tests passed. Web finished 74/80: six tests across
five files either exhausted Vitest's default five-second test limit or could
not find UI that was still waiting for mocked requests. The previously failed
atomic batch-selection test passed. The exact Coder resumed once, made zero
changes and returned BLOCKED because frontend test infrastructure was outside
the two authorized paths. Run `20260916T213742Z-56deb953` is terminal BLOCKED
before Gateway and remains unpublished. Focused QA `20260916T222802Z-wdg5`
then ran all five affected files and reproduced one `review-flow` loading
failure while 47 other tests passed. Successor 5 therefore authorizes only a
central bounded Testing Library wait and Vitest test timeout repair, while
retaining the original Prompt and regression scope.

## Decision Log

- 2026-09-15: clarify the Prompt instead of widening the validator. The
  validator already enforces the desired final-stage contract and correctly
  rejected the contradictory output.
- 2026-09-15: retain `repair_boundary` in historical schemas for replay
  compatibility, but prohibit it in the current Global Review instructions.
- 2026-09-15: preserve all first-cycle Runner results even though lint had
  already failed; the fixed Runner evidence must remain complete and ordered.
- 2026-09-15: classify the 2,450-second full-test termination as an environment
  failure, not a code assertion failure. The log shows steady passing progress
  through 24 percent and no failed test; a successor is required because the
  state machine correctly made an ERROR terminal.
- 2026-09-15: preserve successor 1 after the trusted clone's source-root error.
  Do not relabel its Runner failures as product failures and do not alter the
  sandbox. Rebuild successor 2's local toolchain from Main with the correct
  embedded-path rewrite and prove candidate-local shebangs before formal use.
- 2026-09-16: preserve successor 2 despite complete deterministic PASS because
  semantic Gateway lacked the authenticated pre-change negative baseline.
  Supply that exact missing evidence to a fresh successor; never reinterpret
  the Gateway failure or publish the otherwise clean candidate.
- 2026-09-16: preserve successor 3 after one existing Web test failed under a
  host-load spike. Keep the two-path Coder scope; prove the exact failure is
  nonreproducible on a byte-identical fresh successor, then require all formal
  gates again instead of weakening the test or reusing the old Runner PASS.
- 2026-09-16: preserve successor 4 after six asynchronous Web failures. The
  five-file diagnostic reproduced the same loading-state class, so authorize a
  bounded central test-environment timing repair in successor 5; keep all test
  assertions and production UI unchanged.

## Risks and mitigations

A Prompt can still produce invalid or editorially unsafe output. Existing
Schema repair and deterministic gates remain authoritative, and later real
evidence is reported with its true negative or positive status. Publication
uses exact source fingerprints, path-set comparison, target-byte CAS, backups
and atomic replacement so unrelated delivery-worktree changes are preserved.

## Outcomes and Retrospective

The first five formal runs are terminal BLOCKED and unpublished. Successor 5
`20260916T223427Z-6f412cde` is DONE. Sole isolated Coder
`01a0ac5f-ece1-7b12-96f5-75a0647fb631` changed only its authorized paths.
Fresh Reviewer and Gateway passed with zero unresolved findings. Fixed Runner
lint `20260916T224439Z-9f37`, E2E `20260916T224528Z-7a94` and full test
`20260916T225003Z-7ebc` passed against source fingerprint
`1752f61cb22243f7e96598b1950663160c1aecb27ab94f9d041c2fee278ebc21`.

Main audit `20260916T232104Z-gva5` and publication preflight
`20260916T232133Z-gvp5` passed. Atomic CAS publication
`20260916T232158Z-gpub5` published exactly the accepted paths. The first QA
append request correctly failed while another request was pending; successor
append `20260916T232245Z-gqa6` passed without rewriting history.
Postpublication Prompt QA passed 18/18 and all five affected Web files passed
48/48. Attempts 5 and 6 remain immutable negative evidence. Attempt 7 is
separately frozen and unconsumed; its interrupted hardware preflight is not a
real-model or Delivery result.

## Cross-Mac resume check, 2026-09-17 03:32 UTC

QA `20260917T033200Z-a7ready` reconciled all 1,107 inherited request/report
pairs and recorded the current prerequisite block. This clean `main` checkout
at `6a3b949b2dd852fc6cf11ec648620bd569ddb8de` has no `input/8-30.ts`, no
`data/models/whisper-large-v3-mlx`, no `.venv/bin/python` and no `.loop`.
Neither FFmpeg nor ffprobe is on PATH. The process reports Darwin/x86_64;
`hw.optional.arm64` and `sysctl.proc_translated` queries were denied, so this
check does not establish physical host architecture or Metal availability.
See [the prerequisite receipt](../verification/sd6-mini-attempt7-resume-blocked.json).

Attempt 7 remains unconsumed. No guard, run database or Delivery was created,
and no model or credential was accessed. Setup, doctor and full hardware
preflight were not run: installation cannot restore the missing user media,
and supported hardware is unverified. Product code and control-plane policy
remain unchanged; this documentation check is not deterministic Runner acceptance.

Next task: restore the exact source and pinned model on a supported Apple
Silicon host, install the documented local toolchain, then reconstruct and
freeze attempt-7 controls and register/pass its complete hardware preflight
before the single 64-launch/25-minute attempt. Preserve the prior freeze and
interrupted preflight as historical evidence. Do not mark SD-6 complete.
