# `8-16-3` Full-first semantic-global verification

Date: 2026-08-19/20 PDT

## Outcome

`semantic_global` is implemented as a new path; A, frozen B v1 and
`b_v2_experimental` remain separately selectable. The 701-cue fixture
`tests/fixtures/8-16-3-full-transcript.txt` has SHA-256
`d51cd5535897c039338698d0342e25c9bc50779132da54539f118d29377c2a0a`, ends at
4,659.820 seconds and selects `full_context` with a 128K model context and 0.58 budget.
The final compact cue transport estimate is 36,298 transcript tokens. It is not divided into 78
minute windows.

The production sequence is:

```text
full transcript Discovery (zero to many, no score)
→ full transcript + topic map + all candidates Global Review
→ cue/time/score/risk/Top-N validation
→ optional existing FFmpeg path
```

The real evaluation used the direct transcript/no-render command, so this report claims a
validated clipping plan, not newly rendered video or a new Delivery package.

## Problems found in the previous implementation

- A mechanically generated 40 rough candidates, forced Top-N and admitted two selected scores at
  or below 75 plus two intervals overlapping the 00:00–05:30 negative region.
- B v1 used 78 local windows, at most one proposal per window and 79 Agent calls. Its 55% interval
  overlap rule retained both breathing half-answers.
- B v2's five-second/overlap grouping used time transport as a precursor to semantic identity. It is
  preserved for experiments but is not the new default direction.
- Ordinary Pydantic JSON Schema was not accepted by the pinned Codex strict-response subset because
  every object property must be listed in `required`; the adapter now generates that restricted
  schema while runtime validation keeps the ordinary checked-in Schema authoritative.
- Semantic repair originally received the error and original transcript but not the invalid model
  output, so it could not perform a bounded correction. Repair now receives the invalid output,
  immutable source/range/runtime facts, allowed cue IDs and allowed Discovery IDs—without the full
  transcript—and retains unrelated candidates. Provider failures and validation/repair events are
  persisted without transcript text.
- The existing pipeline-output master provenance and the newer Delivery packager used different
  producer fingerprints. Branch-aware lineage validation was repaired and the focused package flow
  passes without regenerating historical media.

## Prompt and data contracts

Production loading order is stable:

1. `main.md`
2. `common_rules.md`
3. `stages/discovery.md` or `stages/global_review.md`
4. `profiles/general.md` or `profiles/vocal_coach_live.md`
5. runtime parameters and untrusted structured input

`evals/8-16-3.md` is excluded from production. The final real run used Discovery Prompt SHA-256
`c75ca043da489afccf7511770a1cc353681edbd5769a7ffad4baf25b580d5a53` and Global Review
SHA-256 `783a1f72ddf7f4f8a7041e266fb01baafe7344fb5ab81d39a18737d070d3cbbe`.

Full-first reserves 16,000 output tokens and a 1,000-token safety margin inside the 0.58 budget.
Oversize inputs alone use token-bounded 10–20 minute windows targeting 15 minutes. Their default
120-second overlap is `90-second maximum clip + 30-second context guard`; it only transports context.
Every window may return multiple candidates with global cue IDs. Python does not group, merge, split
or deduplicate candidates by time.

Discovery returns topic units plus `parent_topic`, `viewer_promise`, `hook`, `payoff`, evidence cue IDs,
boundaries and risks; it has no 0–100 score. Global Review receives the original full transcript in
Full-first mode and owns omission recovery, semantic containment/duplicate decisions, re-bounding and
six-part scoring. Python maps cue boundaries back to exact milliseconds, accepts only one continuous
45–90 second range, recomputes the total, enforces `score > 75`, applies the typed risk severity gate,
and stably truncates rather than fills Top-N. High medical, absolute, commercial and music-rights
risks are manual; a low-severity general vocal-health reminder is not misclassified as a diagnosis.

## Deterministic regression

The mock end-to-end regression makes exactly two calls and writes
`discovery-raw.json`, `global-review-raw.json`, `final-validated.json` and
`run-metadata.json`. Unit coverage proves zero/multiple Discovery candidates, exact prompt order/hash,
128K Full-first choice, fallback overlap and global IDs, exact 45.000/90.000 boundaries, rejection of
44.999/90.001/reversed/unknown IDs, score recomputation, 75 rejection/76 acceptance, risk propagation,
stable non-padding Top-N, stage cache identity and one breathing result at cue 179–193
(932.500–1,000.950 seconds). The mock Pipeline integration covers transcript through persisted
no-render EditPlans without calling A/B candidate or time-cluster paths.

## M21 shortest-boundary and source-fidelity evidence (supersedes M20 for current quality)

Accepted result:

- directory: `data/evaluations/8-16-3-semantic-global-boundary-r20-global-only-sol-high-2026-08-20`
- provider/model: tool-disabled Codex / `gpt-5.6-sol`, explicit high reasoning
- context: validated full-context Discovery reuse plus full-context Global Review
- Discovery provenance: one prior compatible real call, 37 topics, 11 candidates, 51,971 input and
  19,654 output tokens; reuse is guarded by source/config/profile/model/context/reasoning/Prompt hash
- accepted rerun calls: two — Global initial plus one bounded repair; 107,907 input and 20,930 output
  tokens; 455.153 seconds
- final clips: 3 automatic + 7 manual; raw rejected candidate groups: 2; coverage decisions: 22
- fixture-only strong anchors touched: 9/12
- invalid cue/time/duration intervals, automatic scores `<=75`, automatic high-risk medical clips,
  unfinished kept clips, unsupported title reframes and duplicate risk types: all 0

The two priority boundaries are now exact: the complete breathing direction comparison is one
manual-review clip at 00:15:32.500–00:16:40.950 (68.45 seconds), and the four-step framework is one
manual-review clip at 00:20:06.950–00:21:35.440 (88.49 seconds). The historical 00:12 sales-padded
candidate, 01:12:55 welcome-padded candidate, unfinished “但是” ending and title that recast a medical
claim as cautionary education are absent. Every retained clip reports a source closing quote, a
complete ending, first payoff at its end cue, shortest-complete boundary and faithful source stance.
The breathing clip remains manual because unavoidable internal live CTA cannot be jump-cut under the
single-continuous-interval rule.

The evaluation artifact deliberately exposes exact boundaries plus the full transcript for an
independent reviewer: `evaluation-ready.md`. Its companion `semantic-acceptance.md` records all ten
times, the 9/12 anchor table, deterministic invariants and hashes. This evaluation did not invoke
FFmpeg and makes no new rendered-media claim. Final gates: `make lint`; `make test` with 805 Python,
58 Web, Mock Chrome 1/1 and isolated real API/Worker/SQLite/FFmpeg Chrome 1/1.

M20 below remains historical evidence for the input evaluation that prompted M21.

## M20 repaired real-model evidence

Final accepted run:

- directory: `data/evaluations/8-16-3-semantic-global-v2-repair-r13-sol-2026-08-19`
- provider/model: tool-disabled pinned Codex 0.146.0 / `gpt-5.6-sol`
- context: full-context Discovery and full-context Global Review; estimated Global total 67,696
  tokens against the 74,240-token 0.58 budget
- Agent calls: 3 — one Discovery, one Global Review and one bounded Global repair
- actual input/output tokens: 156,103 / 29,373
- elapsed: 543.870 seconds
- Discovery: 28 topic units and 14 candidates
- final clips: 4 automatic + 11 manual; the extra manual clip is a full-transcript recovery traced
  to source topic IDs without inventing a Discovery candidate
- fixture-only strong anchors touched: 10/12
- invalid cue/time/duration intervals: 0
- automatic scores `<=75`: 0
- `medical_diagnosis_high` automatic selections: 0
- historical 01:12:55–01:13:55 opening-noise interval retained: 0

The breathing result is a single complete version (`clip_004`, 00:15:35.000–00:17:05.000) that
contains both inhale-outward and singing/exhale-inward movement. No overlapping half-version is
retained. The four-step topic is retained as manual review (`clip_005`,
00:20:51.770–00:21:59.110) and is no longer rejected as over 90 seconds. The final late recorded
course versus one-to-one value comparison is retained at 01:16:19.130–01:17:09.700.

Raw candidate dispositions are internally consistent: 4 selected + 10 manual + 0 rejected = 14.
Final clip groups are 4 selected + 11 manual + 0 rejected because one Global recovery clip has no
Discovery candidate disposition. `global-review-agent-raw.json` preserves the exact Agent output;
`global-review-raw.json` is the deterministically validated raw review used for final assembly. The
final artifact also preserves coverage decisions, transition audit, Prompt/model metadata and any
validator notes.

The first M20 Terra rerun found only seven candidates and four anchors. A later Sol probe found 15
candidates but exposed that a single Schema repair listed missing duration boundaries without also
listing the required claimed duration. The repaired preflight now aggregates every deterministic
cross-field error in one request. Another Sol run reached eight anchors but Global fell back because
repeated absent normalization fields consumed the last budget margin. Omitting only those null keys
kept all original/normalized evidence and produced the accepted full/full result above. All failed
and superseded runs remain preserved under separate ignored evaluation directories.

## Historical M19 real-model evidence

Historical M19 final run (superseded by the M20 result above):

- directory: `data/evaluations/8-16-3-semantic-global-real-final2-2026-08-19`
- provider/model: tool-disabled pinned Codex 0.146.0 / `gpt-5.6-terra`
- input mode: `full_context`; one Discovery unit
- Agent calls: 2 (no repair)
- input/output tokens: 113,334 / 8,142
- elapsed: 155.856 seconds
- Discovery candidates: 7
- automatic selected: 2; manual review: 4
- invalid cue/time/duration intervals: 0
- selected score `<=75`: 0
- opening-noise automatic selections: 0
- health-claim automatic selections: 0
- strong reference anchors hit across automatic + manual: 4/12

The final sample was conservative and missed the breathing anchor entirely. It therefore passes every
deterministic safety gate but does **not** meet the desired real-sample semantic recall target or the
breathing-case expectation. This gap is not hidden or converted into a hard-coded result.

An earlier two-call real iteration at
`data/evaluations/8-16-3-semantic-global-real-iteration4-2026-08-19` produced 9 Discovery candidates,
4 automatic + 5 manual results, 8/12 strong-anchor hits, zero opening-noise/health/invalid/low-score
automatic selections, 113,156 input and 8,984 output tokens in 171.704 seconds. It retained only one
automatic interval overlapping the historical breathing anchor, but did not choose the preferred
179–193 union. Other recorded tuning iterations show that the current model's recall/boundary behavior
has meaningful sampling variance even though deterministic validity is stable.

This was the M19 acceptance limitation. M20 addressed it through eval-driven Prompt/model comparison,
complete repair preflight and compact lossless cue transport—not Python keywords, time clustering or
hard-coded `8-16-3` timestamps. Sampling variance remains an ordinary model-quality observation rather
than a deterministic safety failure.

One fixed-Prompt `gpt-5.6-sol` comparison was attempted at
`data/evaluations/8-16-3-semantic-global-real-sol-2026-08-19`. The provider returned
`STRUCTURED_PROVIDER_ERROR` during Discovery after 121.115 seconds, before usable token metadata or
structured content existed. `failure.json` contains the bounded call evidence. It is not counted as a
quality result and was not retried or silently replaced by Mock.

## A/B comparison

The A and B v1 values use the existing byte-identical `8-16-2.ts` and `8-16-3.ts` completed runs; neither
was rerun. “Known duplicate pairs” counts reviewed same-promise pairs, not an exhaustive automatic metric.

| Metric | A | B v1 | semantic_global final |
| --- | ---: | ---: | ---: |
| Agent calls | 40 | 79 | 3 (2 primary + 1 repair) |
| Discovery/rough qualifying candidates | 40 rough | 45 above threshold | 14 |
| Final automatic selected | 15 | 15 | 4 |
| Manual-review results | n/a | n/a | 11 |
| Known same-promise duplicate pairs | 1 | 1 | 0 |
| Invalid intervals | 0 | 0 | 0 |
| Strong anchors hit | 5 | 6 | 10 |
| Opening-noise selected | 2 | 0 | 0 |
| Medical-risk automatic selected | 0 | 0 | 0 |
| Selected score `<=75` | 2 | 0 | 0 |
| Input tokens | 363,523 | 781,930 | 156,103 |
| Output tokens | 11,529 | 17,362 | 29,373 |
| Agent/elapsed time | 391.2s summed | 617.6s summed | 543.9s elapsed |

The comparison demonstrates the call/token efficiency and deterministic safety improvement. The stronger
Sol quality run is slower in wall time and produces a larger audited structure than the earlier Terra run,
but it exceeds both historical portfolios on the fixture anchor measure without Python semantic rules.
Production model choice remains configurable; cached Discovery can be reused when only Global Review
Prompt/configuration changes.

## Modified areas

- Runtime/config/orchestration: `application/pipeline.py`, `pipeline/stage_handlers.py`,
  `pipeline/semantic_global.py`, `pipeline/semantic_cache.py`, `pipeline/srt.py` and bootstrap/settings
  integration.
- Agent contract: `clipping_skills/semantic_global_v1/` and
  `schemas/clipping/{discovery,global_review}.schema.json`.
- Providers/evaluation: `providers/llm/structured.py`, `services/semantic_evaluation.py` and CLI
  `semantic-eval`/`run` options.
- Product surfaces: API request schemas/routes and Web algorithm/profile/duration/budget controls.
- Tests/fixtures: `test_semantic_global.py`, persistent Mock integration, compatibility/config/API/Web
  regressions and the 701-cue transcript fixture.
- Documentation: README, Product Spec, Solution, ADR-023/024, Living ExecPlan, STATUS and this report.

Unrelated pre-existing selection/Delivery work in the dirty worktree was preserved; historical A/B source,
database, rendered masters and Delivery bytes were not replaced.

## Verification commands

```bash
make lint
.venv/bin/pytest -q
cd apps/web && npm test -- --run && npm run typecheck
.venv/bin/liveclip semantic-eval \
  --transcript tests/fixtures/8-16-3-full-transcript.txt \
  --output data/evaluations/8-16-3-semantic-global-mock \
  --provider mock --model-context-tokens 128000
```

Final gates: `make lint` passed, 764 Python tests passed, 58 Web tests passed, and Web typecheck passed.
