# ADR-015: Selective editor handoff uses immutable MP4/SRT packages

Status: accepted, 2026-08-15

## Context

Editors need to download any selected current highlights, their editable subtitles and editorial descriptions for continued work in Jianying/CapCut. Formal Delivery requires approved final renders and may contain burned text; the existing offline-review export always snapshots the whole review set. Neither represents a selective clean editing handoff. Jianying's private draft format has no stable public contract that LiveClip can safely claim or maintain.

## Decision

Add a distinct durable `EditPackage` aggregate and exact ordered `EditPackageClip` snapshots. Owner/editor selection requires current clean proxy and contact-sheet Assets, exact EditPlan revision, committed producer/quality evidence and a completed current generation. A normal SQLite-leased heavy Task builds immutable `edit-packages/vNNN` with clean H.264/AAC MP4, basename-matched UTF-8 no-BOM SRT, JSON/CSV descriptions, high-impact sentences, grounded keyword times, thumbnails, import guidance, checksums, manifest and optional ZIP. Individual current MP4/SRT downloads use revision-bound signed URLs.

Selection, Project generation/epoch, membership, revision, RenderJob, producer TaskAttempt, Asset hashes and lease are fenced before and after no-replace publication. Pipeline-stage and manually rerendered proxies retain their distinct valid producer fingerprints. EditPackage status is independent of Review, Render, Delivery and business lifecycle; old succeeded versions remain immutable.

## Consequences

The package imports through standards-based media/subtitle paths in Jianying/CapCut Desktop/Web and other editors without fabricating a native draft. A user can export before approval and no new ASR/LLM call occurs. More rows, a migration and one routed Delivery-kind Task handler are required; task ownership is disambiguated by its exact target aggregate. External Jianying UI import remains an explicit acceptance item when the application is installed.
