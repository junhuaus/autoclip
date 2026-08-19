# ADR-020: Render once before review and reuse the clean delivery master

Status: accepted

Date: 2026-08-18

## Context

The earlier v1 flow rendered a 540×960 clean review proxy, required approval, and only then rendered separate 1080×1920 final media. The user rejected that ordering: review needs rendered media to make a decision, and rendering the ordinary deliverable only after the decision duplicates work without improving the keep/discard decision. Pending or rejected clips can simply be omitted from a package.

ADR-010 remains correct that model-authored title and captions must not be burned into the media shown for review. The missing decision is whether that clean media is merely a disposable preview or the standard deliverable itself.

## Decision

After candidate selection, the fixed pipeline render stage creates one clean, delivery-quality current-revision master for every selected clip. It publishes an H.264/AAC MP4, matching clip-relative SRT, automatic quality report and contact sheet before any review decision. New production defaults are 1080×1920 and one deterministic center-cropped source layer.

Review is a filter over those immutable current-revision assets:

- `approved` keeps the master eligible for formal Delivery;
- `pending_review` and `rejected` omit it from Delivery;
- a revision edit stales the old master and requires one new clean render for that changed clip.

Delivery snapshots and copies the exact approved master/SRT bytes. It does not enqueue a post-approval render. Existing persisted/API `proxy` names remain as compatibility identifiers so no database migration or client break is required. For already-rendered historical projects, a trusted current successful `final` remains a narrow Delivery fallback when no current single-render master exists.

`title_and_captions` remains an optional explicitly requested burned derivative for release workflows. It is not the ordinary Delivery gate. Approval may still gate that derivative because it visually commits reviewed text, but it never gates the clean master.

## Consequences

Reviewers inspect the same clean video bytes that ordinary Delivery will package, rendering cost is paid once per revision, and rejecting a clip is a metadata decision rather than wasted post-review work. Pipeline storage rises because all selected clips are rendered at delivery resolution, while total work falls whenever approved clips would previously have required a second encode.

Legacy field names and historical 540×960 proxies remain visible in old evidence. Product/UI language must call new `proxy` rows “审核/交付母版” and tests must prove pre-approval rendering, exclusion of pending/rejected clips, revision invalidation and Delivery without a current `final` RenderJob.
