# ADR-025: Overlapping-window semantic clipping

Status: accepted

Date: 2026-08-22

## Context

`semantic_global` proved that Agent-owned semantic discovery and one global editorial review improve
recall and semantic deduplication, but rereading a 78-minute transcript in multiple large prompts made
latency, token use and failed-run recovery worse than the product needs. The historical B v1 window
path is cheaper, but its one-candidate-per-window limit and mechanical overlap rejection lose or split
valid topics.

The target clip remains one continuous 45–90 second source interval, ideally near 60 seconds. Transport
must therefore preserve at least one full maximum-length topic at ordinary window boundaries while
leaving semantic identity, value and boundaries to the Agent.

## Decision

Add `semantic_windowed` as the recommended new-run mode while retaining A, B v1, experimental B v2 and
Full-first `semantic_global` for compatibility and comparison.

Discovery uses 120-second logical windows at a 60-second step. Four logical windows are deduplicated
into one request containing the 0–300 second union. Each batch owns a half-open 240-second start-time
interval; a candidate is emitted only by the batch whose ownership interval contains its final start
cue. The next batch starts at the previous ownership end, so transport overlap cannot create two
owners.

Discovery returns zero or more candidates, a complete topic map for its context, and structured left
and right open-topic reports. If either side of an internal batch boundary says the topic continues,
Python schedules one boundary call over the fixed 180-second union of the two adjacent logical edge
windows. Python only schedules and validates that the returned interval crosses the boundary; it does
not decide whether the two sides are semantically identical.

Base batches that miss cache run with a bounded default concurrency of four. Each batch and boundary
request has an independent cache identity containing transcript evidence, algorithm, input range,
runtime settings, model and Prompt hash. A failed request therefore does not invalidate historical
algorithms or unrelated batches.

Global Review receives every candidate's complete source transcript, roughly 30 seconds of adjacent
context, Discovery evidence and boundary-call results. It compares all candidates, resolves semantic
duplicates, verifies shortest-complete boundaries, scores once on the common scale and applies typed
risk judgment. It does not rescan the complete livestream in this mode.

Python remains responsible only for schema, cue/time, single-continuous-interval, 45–90 second duration,
score arithmetic and strict `>75`, typed risk gates, Top-N ceiling, cache, telemetry and FFmpeg. It does
not use keywords, punctuation, time-overlap ratios or adjacency seconds to infer a topic, merge or
semantic duplicate.

## Consequences

The normal 78-minute regression uses about twenty parallelizable Discovery calls plus boundary calls
that occur only when an outside edge is open, followed by one Global Review. Repeated transcript
transport is bounded to the 60-second overlap and compact Discovery Skill rather than two whole-live
prompts. Individual batches can be retried and cached independently.

The mode has more calls than Full-first and may transport about 1.3 times the transcript duration, but
it reduces the blast radius of an invalid response and lowers wall-clock latency through bounded
parallelism. Full-first remains useful as an explicit comparison mode.

Regression acceptance includes: recovering a 50–140 second cross-window topic; keeping adjacent but
independent questions separate; rejecting a semantic core shorter than 45 seconds instead of padding
with live noise; and emitting one final owner for a candidate seen across windows or batches.
