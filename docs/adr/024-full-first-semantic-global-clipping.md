# ADR-024: Full-first semantic global clipping

Status: accepted, 2026-08-19

## Context

Algorithm A mechanically creates rough candidates. Frozen Algorithm B v1 uses 120-second windows,
60-second steps, at most one candidate per window and overlap rejection. Experimental B v2 adds
time-neighbour clustering before a consolidation Agent. The real `8-16-3` run showed that two
partially overlapping descriptions of the same breathing explanation could escape the local
duplicate rule, while small windows also hid the complete topic map.

## Decision

The recommended algorithm is `semantic_global`:

```text
full transcript or token-bounded large-window Discovery
→ one Global Review with original evidence
→ deterministic validation and risk gates
→ Top-N ceiling
→ existing continuous FFmpeg render
```

The actual model tokenizer and configured context limit decide Full-first. Prompt and transcript,
an output reserve and a safety margin must fit the configurable 0.58 budget ratio. Oversize inputs
use 10–20 minute token-bounded windows targeting 15 minutes and overlap by maximum clip length plus
context guard. This overlap transports context only.

Discovery returns a topic map and zero or more continuous cue-ID candidates without a final score.
Global Review sees all candidates and, when possible, the full original transcript. It alone decides
semantic duplicates, containment, splitting/merging, boundaries and six-dimension scores. Python
performs no keyword discovery, overlap-ratio semantic deduplication, five-second semantic clustering,
or quota filling. It validates exact IDs and continuous 45–90 second bounds, recomputes scores,
requires `>75`, gates risk, caps Top-N and passes only valid intervals to FFmpeg.

Prompts load as base, common, stage and profile files. Discovery and Global Review have independent
hashes and caches; evaluation examples are never production input. Transcript/model output remains
untrusted, tools are disabled, and one bounded structured/domain repair is allowed.

## Consequences

- A and B v1 stay reproducible; B v2 remains explicitly experimental.
- `8-16-3` fits a simulated/configured 128K model as one 701-cue Full-first input.
- The normal successful case uses two Agent calls rather than one call per minute.
- Global judgment improves but a large single response remains model-sensitive; failures are explicit
  and auditable instead of silently dropping candidates.
- Phase one remains a single source interval; discontinuous montage is deferred.
