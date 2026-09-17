# ADR 030: Version semantic validation separately from frozen model wire formats

Status: accepted for isolated SD-1A implementation; not published to product tree.
Date: 2026-09-11 PDT.

## Context

V4 Boundary output can contain contradictory explicit quality facts and flags;
Global duplicate references can form cycles or point at rejected representatives.
Adding validators directly to historical Pydantic wire models would break immutable
Run/cache loading. The dirty delivery worktree must also remain protected.

## Decision

Introduce PipelineRunConfig v8 with a fingerprint-bound semantic_validation_contract:

| Input configuration | Loaded identity | Validation and cache behavior |
| --- | --- | --- |
| Exact fingerprinted v2–v7 | In-memory v8, semantic-v4-validation-v1 | Preserve historical business semantics and keys |
| New v8 | semantic-v4-quality-v2 | Strong Boundary/Global validation and distinct keys |
| Incomplete, unknown, tampered snapshot | Reject | No inferred identity or fallback |

Freeze v7 as a separate loader. Verify its original field set and fingerprint
before adaptation. Preserve v7 mini Profile, durations and all five Prompt hashes.
Do not modify historical stored snapshots, Prompt files, JSON Schemas or Deliveries.

Use a pure domain contract definition; application configuration owns dispatch.
Entry points do not implement quality rules. Pipeline Boundary and final Global
validators compare explicit model facts without interpreting transcript text or
inserting missing semantic flags. Model-authorized duplicate targets must be direct,
retained representatives before Top-N; manual/blocked/Top-N-excluded retained
representatives are valid, quality/content/score-rejected representatives are not.

Only affected V4 Boundary/Global requests add the new identity to payload and cache
model settings. Discovery/Link/Topic Chain keys and legacy requests remain unchanged.
Keep the existing sole semantic repair budget. Preserve the immutable request and
aggregate available schema, quality, identity, provenance and duplicate errors.
Compute score totals only from complete, valid scorecards.

For the new OpenAI path, capture only the actual sole business output_text using
with_raw_response before SDK parsing. Nested Schema errors must not lose that JSON.
Do not persist headers, credentials, reasoning or the whole HTTP response.
The strict output model, disabled tools and store=False remain unchanged.
Verified against the installed SDK and the
[official Python SDK raw-response interface](https://developers.openai.com/api/reference/python#accessing-raw-response-data-eg-headers).

## Consequences and limits

Historical replay does not silently acquire new semantic gates. New validation
requires a new explicit configuration/generation; no bulk migration is authorized.
Wire compatibility and output quality are distinct contracts.

Preflight is not a substitute for final typed domain validation. The September 12
continuation adds shared local cue/time/reference checks, current-contract Global
interruption references, authoritative duration Profile selection and partial-JSON
guards. Stage/Codex failure-cache and sole-repair regressions are implemented.
See the current SD-1A verification checkpoint for actual results. Failures still
fail closed; missing semantic decisions are never inferred.

The isolated implementation is not an accepted Loop candidate. The historical
host Runner sandbox and Coder profile checks were repaired on September 12, but
formal run 20260912T160102Z-12b7777d stopped after both fresh Planners could not
use read-only tools under the unchanged code-mode disable policy. No Coder or
Runner/Gateway evidence exists for that attempt. Do not publish it or reuse
diagnostic PASS records as formal Runner/Gateway evidence.
