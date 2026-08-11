# ADR-010: Clean review proxies and separate editorial metadata

Status: accepted

Date: 2026-08-05

## Context

The first implementation rendered the proposed title and caption cues into every review proxy. The user clarified that the first artifact must instead be the video slice itself, accompanied by separate descriptions such as highlight title, Hook, recommendation reason, risk flags and editable captions. Burning proposed text before review makes the video harder to judge, visually commits unapproved model output and forces a re-encode to inspect a metadata-only correction.

## Decision

The renderer has two closed, system-selected modes:

- `none`: used by automated and manually requested review proxies. It renders the validated source interval and chosen 9:16 layout with audio processing/effects, but creates no LiveClip title or caption overlays.
- `title_and_captions`: used by the approved current final revision. It renders the same deterministic layout and may burn the reviewed title and caption cues.

Title, Hook, reason, score, risk flags and caption cues remain immutable EditPlan-revision metadata and are returned by CLI/API/Web next to the clean proxy. Model output still cannot select arbitrary renderer syntax. Render fingerprints include the text mode and renderer contract version, so an earlier text-bearing proxy cannot be recovered as a clean one. Any revision change continues to stale older renders even when the proxy pixels would otherwise be unchanged; delivery eligibility is tied to exact revision identity, not visual similarity.

## Consequences

Reviewers see the underlying slice without unapproved LiveClip text, while final deliveries retain the existing optional title/caption presentation. Proxy safe-area validation is `not_applicable`; final overlay bounds remain validated. Demo and end-to-end tests must prove a clean proxy, a stale old revision and a text-bearing final render. Native text that already exists inside the source livestream remains source content and is not removed.
