# ADR-011: Single-layer video rendering without blurred backgrounds

Status: accepted

Date: 2026-08-11

## Context

Generation 3 selected `vertical_blur_background` for 10 of 15 clips and `center_crop` for five. The first template blurred a fill copy of the source and placed a shrunken aspect-fit copy in front, while the second showed one direct source layer. The user explicitly rejected blurred backgrounds and required all generated clips to use one consistent presentation.

## Decision

All review and final renders use a single source-video branch with deterministic center crop. LiveClip must not generate a blurred background, duplicate the source into foreground/background layers, or shrink a foreground copy over a fill layer.

Layout is removed from the LLM editorial wire schema and is now system-owned. Deterministic fallback also selects `center_crop`. The historical `vertical_blur_background` enum value remains readable only for persisted audit compatibility; active EditPlan validation and FFmpeg request validation reject it, and the filtergraph contains no blur branch.

The renderer and clean-proxy contracts are versioned again. Migration `c91f4e2a7b63` marks every pre-no-blur proxy and every render tied to a removed layout stale, cancelling or requesting cancellation of active tasks. A historical current plan can create an immutable human revision with the only accepted patch value, `center_crop`, before rerendering.

## Consequences

Every candidate has consistent composition and no synthetic blurred canvas. A wide source is center-cropped to the configured portrait dimensions, so side content may be excluded; preserving the full wide frame with bars is not part of this decision. Old media remains immutable on disk but cannot be presented as a current valid proxy or used for a new Delivery. Contact-sheet inspection and regression tests must prove the absence of `boxblur`, split background/foreground branches and shrunken foreground composition.
