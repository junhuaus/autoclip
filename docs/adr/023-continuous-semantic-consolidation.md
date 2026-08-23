# ADR-023: Continuous semantic consolidation for Algorithm B

Status: Superseded as the default by ADR-024; retained as `b_v2_experimental`

Date: 2026-08-19

## Context

Algorithm B v1 independently evaluates overlapping transcript windows. Its interval-overlap filter
removes only strong duplicates. On the real `8-16-3.ts` run, “唱歌吸气：小腹要往外撑”
(`15:32.500–15:50.570`) and “唱歌时腹部该往哪边动？”
(`15:43.670–16:40.950`) overlapped by 6.9 seconds but covered only 38.2% of the shorter proposal,
so both survived even though they form one continuous viewer topic. Increasing a mechanical overlap
threshold cannot reliably distinguish that case from two different questions discussed together.

The user requires phase one to consolidate only continuous source material, prefer clips around one
minute, enforce a default hard maximum of 90 seconds, and allow both durations to be adjusted. A,
Algorithm B v1, and completed real-run evidence must remain unchanged.

## Decision

New Algorithm B runs use immutable config schema v4 and two separately versioned, hashed Skills:

1. `semantic_window_v2` discovers at most one viewer-valuable continuous proposal in each
   timestamped transcript window. For target `T` and hard maximum `M`, Python supplies `T+M`
   evidence at stride `T`. Defaults are `T=60s` and `M=90s`.
2. Python filters proposals using the existing strict `>75` default threshold and transcript/duration
   evidence. It groups only overlapping or at-most-five-second-adjacent proposals whose combined
   evidence remains bounded by `T+M`.
3. `semantic_continuous_v1` decides whether a group is one continuous topic, redundant alternatives,
   genuinely separate viewer questions, or no valuable result. A merge/reduction is newly bounded
   and newly scored; old discovery scores are not inherited. `keep_separate` retains the originals.
4. Python validates the result and maps the consolidated EditPlan to an existing persisted analysis
   window. It never joins non-contiguous ranges, invents topic identity, or pads Top-N.

Config v3 and `semantic_window_v1` remain the exact Algorithm B v1 contract. Config v2 remains the
historical Algorithm A contract. Their original payload fingerprints are validated before in-memory
adaptation; stored snapshots are not mutated.

## Consequences

- The adjacent-window duplicate is addressed by semantic judgment instead of a single overlap ratio.
- Discovery/scoring guidance and consolidation guidance can be upgraded independently.
- Current B defaults analyze 150 seconds every 60 seconds, increasing bounded Agent work compared
  with B v1's 120/60 schedule only in evidence length, not call count per hour. Consolidation adds a
  call only for a temporal conflict group.
- A valid B run may still produce zero clips. Provider failure, invalid bounds, score ≤ threshold or
  no-value output is discarded without falling back to A.
- Discontinuous montage is explicitly deferred to a later phase because it needs a different media,
  caption, provenance and viewer-continuity contract.
