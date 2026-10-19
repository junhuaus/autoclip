# LiveClip dual-profile offline-review delivery Living ExecPlan

Prepared 2026-09-25. This plan follows `.agent/PLANS.md` and extends the accepted
dual-profile benchmark flow without changing its semantic selection results.

## Purpose / Big Picture

A user can turn one validated dual-profile run and its rendered short/long
masters into the same friendly, self-contained offline-review format used by
historical LiveClip deliveries. After extraction, `index.html` plays every
clip locally and shows Chinese titles, profile, status, score, source range,
high-impact sentence, recommendation, risks, grounded editor keywords,
subtitles and quality contact sheets. The package also contains readable MP4
and SRT names, per-clip Markdown, a machine manifest, SHA-256 checksums and a
verified ZIP. Export does not approve a candidate or claim formal Delivery.

## Context and Orientation

The accepted real run is
`data/evaluations/dual-profile-benchmark-20260924-final-cold-18`. Its
`final-validated.json` is the semantic authority and its
`renders/render-manifest.json` binds twelve real MP4/SRT/contact-sheet outputs.
The historical browsable template is implemented by
`src/liveclip/delivery/package.py`; the richer pending-review contract is in
`src/liveclip/delivery/review_package.py`. Dual-profile evaluation is a
standalone application flow and has no database RenderJob/Asset identities, so
the new adapter must record its real evaluation provenance rather than invent
database task lineage.

The worktree already contains user-owned SD-6 documentation/QA edits and the
uncommitted dual-profile implementation. Preserve every unrelated change.

## Scope and non-goals

Add a dedicated dual-profile offline-review package builder, an adapter that
joins and validates final/render/run/transcript evidence, a CLI command and
Mock/local tests. Reuse existing safe filename, pinned copy, verified ZIP and
no-replace publication primitives. Do not change candidate scores, boundaries,
statuses, benchmark rules, database schema, formal Delivery state or source
media. Do not add a browser server or claim human audio acceptance.

## Progress

- [x] 2026-09-25 Locate and inspect the historical browsable Delivery and offline-review templates.
- [x] 2026-09-25 Confirm the Product Spec requires a distinct pending-review export rather than formal Delivery.
- [x] 2026-09-25 Implement the immutable dual-profile offline-review package builder and manifest.
- [x] 2026-09-25 Implement evidence joining, transcript-grounded keywords and CLI integration.
- [x] 2026-09-25 Add unit/CLI/security/integrity regressions with no model or FFmpeg calls.
- [x] 2026-09-25 Run targeted tests and lint/type checks.
- [x] 2026-09-25 Generate and verify a real package from the accepted twelve rendered clips.
- [x] 2026-09-25 Update this plan and `STATUS.md` with exact evidence and remaining limitations.

## Work breakdown

1. Define strict package input/result models independent of database task
   lineage. Publish through a temporary sibling directory and atomic
   no-replace rename.
2. Copy only files named by the renderer manifest and confined below its
   directory. Re-hash every input; reject unknown candidates, cross-profile
   identity drift, stale bounds/status, tampered media/SRT/contact sheets and
   malformed quality reports.
3. Build deterministic short-first, source-time ordering with numbered Chinese
   filenames. Include clips, subtitles, descriptions, contact sheets, quality
   JSON, audit inputs, README, combined descriptions, index, manifest and
   checksums.
4. Create a CSP-constrained file-only gallery grouped by Profile. Escape all
   model/transcript strings and use only persisted transcript intervals for
   keyword timing.
5. Add `liveclip dual-profile-review-package` as a thin CLI adapter.
6. Exercise the builder with generated fixture bytes, malicious/path/tamper
   cases and exact ZIP/hash verification. Then run it on the retained real
   artifacts without rerendering or calling a model.

## Validation and acceptance

Targeted tests must prove both Profiles appear, statuses remain pending/manual,
filenames are readable, HTML is local-only, hashes and ZIP members match,
existing output is never replaced, tampered hashes and outside-root paths fail,
and transcript keywords use real segment timing. `make lint` must pass unless an
unrelated inherited failure is recorded precisely. The real package must have
twelve MP4/SRT pairs, seven short and five long clips, pass ZIP CRC/member hash
verification and expose a working root `index.html`.

## Idempotency, recovery and rollback

The requested output path is immutable: an existing file, directory or symlink
fails. Construction occurs below a random sibling attempt directory. Any
pre-publication failure removes only that identity-checked attempt; successful
publication is atomic and never overwrites. Rerun with a new output path. The
input render tree and source media remain read-only.

## Decisions

- 2026-09-25: use offline-review semantics because every current benchmark
  match is `manual_review`; formal Delivery would falsely imply approval.
- 2026-09-25: create explicit evaluation provenance rather than filling the
  database-oriented review package with invented RenderJob/Asset identifiers.
- 2026-09-25: retain the historical card-gallery experience while grouping the
  two Profiles and adding quality contact sheets needed for this review.

## Surprises and Discoveries

- 2026-09-25: `risk_mini_0005_breathy_mix_control` intentionally carries four
  risk/context evidence cue IDs immediately before its final clip boundary.
  Evidence cues therefore are audit provenance, not a claim that every cue is
  inside the rendered interval. The package preserves them while independently
  validating the actual MP4/SRT interval against the transcript.

## Risks and mitigations

- A renderer manifest contains paths. Confine every referenced file to the
  manifest directory, reject symlinks/outside paths and verify committed hashes.
- A large MP4 package can exceed 1 GB. Stream pinned copies/ZIP members and do
  not load video bytes into memory.
- Transcript/model text is untrusted. HTML-escape all values and use a strict
  CSP; Markdown renders subtitles as indented code.
- The current twelve clips are a benchmark-matched review subset. State that in
  the notice and retain the source candidate filter in manifest provenance.

## Recovery Notes

Implementation is complete. The primary entry point is
`liveclip dual-profile-review-package`; it reads the existing transcript,
validated result, semantic run manifest and render manifest, then creates a new
immutable directory. No model or render call occurs. If the target already
exists, choose a new versioned target rather than deleting or replacing it.

## Outcomes and Validation Evidence

The builder lives in `src/liveclip/delivery/dual_profile_review.py`; the
evidence adapter lives in `src/liveclip/services/dual_profile_delivery.py`.
The adapter validates final/run/render consistency, source and artifact hashes,
render-root confinement, exact regenerated SRT content and passed decode
reports before publication. The package uses the existing pinned-copy,
no-follow, no-replace and verified-ZIP primitives.

The following checks passed on 2026-09-25:

    .venv/bin/pytest -q tests/unit/test_dual_profile_delivery.py
    5 passed

    .venv/bin/pytest -q tests/unit/test_dual_profile.py tests/unit/test_dual_profile_render.py tests/unit/test_dual_profile_delivery.py tests/integration/test_dual_profile_evaluation.py tests/unit/test_offline_review_package.py tests/unit/test_delivery.py
    52 passed

    make lint
    ruff, formatting, mypy over 208 source files, schema checks and Web typecheck passed

The real export is
`/Users/junhuaxu/Downloads/LiveClip-双轨切分-离线审核-v001`. It contains
seven short clips and five mini lessons, twelve matching SRT files, twelve
quality reports/contact sheets, audit inputs, a browsable `index.html`,
manifest, checksums and a portable ZIP. `shasum -a 256 -c checksums.sha256`
and `unzip -t` both passed. The ZIP SHA-256 is
`ee151edf3f8905561d45dd3e78847004b0fa9f03423fc29b71bf27ce8484904c`;
the manifest SHA-256 is
`2e6067571e2bc54a6f982e186848faf2a64a0b403d38a4bf4edc67471bb6ea38`.
A local Chrome render was captured and visually inspected: the root notice,
two Profile counts, navigation, Chinese titles and video cards render
correctly. Human audio/content approval remains intentionally open; every
clip retains its original `manual_review` status.
