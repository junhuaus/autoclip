# 8-16-3 semantic_windowed verification — 2026-08-23

## Outcome

The recommended overlapping-window algorithm completed a real semantic run, offline editorial
review, FFmpeg rendering and browsable Delivery for the 701-cue, 4,659.820-second fixture. Production
code contains no source-specific time or topic hardcode.

## Algorithm contract

- Discovery: 120-second logical windows, 60-second step, four logical windows per deduplicated
  300-second batch, half-open 240-second ownership, bounded concurrency five.
- Boundary recovery: either outside edge reporting an unfinished topic schedules the fixed
  180-second adjacent-window union; Python triggers transport only and makes no semantic merge.
- Global Review: candidate text plus local context and boundary evidence; it owns semantic duplicate,
  shortest-complete boundary, source fidelity, risk and final scoring.
- Deterministic layer: JSON Schema, cue/time mapping, one continuous 45–90 second range, score strictly
  above 75, risk gates, Top-N ceiling, statistics, caching and FFmpeg.

## Real model evidence

The run is one recoverable cold chain split across two immutable directories:

1. `8-16-3-semantic-windowed-r15-cold-final-2026-08-23`: all 20 base batches ran; a contradictory
   candidate/topic reference correctly stopped post-Schema validation. It records 24 calls,
   334,473 input tokens, 66,922 output tokens and 292.467 seconds.
2. `8-16-3-semantic-windowed-r16-cold-resume-2026-08-23`: reused exactly those 20 validated batch
   checkpoints, ran seven boundary bridges and Global Review/repairs. It records 10 calls, 221,459
   input tokens, 44,078 output tokens and 640.231 seconds.

Combined: 34 calls, six repairs, 555,932 input tokens, 111,000 output tokens and 932.698 seconds using
`gpt-5.6-terra`. The 28 Discovery candidates became 14 kept clips: 3 automatic and 11 manual. The
validated plan touches at least 9/12 reference anchors. `r23-final-plan` is a deterministic zero-call
replay of these exact stage outputs and is the plan used for delivery.

Important boundaries:

- breathing answer after offline source review: cue 179–193,
  `00:15:32.500–00:16:40.950`, 68.45 seconds;
- four-step method after offline source review: cue 224–231,
  `00:20:06.950–00:21:35.440`, 88.49 seconds;
- R&B positioning: cue 509–517, `00:57:54.550–00:58:43.550`, 49.00 seconds.

The old advertising-padded `12:22` clip, welcome-padded `1:12:55` clip, unfinished “但是” ending and
source-reframed medical title are absent. Offline review additionally rejects `clip_03` as redundant
and `clip_12` as a repeated high-risk absolute-talent claim.

## Render and Delivery evidence

The review artifact is `r23-final-plan/offline-review.json`. It is bound to the exact
`final-validated.json` SHA-256 and classifies all 14 kept clips. Boundary overrides use transcript cue
IDs and are checked by the generic `semantic-deliver` service; they are not production prompt input.

Output:

`data/exports/8-16-3-semantic-windowed-reviewed-r25-final-2026-08-23`

- 12 actual 1088×1920 H.264/AAC renders, all with audio and video;
- probed container durations 45.08–88.52 seconds;
- immutable `deliveries/v001/index.html`, 12 MP4s, 12 SRTs, manifest and checksums;
- ZIP SHA-256 `e33a5334f1f5def6883c597299cb6f502891c0e5b14cfa11550d1211f93e51c2`;
- all checksum entries and `unzip -t` pass;
- eleven unchanged renders were reused only after exact source/range/hash validation, while the
  corrected four-step interval was freshly rendered;
- representative 12-frame contact sheet was actually viewed and showed coherent portrait frames.

Web-metadata superseding package:

`data/exports/8-16-3-semantic-windowed-reviewed-r26-web-metadata-2026-08-23`

- no new Agent call and no model tokens; 11 exact render matches were reused and one clip was
  re-encoded because the prior audit package held that corrected interval locally;
- all 12 manifest entries include the final semantic `hook`, review reason, deduplicated risk types
  and transcript-grounded `keywords` with both clip-relative and source milliseconds;
- keyword counts are 1–5 per clip, 37 total, with no empty hook or keyword set;
- the root index uses the same “高光语句 / 推荐上屏” and “编辑关键词 / 仅供编辑定位” information
  hierarchy as the Web review card;
- ZIP SHA-256 is `10f6f503a6c18d217b4d922a1c3a87ac755b7c140b413051f6402c08ddab53e2`;
  every member checksum and `unzip -t` pass.

The in-app Browser runtime had no registered browser, so this exact `index.html` was not visually
claimed. Its 12 HTML5 video links and all referenced resources were checked on disk; the repository's
Mock Chrome and isolated real-backend Chrome flows passed.

## Verification commands

```text
make lint
make test
ffprobe (all 12 rendered MP4 files)
shasum -a 256 -c checksums.sha256
unzip -t delivery.zip
```

Results: lint/type/schema gates pass; 842 Python tests pass; 58 Web tests pass; Mock Chrome 1/1 and
isolated real API/Worker/SQLite/FFmpeg Chrome 1/1 pass.
