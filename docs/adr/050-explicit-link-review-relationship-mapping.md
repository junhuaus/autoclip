# ADR 050: Explicit Link Review relationship mapping

Date: 2026-09-15. Status: proposed for formal SD-6B acceptance.

## Context

Mini attempt 2 used a newly frozen 64-launch/25-minute budget after read-only
analysis proved that the earlier eight-launch estimate could not cover its 22
initial Link Reviews. The new attempt did not hit either limit. It stopped at
9/64 launches because one Link Review remained schema-invalid after its single
repair.

The Agent judged the fragments as not sharing both the same topic and central
objective, but returned linking relationship `next_step_same_lesson`. Repair
changed one boolean and retained that linking enum, so the deterministic
validator rejected it again with `link relationship contradicts
same-topic/objective decision`. The stage Prompt currently lists all seven
relationship values and separately states the two-boolean join rule, but does
not state the required truth-table mapping. The generic repair Prompt says to
preserve semantic decisions without identifying which redundant field to
correct when these values conflict.

## Decision

Make the existing contract explicit in the Prompt; do not weaken or change the
validator. The four linking values `continuation`, `supporting_example`,
`next_step_same_lesson` and `summary_same_lesson` are valid only when both
`same_topic` and `same_central_objective` are true. If either boolean is false,
the relationship must be one of `adjacent_but_independent`, `topic_switch` or
`uncertain`.

For the specific contradiction validation error, the repair Prompt preserves
the two boolean judgments and changes only `relationship` to a value in the
matching set. This treats the booleans as the Agent's semantic decision and the
relationship as its required structured classification. Python does not infer
or normalize model output.

The Prompt content hash changes and therefore creates a new immutable Pipeline
configuration identity while retaining the existing versioned wire schema.
Historical runs keep their recorded hash and cannot silently reuse output
under the new Prompt.

## Consequences

The correction can reduce a repeated structural failure without adding calls,
repairs, retries or model authority. It changes no Link Review scheduling,
candidate quality rules, scoring, rendering, Codex security profile, Runner or
developer control plane.

Acceptance requires a fresh isolated sole Coder, read-only assurance roles,
fixed Runner lint/e2e/full-test from one sealed identity, Gateway PASS,
independent audit and exact-path CAS publication. Mini real success remains a
separate guarded post-publication result; the failed attempts and counters are
never reset or relabelled.
