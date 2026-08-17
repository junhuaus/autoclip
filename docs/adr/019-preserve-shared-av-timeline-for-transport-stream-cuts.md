# ADR-019: Preserve one audio/video timeline for transport-stream cuts

Status: Accepted

Date: 2026-08-16

## Context

The real `8-16-1.ts` source plays in sync in VLC because the player follows the
MPEG-TS PTS/PCR timeline. LiveClip previously used input-side `-ss` directly at
the requested cut and then applied `setpts=PTS-STARTPTS` and
`asetpts=PTS-STARTPTS` independently. At a non-keyframe HEVC cut, audio decoded
immediately while video could not reconstruct reference frames until a later
keyframe. Independently rebasing the first decodable frame of each stream made
that content offset permanent in the MP4.

At the 1368-second cut, the old path did not produce a decodable video frame
until about 2.04 seconds after audio. The source's maximum observed video
keyframe gap was 2.545 seconds.

## Decision

- Seek at most ten seconds before the requested source boundary.
- Decode that bounded preroll and apply a second output-accurate seek to the
  requested boundary.
- Preserve the source audio/video timestamps through the filtergraph; never
  apply independent `STARTPTS` rebasing to the two source streams.
- Offset trusted overlay and fade windows by the preroll duration because the
  filters observe the preroll timeline.
- Version the changed manual render cache contract as
  `ffmpeg-renderer-v4.av-sync-preroll`; old immutable artifacts are not
  overwritten.
- Keep the clean-proxy Pipeline compatibility contract unchanged so unrelated
  historical Projects are not hidden merely by this operational correction.

## Consequences

Each clip decodes at most ten additional source seconds, which is bounded and
small relative to a 30–90 second render. Accurate cuts preserve the original
relative clock and still re-encode to H.264/AAC. The regenerated 15 proxies for
`8-16-1` all start with a measured stream delta of 0 or 40 ms, and all passed
full decode and automatic quality checks. Timestamp evidence cannot prove
semantic lip sync by itself, so human review remains the final observation.
