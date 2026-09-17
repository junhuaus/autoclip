# SD-6B requirement: explicit Link Review relationship consistency

## User-visible outcome

Mini-lesson Link Review and its one allowed repair receive an explicit mapping
between `same_topic`, `same_central_objective` and `relationship`. The current
strict validator remains authoritative. A response that judges either boolean
false is guided to a non-linking enum rather than repeatedly returning a
linking enum and exhausting the run for a preventable structural contradiction.

## Preserved evidence

Real QA `20260915T045700Z-mn02` is FAIL and must remain unchanged. Run
`9dea3e8250854d91a3f9476fb55c70a3` used 9/64 Codex launches, created no
Delivery and stopped at `CANDIDATES_PROVIDER_OUTPUT_INVALID`. Its failed Link
Review initial output had `same_topic=true`, `same_central_objective=false`,
`relationship=next_step_same_lesson`; repair had both booleans false and kept
that linking relationship. Both failed with `link relationship contradicts
same-topic/objective decision`. The immutable summary and outcome hash are in
`docs/verification/sd6-mini-attempt2-failure.json`.

## Exact Coder scope

The sole isolated Coder may edit only:

- `src/liveclip/clipping_skills/semantic_topic_chain_v1/stages/link_review.md`
- `src/liveclip/clipping_skills/semantic_topic_chain_v1/repair.md`
- `tests/unit/test_semantic_lineage_prompts.py`

All other files are read-only. Only the recorded Coder session may be resumed;
never use `--last`. Planner, Reviewer, Tester and Gateway are fresh and
read-only. Runner uses only the checked-in allowlist under the deny-default
macOS sandbox.

## Required behavior

1. The Link Review stage Prompt must state that the linking values are exactly
   `continuation`, `supporting_example`, `next_step_same_lesson` and
   `summary_same_lesson`, and they are permitted only when both booleans are
   true.
2. It must state that if either boolean is false, `relationship` is exactly one
   of `adjacent_but_independent`, `topic_switch` or `uncertain`.
3. For the named relationship/boolean contradiction, the repair Prompt must
   preserve the two boolean semantic judgments and correct only the redundant
   relationship classification to the matching set. It must not invite a new
   semantic decision, whole-stage replay or changes to unrelated objects.
4. Add a direct prompt-contract regression for both `general` and
   `vocal_coach_live` mini profiles. It must prove the composed initial Prompt
   contains every exact enum and both truth-table branches, the repair Prompt
   contains the narrow correction rule, and the resulting Prompt hash differs
   from historical Link Review hash
   `12881e9817b1fe45d86607b81d629966a0e948bf8f4d3d0d701355db9b48085d`.
5. Keep `LinkReviewV4`, schemas, semantic scheduling, cache implementation,
   one-repair limit, model/settings, Codex `tool-free-v3`, credentials,
   source-media handling, Runner and control-plane code unchanged. Do not add
   deterministic semantic normalization or fallback.

## Formal acceptance

Fresh Reviewer must return PASS with no unresolved P0/P1 and Tester must be
READY. Fixed Runner `make lint`, `make e2e` and `make test` must pass from one
sealed source/toolchain identity. Fresh Gateway must PASS, and deterministic
evidence must be complete, current, unmutated and correlated. Main then audits
the exact Coder session and three-path delta before atomic publication.

No formal role or Runner performs business inference. A post-publication real
mini attempt uses a new frozen guard/budget and fresh run root. Its success is
claimed only from actual Delivery plus independent artifact inspection; any
failure remains FAIL without automatic retry or limit increase.
