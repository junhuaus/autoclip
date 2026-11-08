# ADR053: Customer delivery of imported dual-profile results

Status: accepted (Stage 19, 2026-11-07/08; 19a–19d accepted by the
independent tester and reviewer; 19e operator phone test pending).

## Context

Dual-profile evaluation (`python -m liveclip dual-profile-eval`, benchmark
v1 strictly accepted 2/2 on frozen `f525338`) produces validated short-highlight
and mini-lesson clips, but only as an internal CLI run directory. The end
customer (a teacher or streamer) needs to watch, read and download the chosen
clips without seeing any internal evidence, either as a file they keep or as
a link opened on a phone. The existing formal Delivery is bound to
single-profile run lineage and exposes internal fields, and the dual-profile
run has no database lineage that may be invented. The user decided
(2026-11-07): end-customer audience; offline package and expiring read-only
share link; import existing CLI results first; reviewer text overrides; clean
MP4 plus separate SRT; LAN-only sharing with explicit opt-in and no TLS; and the
benchmark freeze narrowed to the dual-profile closure.

## Decision

1. **Import, do not run.** A finished run directory and its transcript are
   imported into a new Project (lifecycle `editorial_review`,
   `source_kind = dual_profile_import`, no pipeline run). The import re-verifies
   the run with `load_verified_dual_profile_render_set()` (hashes, interval and
   status binding, transcript-derived SRTs, passed quality reports) plus the
   frozen routing policy and algorithm, confines paths to allowed roots
   (never the managed data directory), copies media as committed Assets and
   records immutable import and clip rows. Pipeline actions on imported
   Projects are refused (409); only read, membership, management, review and
   delivery apply.
2. **Append-only review.** Decisions (approve, reject, select, deselect) are
   sequenced and immutable; approvals may override title/hook/summary while the
   model originals stay immutable. A clip is deliverable when `selected`, or
   `manual_review` whose latest review is approve, and a later reject always
   blocks; a select counts only after the latest review.
3. **Customer-text warning gate.** Model summaries can contain reviewer-style
   notes. One documented pattern table flags "strong" notes and advisory
   "narration". Approving, selecting or delivering text that still has a strong
   warning is refused unless a user with `review_clip` explicitly keeps it
   (`acknowledge_warnings`, recorded on the decision). Prompts are not changed.
4. **Immutable customer deliveries.** A version (v001…) snapshots the selected
   deliverable clips with their effective text; a worker Task builds an
   offline package (allowlisted `manifest.json` from `CustomerClipView`, one
   shared `customer_index_html` page with a strict CSP and no script, clean
   MP4s, normalized SRTs, checksums, a deterministic ZIP) and publishes it
   without replacement. Later decisions never change an existing version.
5. **Separate LAN-only share server.** `make share` runs a second app with only
   four read-only routes. Tokens are shown once and stored as SHA-256; links
   expire (1–30 days), can be revoked and are scoped to one built version. The
   server binds only to loopback, `0.0.0.0` or a LAN IP literal and answers only
   loopback, RFC 1918, link-local and IPv6 unique-local/link-local clients;
   everything else, and every unknown, expired or revoked link, gets one
   identical 404. There is no TLS; internet exposure and tunnels are out of
   scope.
6. **Freeze scope.** The benchmark freeze covers only the dual-profile
   benchmark closure (listed in `STATUS.md`); Stage 19 changes outside it keep
   the 2/2 acceptance, given clean freeze evidence at every checkpoint.

## Consequences

- No fake `candidate_clips`/`render_jobs` rows; formal single-profile Delivery is
  unchanged. Six tables and four migrations (`d5e8a1c3f907`, `e4b2c7d9a1f3`, `f6a1b3c5d7e9`, `a7c9e1b3d5f2`) were added; immutability and
  delete guards are database triggers that still allow the project-purge cascade.
- Only rendered candidates can be delivered; "render more" from the console is
  deferred. The import copies media synchronously inside the request.
- Shared subtitles are the imported SRT bytes; the offline package holds a
  normalized copy (same text, different hashes).
- A phone on another network, CGNAT or IPv6 transition addresses cannot open
  links; such customers receive the offline ZIP.
- Alternatives rejected: generalizing the single-profile Delivery (would leak
  internal fields and needs invented lineage); serving share pages from the
  main API (shares its authentication surface and routes); internet sharing
  with TLS or tunnels (out of scope by user decision).
