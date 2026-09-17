# 8-21-1 `semantic_windowed` real-data verification — 2026-08-23

## Outcome

The new 5,456.232-second portrait HEVC/AAC source completed real OpenRouter ASR, cold overlapping-
window Discovery, boundary bridges, Global Review, deterministic validation, offline editorial
review, FFmpeg rendering and a browsable Delivery. Production code contains no `8-21-1` topic,
cue or timestamp hardcode.

The reviewed result is satisfactory for the intended Agent-plus-selection workflow: 12 continuous
clips were rendered and packaged. It is not evidence that raw Global Review is ready for completely
unattended publication. Two of five raw automatic clips needed generic source review: `clip_01`
ended in a half sentence and `clip_03` retained a live “type 1/type 2” interaction after the first
complete answer. Both were corrected through the audited offline-review cue contract, not through
production rules.

Editorial assessment:

- Discovery recall and topic diversity: **8.7/10**. Forty-one candidates cover breathing,
  vocal-channel, tongue, articulation, pitch, teacher-selection and product/course topics across
  the 91-minute source.
- Global selection and semantic de-duplication: **8.2/10**. Fourteen clips were kept, ten rejected
  candidate groups were audited, and the crossed-window hiss exercise was consolidated.
- Raw automatic boundary precision: **7.2/10**. Three of five automatic clips were directly usable;
  two had real ending defects despite reporting `shortest_complete`.
- Offline-reviewed delivery: **8.8/10**. Twelve clips are understandable, continuous and 45–90
  seconds, with known-risk material explicitly retained only for local evaluation.

## Source and transcript evidence

- Source: `input/8-21-1.ts`
- Source SHA-256: `2c5e128d2d34d37f1d1fa8ddf0279e8ec6f8cedf19b7134752a60e69bb538116`
- Container duration: 5,456.232 seconds; HEVC 1088×1920 video plus AAC stereo audio.
- Project: `ffc740db2c124326b86c64e798caefa7`
- Pipeline run: `8b1fc881a2074365a8a23191d96f6ce9`
- OpenRouter transcription: 65 successful chunks and 1,329 timestamped SRT cues; transcript ends at
  5,454.660 seconds.

The database Pipeline preserved successful ingest, preprocess and ASR, then stopped at candidates
because the tool-disabled Codex child could not initialize inside the outer execution sandbox. The
same audited executable and payload ran successfully outside that outer sandbox through the official
`semantic-eval` command. This is an execution-environment limitation, not a fabricated Pipeline
success; the persisted Project remains `failed` at candidates.

## Real semantic execution

Cold Discovery artifact:

`data/evaluations/8-21-1-semantic-windowed-r02-cold-host-2026-08-23`

- 91 logical windows grouped into 23 batch calls, with six 180-second boundary bridges.
- 41 Discovery candidates.
- 39 Agent calls including ten bounded repairs.
- 568,436 input and 102,640 output tokens.

The cold run exposed a generic scale defect: the Global Review package estimated 75,041 tokens
against the configured 74,240-token budget and stopped instead of dropping evidence silently. The
fix retains every candidate, linked topic and bridge, then reduces only symmetric extra context from
30 seconds toward a 15-second floor. This source selected a 20-second guard and transported 73,835
estimated tokens.

Successful Global Review artifact:

`data/evaluations/8-21-1-semantic-windowed-r05-balanced-repair-2026-08-23`

- Exact validated Discovery reuse: 23/23 batches and 6/6 bridges; no Discovery model call repeated.
- Global Review: one initial call plus one Schema repair.
- 139,624 input and 30,413 output tokens, 557.049 seconds.
- Model: `gpt-5.6-terra`, medium reasoning.
- Prompt bundle: `177cdc916b1f15f19c2e9e8b054fa743b146ce1abe78901d11cf0525fadc38c3`.
- Raw result: 5 selected, 9 manual, 1 validator-rejected clip and ten rejected candidate groups.
- Deterministic result: 14 kept clips, all continuous, 45–90 seconds and strictly above 75.

The first Global response was structurally invalid. Its repair previously included complete ranges
and then truncated the source-ordered cue list to 600 entries, which made valid late-video clips look
unknown. Repair evidence now samples both boundaries and neighbours for every editable item. The
successful repair therefore validated early cues and cues beyond 1,200 in the same result without
expanding to the full transcript.

Combined semantic cost for the cold Discovery plus accepted Global Review is 41 Agent calls,
708,060 input tokens and 133,053 output tokens. The result proves bounded recovery, but Global Review
latency and total Discovery token cost remain the main optimization target.

## Offline source review

The SHA-bound `offline-review.json` classifies all 14 kept clips. It rejects:

- `clip_02`: regional/dialect generalization dominates the practical teaching payoff;
- `clip_14`: unsupported numerical percentages and absolute improvement claims dominate the clip.

It corrects two boundaries:

- `clip_01`: cue 92–102, 00:05:29.550–00:06:22.750, 53.20 seconds. Cue 103 ended in “那我把我们…”.
- `clip_03`: cue 215–225, 00:13:04.260–00:14:01.940, 57.68 seconds. Cue 226 was a live response CTA.

The other ten reviewed ranges are unchanged. Risk-bearing clips remain local evaluation material;
their inclusion is not public-release approval.

## Render and Delivery evidence

Output:

`data/exports/8-21-1-semantic-windowed-reviewed-r01-2026-08-23`

- Twelve new real H.264/AAC renders, each with both video and audio.
- Probed durations: 50.07–88.70 seconds.
- A 12-frame contact sheet was viewed: all samples are upright, coherent portrait frames with no
  black output or crop/rotation defect.
- Delivery `v001` includes root `index.html`, 12 MP4 files, 12 SRT files, `manifest.json`,
  `checksums.sha256` and `delivery.zip`.
- Every checksum passes and `unzip -t` reports no errors.
- ZIP SHA-256: `b0b14e4c0fff6077edba5b2a0d61bf5c48353a5c7b02c9e70eb82b992b453a6f`.
- All 12 index cards have one high-impact sentence and 1–5 transcript-grounded editor keywords;
  35 keyword occurrences include both clip-relative and source times.
- Structural HTML audit found 12 articles, 12 unique video links, 12 “高光语句” sections, 12
  “编辑关键词” sections and zero missing targets.

The in-app Browser runtime exposed no browser, so no visual-browser claim is made for this exact
file page. The generated media was visually sampled, the page/resource graph was checked on disk,
and repository Mock Chrome plus isolated real API/Worker/SQLite/FFmpeg Chrome E2E passed.

## Verification commands

```text
make lint
make test
ffprobe (all 12 rendered MP4 files)
shasum -a 256 -c checksums.sha256
unzip -t delivery.zip
```

Results: lint/type/schema/TypeScript gates pass; 844 Python tests and 58 Web tests pass; Mock Chrome
1/1 and isolated real-backend Chrome 1/1 pass.

## Remaining improvement

The next algorithm improvement should not add source-specific rules. It should make the existing
Agent boundary audit harder to self-certify incorrectly: the final editor should re-check all raw
automatic clips against the immediate next cue, or run one compact boundary-only pass over automatic
clips. This run also supports hierarchical/partitioned Global Review to avoid one 67K-input call,
provided distant semantic de-duplication remains a final Agent responsibility.
