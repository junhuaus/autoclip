# ADR-028: Accuracy-first scored-candidate Global Review

Status: accepted for implementation; fresh real-model acceptance pending

Date: 2026-09-04

## Context

Two fresh `8-30.ts` runs used an identical pinned local MLX transcript: 78 chunks, 3,159 segments and
canonical time/text SHA-256
`f882915ca8fac667a1c238cffb04337933a42b5224f6afe09b6d7f0b54f90da2`. Their immutable Pipeline
configuration and v1 Global Review Prompt also matched. One review retained 13 valid clips; the next
retained seven. All seven omitted accepted topics were still present in the newer Discovery output, so
ASR and Discovery recall did not explain the loss.

The failing review assigned 34 Discovery candidates to only two `no_general_value` groups. One group
contained the response Schema maximum of 30 candidate IDs. v1 required every candidate to have a
disposition but did not require an individual score before a grouped rejection. The final model could
therefore remove most of the portfolio with one broad assertion that Python had no score evidence to
challenge. Separately, the completed three-configuration benchmark ranked Sol High above Sol Medium
and Terra Medium for this editorial task. The user explicitly prioritizes quality and repeatability over
elapsed time.

## Decision

Add `semantic_global_v2` as the Global Review contract for new Full-first and Windowed runs. Preserve
the v1 loader, Prompt and Schema unchanged for historical PipelineRun and provider-cache replay.

V2 adds one compact `candidate_assessments` record for every Discovery candidate. The dynamic response
Schema fixes that array to the exact candidate count, just as coverage decisions are fixed to the exact
eligible-topic count. Each record carries the existing six score dimensions and one disposition:

- `advance` points to a retained `keep` clip that references the candidate; both assessment and result
  clip must pass the strict score threshold.
- `duplicate` independently records the candidate and points to a retained representative that
  references it. Semantic duplication is still an Agent judgment, not an overlap rule.
- `reject` has no result clip and must have structured rejection audit. `no_general_value` is invalid
  when the candidate's own score is above the strict threshold.

Full verbose clip records are valid only for retained results; rejected candidates use scorecards plus
existing grouped audit data. Provider preflight applies these mappings to raw JSON before the single
repair, and stage validation repeats them after parsing. Python validates model-authored evidence but
does not assign semantic scores, upgrade a rejection or force a clip count.

New runs default the editor model to `gpt-5.6-sol`. Codex Discovery and boundary work remains at medium
reasoning, while only v2 Global Review uses high reasoning and the existing 600-second timeout floor.
Model, Prompt hash, response Schema and effective reasoning remain part of immutable run/cache/call
evidence. The accepted 13-clip `8-30.ts` portfolio is checked in as a golden evaluation reference; it is
not embedded in production behavior.

## Consequences

- Global Review output grows by one small record per candidate, but rejected verbose clip records are
  removed. The two retained real `8-30.ts` inputs still fit the configured 74,240-token request budget:
  39 candidates at 74,000 tokens with a 10-second extra guard, and 41 candidates at 74,117 tokens with
  zero extra guard.
- A model can still make a poor individual semantic judgment. The contract makes omissions and broad
  rejection shortcuts observable and repairable; it does not promise byte-identical generative output.
- Sol/high final review is slower and may consume more inference, which is accepted because the user
  selected accuracy and stability over speed.
- A fresh ordinary-Terminal run is required before claiming improved real-model recall, repeatability or
  a new 13-clip Delivery. Media quality and package contents must then be inspected through the existing
  deterministic gates.
