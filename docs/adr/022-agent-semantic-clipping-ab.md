# ADR-022: Add Agent semantic clipping as algorithm B

Status: accepted

Date: 2026-08-18

## Context

The existing algorithm mechanically enumerates duration-legal transcript windows, scores
surface signals, sends every rough candidate to an editor and retains a fixed Top-N. This is
reproducible, but it admitted context-dependent topics such as “老师点评学员第二节课” whose
label and local completeness did not make them useful to an unfamiliar viewer. The user wants
content value, standalone clarity and interest to determine whether a clip exists at all.

Replacing the existing algorithm would destroy reproducibility for completed Projects and make
the proposed comparison impossible. Sending a whole multi-hour transcript to one model call
would also weaken evidence bounds, recovery and cost visibility.

## Decision

Keep the current pipeline as algorithm A without changing its generation, ranking or forced
Top-N behavior. Add algorithm B as a separate immutable PipelineRun option.

For requested maximum duration `L`, B constructs timestamped transcript windows of `2L` and
advances by `L`. A versioned, hashed `semantic_window_v1` Skill asks a tool-disabled Agent to
return at most one independently understandable, transferable, interesting and evidence-faithful
interval, or a `not_meaningful` result. The Agent chooses semantic value, topic, score and exact
start/end. Python only validates configured duration, allowed window and transcript boundary
evidence, rejects degraded/no-value output and any score not strictly above the configurable
retention threshold (default 75), removes strong interval duplicates and caps the
portfolio at Top-N without padding it. Zero selected clips is a successful, auditable outcome
and the render stage completes with an empty checkpoint.

Pipeline config advances from closed schema v2 to closed schema v3. The loader retains the
exact v2 field set and fingerprint algorithm, then adapts a proven historical snapshot to A only
in memory. New A and B configurations persist the algorithm and Skill identity. The Web exposes
the choice at import; B defaults to `L=60s` and A retains the established 30–90 second defaults.

## Consequences

A remains suitable as the stable baseline and B can be evaluated on the same source through a
separate run. B costs roughly one editorial call per `L` of source before cache reuse, so a
60-second maximum means about one call per source minute; the overlap intentionally trades cost
for boundary recall. B never falls back to A after a Provider failure because that would make
the experiment untruthful. Window/proposal caches, persisted Provider telemetry and immutable
artifacts preserve recovery and cost evidence.

The first B contract returns at most one proposal per analysis window. A later version may allow
multiple proposals or a second Agent portfolio pass, but it must receive a new Skill/config
identity and must not silently change A or `semantic_window_v1`.
