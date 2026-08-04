# ADR-003: Rasterized text overlays for captions and titles

Status: accepted and validated through M1/M5, 2026-08-04

## Context

The inspected arm64 FFmpeg 8.1.2 build has `overlay` but lacks `subtitles`, `ass` and `drawtext`; its build configuration omits libass/freetype/harfbuzz. Product capability still requires safe burned Chinese captions and a title bar. Model/user text must never become filter syntax.

## Decision

Pillow renders bounded title/caption text with an allowlisted Chinese font into transparent full-frame RGBA images. FFmpeg receives those files as separate system-generated inputs and applies fixed overlay templates with validated numeric time windows. Doctor reports exact missing filters. A fuller FFmpeg install is optional, not a prerequisite or alternate untrusted path.

## Consequences

The current host meets the product path without system installation and text never enters a filtergraph. M1/M5 real renders, full decodes and viewed contact sheets validate Chinese glyph coverage and safe areas. The domain and renderer share a maximum of 64 title/caption overlays, and FFmpeg filter/encoder workers are bounded; overflow is rejected before render instead of truncated. Representative 2–4 hour/M3 throughput remains a performance limitation, not an unresolved rendering-capability Spike. If future media shows a material failure, installation guidance for a full FFmpeg build will be reconsidered in a new ADR rather than silently dropping text.
