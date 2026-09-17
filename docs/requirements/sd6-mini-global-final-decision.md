# SD-6 mini Global Review final-decision clarification

## Problem

Real mini attempt 5 (`85e067ff90e740cc9dfe1afb303e4cb3`) supplied Global Review with a Boundary
Review interval already repaired to cues 88--126. Global Review kept the same boundaries and scored the
candidate 86, but copied `content_decision=repair_boundary`; deterministic validation then rejected it
with `content_keep_gate`. The current Prompt describes a second repair even though the current validator
requires Global Review to score the exact supplied Boundary interval and advances only `keep`.

## Authorized scope

The sole isolated Coder may change exactly:

- `src/liveclip/clipping_skills/semantic_topic_chain_v1/stages/global_review.md`
- `tests/unit/test_semantic_lineage_prompts.py`

No validator, Schema, Python runtime, model, reasoning, retry, budget, selection, risk, quality, duration,
Runner, control-plane or dependency change is allowed.

## Required behavior

The composed Global Review instructions for both `general` and `vocal_coach_live` mini profiles must say:

1. the interval in `boundary_reviews` is the already resolved final Boundary interval for this stage;
2. Global Review decides that supplied interval independently and must not copy an upstream historical
   `repair_boundary` decision;
3. return `keep` when that exact supplied interval is acceptable, otherwise `drop`;
4. do not return `repair_boundary` or propose a second boundary repair in current Global Review.

Keep existing score, quality, risk, publish-status, evidence, duplicate and Top-N rules exact. Add a
direct composed-prompt regression for both profiles and retain the existing hash-participation test.

## Acceptance

Fresh roles must produce Reviewer PASS with no P0/P1, Tester READY, fixed Runner `lint`, `e2e` and `test`
PASS on one sealed source/toolchain, and Gateway PASS. Only the two authorized files may differ. Main
independently audits the exact recorded Coder session, source fingerprint and QA evidence before any
compare-and-swap publication. No real-model success is implied by the engineering gate.
