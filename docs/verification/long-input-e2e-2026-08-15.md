# Two-long-input real E2E — 2026-08-15

## Scope

This report records the real, non-Mock E2E requested for `input/8.15-1.ts` and
`input/8.15-2.ts`. Each input is a distinct Project and current PipelineRun. The
acceptance endpoint is `pending_review`: no clip was auto-approved, no final
text-bearing render was created, and no Delivery was claimed.

| Source | Bytes | Duration | Project | Current run |
| --- | ---: | ---: | --- | --- |
| `8.15-1.ts` | 2,229,033,280 | 4,660.205 s | `67e827b4c0c8493b9804241e517cc5fe` | `f0187e64fdbe44cdad62e4ae7afd9bd7` |
| `8.15-2.ts` | 2,398,135,896 | 5,042.717 s | `4e3bf22ebf2f4b6a81f5ae5a0e552a46` | `a4228d3ca597476685c11b52a1202309` |

Both sources are portrait MPEG-TS containing HEVC 1088×1920 video and AAC
audio. The sources remained read-only references beneath the configured media
root.

## Recovery exercised by the real media

The generation-1 runs (`930a3fe5512e4699b0be81a5dc286776` and
`554a23a6a5a141f4b0cabe8fe6913f82`) imported successfully and then failed
deterministically because FFmpeg emitted adjacent MPEG-TS silence events that
overlapped by 1–2 ms after canonical rounding. The persisted error was
`PREPROCESS_OUTPUT_INVALID`; it was not reported as success.

`parse_silencedetect` now normalizes silence intervals to an ordered union. A
regression test reproduces the timestamp jitter, and complete silence scans of
both sources produced 385 and 670 ordered, non-overlapping intervals. Because
unchanged deterministic retries are intentionally refused, two generation-2
runs were created in the same Projects. The failed attempts remain preserved
for audit. Fix checkpoint: `d995c9e`.

## Result matrix

| Evidence | `8.15-1` | `8.15-2` |
| --- | ---: | ---: |
| Pipeline status / progress | `completed` / 100% | `completed` / 100% |
| Succeeded stages / tasks / attempts | 6 / 6 / 6 | 6 / 6 / 6 |
| Audio chunks / ASR succeeded | 55 / 55 | 60 / 60 |
| Transcript segments | 202 | 210 |
| Rough candidates | 45 | 45 |
| Selected review clips | 15 | 15 |
| Degraded current EditPlans | 0 | 0 |
| Successful proxy renders | 15 | 15 |
| Automatic quality reports passed | 15 | 15 |
| Final Project computed state | `pending_review` | `pending_review` |
| End-to-end elapsed wall time | 2,103.4 s | 2,230.8 s |

The single heavy Worker interleaved stage tasks from both Projects, so the wall
times overlap; this is not two simultaneous heavy FFmpeg executions.

## Real Provider evidence

- `8.15-1`: OpenRouter `openai/whisper-large-v3` completed 55/55 calls with
  zero retries and 4,932.7 uploaded audio seconds including chunk overlap.
  Codex CLI `gpt-5.6-terra` produced 44 valid initial responses; one initial
  response was recorded as invalid and its single allowed repair succeeded.
- `8.15-2`: OpenRouter `openai/whisper-large-v3` completed 60/60 calls with
  zero retries and 5,340.6 uploaded audio seconds including overlap. Codex CLI
  `gpt-5.6-terra` produced 45/45 valid initial responses.
- Provider usage contains zero rows whose provider is Mock. Both selected sets
  contain zero degraded plans.

Representative real titles include “声音穿透力不够？问题在支撑”, “唱歌发声别憋气”,
“三种唱法的发声通道区别” and “吐气练习头晕的原因”.

## Media and visual verification

Every proxy's persisted quality report passed ffprobe checks, required video
and audio streams, dimensions, duration tolerance, minimum size, full decode,
black-frame checks, crop/edge heuristics, representative frames and contact
sheet generation.

Two representative proxies were independently probed and decoded again:

- `8.15-1`: `runs/g002/renders/proxies/796928a7f8214eefa7e00a7cf965fc6e/r001/review.mp4`
  — H.264/AAC MP4, 540×960, yuv420p, 57.720 s, 19,132,271 bytes; full decode
  exited 0.
- `8.15-2`: `runs/g002/renders/proxies/0959c456efd440da8a9f784708d9fe76/r001/review.mp4`
  — H.264/AAC MP4, 540×960, yuv420p, 53.640 s, 17,793,849 bytes; full decode
  exited 0.

Codex actually viewed both corresponding contact sheets. Beginning, middle and
ending frames consistently show the source's native portrait composition with
normal subject proportions. There is no blurred background, thumbnail-like
foreground, black frame, blank side or severe crop. Existing text visible near
the top of the first source is part of the original livestream frame; LiveClip
did not burn a title or subtitle into either proxy.

Contact sheets:

- `data/projects/67e827b4c0c8493b9804241e517cc5fe/runs/g002/renders/proxies/796928a7f8214eefa7e00a7cf965fc6e/r001/review-quality/contact-sheet.png`
- `data/projects/4e3bf22ebf2f4b6a81f5ae5a0e552a46/runs/g002/renders/proxies/0959c456efd440da8a9f784708d9fe76/r001/review-quality/contact-sheet.png`

## Regression and environment gates

- `make doctor`: READY; OpenRouter and Codex configured, with expected warnings
  for non-LTS Node, raster text fallback and VideoToolbox-to-libx264 fallback.
- `make lint`: Ruff/format, mypy over 121 source files, EditPlan schema,
  TypeScript all passed.
- `make test`: 584 Python tests, 29 Web tests, one Mock Chrome E2E and one real
  FastAPI/leased-Worker/SQLite/FFmpeg Chrome E2E all passed.
- Real SQLite `PRAGMA quick_check` returned `ok`; foreign-key check returned no
  rows.

The Browser plugin discovered no controllable browser instance. Google Chrome
was running, but the selected profile did not contain the Codex Chrome
Extension. No plugin was installed and MCP Chrome success is not claimed. The
repository's standalone Chrome Playwright E2E is the browser evidence above.
