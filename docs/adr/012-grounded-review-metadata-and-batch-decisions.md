# ADR-012: Grounded review metadata and atomic batch decisions

Status: accepted

Date: 2026-08-11

## Context

Reviewing 10–20 candidates one editor at a time is slow. The user wants subtitles directly below each proxy and keywords below those subtitles, including occurrence times for later editing. The current real transcript has segment timing but truthfully records word timing as unavailable. The user explicitly does not want A/B alternatives.

## Decision

The existing candidates remain the only review units. The Web can select several clips and send one batch decision containing each clip ID and expected revision. The database validates every item before recording any decision and commits or rolls back the entire batch. The `Idempotency-Key` record and decision effects share that transaction. Browser retries reuse the exact request body and key; an included clip with an unsaved draft, changed revision or missing current row makes an old failed operation ineligible for retry.

Keywords are derived read-only metadata for the current EditPlan revision. The extractor only returns phrases with an exact normalized match in a persisted ASR segment fully contained by the clip. It uses persisted word intervals when an exact word match exists; otherwise it binds the phrase to that entire transcript segment and labels the precision `segment`. Proportional caption-display timing is never used as ASR evidence. Both clip-relative and source-absolute milliseconds are returned. No model may invent the time, and deriving keywords never invokes ASR.

Each card owns its video reference. Clicking one subtitle or keyword seeks only that card's clean proxy using clip-relative time. Metadata loading is handled before seek; the UI does not add the source-video offset to proxy time.

## Consequences

Reviewers can compare and decide multiple ordinary candidates without duplicate A/B data or partial browser-side fan-out. Segment-only ASR produces honest ranges rather than fake word points. Keywords do not enter EditPlan, do not affect rendering, and require no schema migration; caption or boundary revisions cause the derived response to change automatically. The Web excludes dirty editors from batch selection, locks editor writes during an in-flight batch, reconciles list/detail caches after completion and never silently retries a stale request.
