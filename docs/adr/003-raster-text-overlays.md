# ADR-003: Rasterized text overlays for captions and titles

Status: accepted, pending M1 performance validation, 2026-08-03

## Context

The inspected arm64 FFmpeg 8.1.2 build has `overlay` but lacks `subtitles`, `ass` and `drawtext`; its build configuration omits libass/freetype/harfbuzz. Product capability still requires safe burned Chinese captions and a title bar. Model/user text must never become filter syntax.

## Decision

Pillow renders bounded title/caption text with an allowlisted Chinese font into transparent full-frame RGBA images. FFmpeg receives those files as separate system-generated inputs and applies fixed overlay templates with validated numeric time windows. Doctor reports exact missing filters. A fuller FFmpeg install is optional, not a prerequisite or alternate untrusted path.

## Consequences

The current host can meet M1 without system installation and text never enters a filtergraph. We add Pillow and must validate glyph coverage, safe areas, memory/input count and performance on 30–90 second clips. If the Spike fails materially, install guidance for a full FFmpeg build will be reconsidered in a new ADR rather than silently dropping text.
