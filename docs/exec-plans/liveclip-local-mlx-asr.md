# Local MLX ASR Living ExecPlan

This plan follows `.agent/PLANS.md`. It is the durable implementation contract for the
accuracy-first local ASR capability requested on 2026-09-02. The existing OpenRouter, direct OpenAI
and Mock providers remain compatible alternatives until real local acceptance evidence justifies a
default change.

## Purpose / Big Picture

A LiveClip operator on Apple Silicon can choose a local `mlx-codex` processing mode. LiveClip then
transcribes every verified audio chunk with one pinned, unquantized Whisper `large-v3` FP16 model on
the Mac and sends only the resulting transcript to the existing Codex editorial provider. No audio
leaves the machine. Decode settings are fixed for stability, the exact model bytes are represented in
the immutable PipelineRun contract, and the existing per-chunk cache/retry/timestamp rules continue to
apply.

## Context and Orientation

The ASR application port is `src/liveclip/providers/asr/base.py`. Cloud adapters live in
`src/liveclip/providers/asr/openai.py` and `openrouter.py`; provider composition is in
`src/liveclip/pipeline/stage_handlers.py`, `src/liveclip/bootstrap.py` and
`src/liveclip/providers/readiness.py`. `PipelineRunConfig` in
`src/liveclip/application/pipeline.py` freezes the provider, model, concurrency and Provider contract
for recovery. `src/liveclip/pipeline/transcript.py` owns per-chunk cache validation and deterministic
overlap merging.

The development Mac is an Apple M2 with 24 GB unified memory. The selected model is the full
`mlx-community/whisper-large-v3-mlx` FP16 snapshot, not Turbo and not a quantized checkpoint. Model
weights are operational data below ignored `data/models`; they must never enter Git.

## Scope and Non-goals

This slice adds the optional local Provider, safe readiness/Doctor reporting, immutable configuration,
tests, dependency lock and operator setup documentation. It does not remove cloud modes, silently fall
back to cloud, change candidate/editorial semantics, claim accuracy before a labelled comparison, or
make the local mode the default before real acceptance. Cross-Project cache sharing and semantic-model
reproducibility are follow-up milestones because they have separate storage and product consequences.

## Milestones and Progress

- [x] 2026-09-02 Confirm root cause and select full Whisper large-v3 FP16 with single-worker,
  temperature-zero deterministic decoding.
- [x] 2026-09-02 Inspect the current ASR port, immutable Pipeline config, readiness, Doctor and cache
  boundaries; preserve all pre-existing dirty-worktree changes.
- [x] 2026-09-02 Add and unit-test a lazy local MLX ASR adapter with pinned model-byte fingerprint, strict
  large-v3/non-quantized validation, safe chunk handling and bounded telemetry.
- [x] 2026-09-02 Add `mlx-codex` to Settings, immutable PipelineRun configuration, readiness, API health, Web
  types and Stage composition without changing the default mode.
- [x] 2026-09-02 Add the optional locked dependency and documented model installation/readiness workflow.
- [x] 2026-09-02 Pass focused tests, full lint and complete local test gates.
- [x] 2026-09-02 Download the full model outside Git, run a short real local transcription, inspect timestamped
  artifacts, then run three cache-bypassed repeats before making any stability claim.
- [x] 2026-09-02 Generate complete local transcripts over the same 78 chunks, use an anonymous
  tool-disabled Codex full-text judge as the user-approved accuracy criterion, find and repair the
  repetition-loop causes, then accept v4 over OpenRouter 60.6 to 55.0 at medium confidence.
- [x] 2026-09-03 Start a real `auto` run on `8-30.ts`; complete ingest, preprocess, local ASR 78/78 and
  36 window/bridge Discovery units, then diagnose the pre-Provider Global Review token-budget failure.
- [x] 2026-09-03 Add and gate a lossless declared-column Global Review fallback; replay the exact real
  artifacts at 73,770/74,240 tokens with all 39 candidates and 47 coverage topics retained.
- [x] 2026-09-03 Resume the same Run through Global Review, render, selection and immutable Delivery;
  inspect all three real MP4s, contact sheets, manifest checksums and ZIP before claiming operational
  end-to-end success.
- [x] 2026-09-03 Correct the manual-review materialization gap, replay the exact semantic caches without
  a Provider call, render all 13 kept clips and explicitly publish them as immutable Delivery v002
  after the user's manual selection.
- [x] 2026-09-04 Apply the user's final inclusion rule: every deterministically retained clip with
  recomputed score strictly greater than 75 enters default Delivery regardless of automatic/manual
  provenance; keep the `manual_review` flag as advisory metadata.
- [ ] Build a human-labelled representative Chinese evaluation set and compare CER, terminology,
  omissions, repetitions and timestamp error before making an acoustic-accuracy claim.

## Work Breakdown

The main agent owns all files. No parallel writer is used. Implementation order is Provider primitives,
runtime composition, dependency/docs, focused tests, full gates, then real model evidence. The adapter
must import MLX lazily so existing installations and Mock tests still start without the optional extra.

## Concrete Commands

From the repository root:

    make setup-local-asr
    .venv/bin/pytest -q tests/unit/test_mlx_asr.py tests/unit/test_settings.py \
      tests/unit/test_provider_readiness.py tests/unit/test_stage_handlers.py
    make lint
    make test

The checked-in setup command installs `mlx-whisper==0.4.3`, downloads only `config.json` and
`weights.npz` from exact commit `49e6aa286ad60c14352c404340ded53710378a11`, and verifies the
recorded SHA-256 and byte count. A successful dependency import is not model readiness; Doctor verifies
the package, Metal import, FFmpeg, local directory, full FP16 model configuration and exact byte
fingerprint without loading transcript content.

## Validation and Acceptance Criteria

- Existing Provider modes keep their exact behavior and tests.
- `mlx-codex` needs no ASR credential and fails before Project processing when MLX, FFmpeg or the model
  snapshot is unavailable.
- Runtime never interprets a remote repository ID; it accepts only a configured local model directory.
- Model configuration is exactly Whisper large-v3 and contains no quantization stanza. Required model
  bytes are regular non-symlink files and are SHA-256 fingerprinted into the ASR contract.
- Audio is read only through verified chunk metadata; the MLX library receives a private decoded local
  artifact, never an untrusted/model-authored path.
- Decode parameters are fixed at language `zh`, task `transcribe`, FP16, temperature `0.0`,
  deterministic greedy selection, disabled previous-text conditioning, no generic initial prompt and
  word timestamps. High-compression or low-log-probability failed decode segments are counted and
  omitted. The pinned runtime's
  unsupported beam-search option is forbidden.
- Provider output is mapped to bounded chunk-local integer milliseconds; malformed results fail closed
  and never become a transcript cache hit.
- No fallback to OpenRouter, OpenAI or Mock occurs.
- Real accuracy/stability is reported only after real model and labelled evidence exist.

## Idempotency, Recovery and Cancellation

The Provider contract includes model and decoding identity, so incompatible weights or settings cannot
reuse a chunk cache. Existing immutable chunk cache publication remains the recovery unit. Cancellation
is checked before decode, after local media conversion and after model inference; a cancelled operation
does not publish a successful cache. A failed chunk preserves prior successful chunk caches.

## Surprises and Discoveries

- The current project-local ASR cache already keys on Provider/model/contract and exact chunk bytes, so
  no cache format change is required for this first optional Provider.
- `mlx-whisper` keeps one model in its process-level holder, which fits the desired single-worker mode.
- The current pip release and current upstream conversion filenames have differed historically; local
  readiness must validate the actual installed loader contract and model files rather than assuming a
  filename from documentation.
- The Hugging Face Xet downloader attempted to write a global user cache under the managed sandbox and
  failed before model installation. The checked-in installer now uses a repository-local ignored cache
  and disables Xet; the ordinary HTTPS download resumed without changing trusted source or hashes.
- A real direct call proved `mlx-whisper==0.4.3` raises `NotImplementedError` for `beam_size`; the ASR
  contract was corrected to deterministic temperature-zero greedy decoding instead of claiming an
  unsupported accuracy feature.
- Passing an M4A/MP4 chunk through `pipe:0` can produce a header-only WAV because the container needs a
  seekable input. The adapter now gives FFmpeg the already verified inherited descriptor through
  `/dev/fd/N` and rejects decoded PCM shorter than 75% of the declared chunk duration.
- The first complete local run exposed repetition loops caused by previous-text conditioning. After
  disabling it, an exact boundary experiment proved the shared generic vocabulary prompt independently
  caused a 29.98-second `直播` loop with compression ratio 26.76. v4 fixes no local initial prompt and
  rejects/counts final decode results that exceed the frozen compression/log-probability thresholds.
- The exact 3,159-segment transcript made lossless Global Review evidence exceed its hard token budget
  until declared-column transport removed repeated JSON field names. A later repair-path failure exposed
  that its ID allowlists decoded only object transport and therefore became empty for compact rows. The
  shared transport decoder now rehydrates both representations; the next real bounded repair succeeded.
- Foreground `Ctrl-C` records cancellation rather than pausing. Explicit `retry` now safely resumes a
  terminal cancelled run only when its first cancelled stage has one unambiguous cancelled stage task;
  completed stages remain immutable and cancelled downstream stages are requeued.

## Decision Log

- 2026-09-02: Choose full `large-v3` FP16, not Turbo or quantization. The user explicitly prioritizes
  stability and recognition accuracy over elapsed time.
- 2026-09-02: Add `mlx-codex` as an explicit compatible mode before changing defaults. Real labelled
  accuracy evidence is required for the later default decision.
- 2026-09-02: Force one local ASR worker. Concurrent cloud request count is not a meaningful local GPU
  tuning knob and shared model concurrency would weaken memory and determinism guarantees.
- 2026-09-02: Require a local model directory and forbid implicit Hub download during a Pipeline run.
  Installation is explicit; processing remains offline and recoverable.
- 2026-09-02: Pin repository commit `49e6aa286ad60c14352c404340ded53710378a11`, config SHA-256
  `34982ce6…e6500e3`, and the 3,083,520,416-byte weight SHA-256 `05ff791c…99b40d`.
- 2026-09-02: Accept the user's requested text-only Codex comparison boundary for this iteration. The
  final anonymous full-transcript judge preferred local v4 60.6 to 55.0 with medium confidence; this
  selects the explicit test mode but is not relabelled as CER/WER or acoustic accuracy.

## Risks and Mitigations

- MLX/package/model drift: pin dependency, hash exact required model bytes and bind that fingerprint to
  PipelineRun config.
- GPU or decoder nondeterminism across upgrades: freeze settings and cache identity, record environment,
  and test three fresh repetitions; exact regression uses verified cache replay.
- Whisper hallucination over music/silence: retain no-speech/log-probability checks and measure on the
  actual livestream rather than relaxing output validation.
- Word alignment increases memory/time: single-worker inference and strict optional-word validation;
  segment timing remains mandatory.
- Large operational files entering Git: store below ignored `data/models` and verify Git status before
  any checkpoint.

## Recovery Notes

If interrupted, rerun `make setup-local-asr`; the Hub client resumes the ignored partial file and the
installer accepts nothing until exact hashes pass. Keep the default provider unchanged. After download,
run focused and full gates, then use a short extracted real-audio sample for the first Metal inference.

## Outcomes and Retrospective

The optional provider, setup/readiness surface and pinned model are operational. Doctor passed outside
the managed sandbox, and three cache-bypassed real runs returned byte-equivalent segment text/timing
evidence. Three complete 78-chunk research passes exposed and then eliminated the major repetition
loops. The accepted final Codex blind judge preferred local v4 60.6 to OpenRouter 55.0 at medium
confidence under the user's text-only criterion. This establishes scoped repeatability and comparative
text quality for this source, not measured acoustic accuracy.

The real `8-30.ts` Project `d77d8b48cc194897a3e488b83bad9510` completed all six stages with the
78/78 local transcript caches, 36 Discovery units, three automatically selected Global Review plans
and ten manual-review `keep` results. The original implementation materialized only the automatic set,
so default selection published immutable Delivery v001 with 70.84, 50.00 and 45.52-second
1080x1920 H.264/AAC MP4s. Every file independently decoded, the three contact sheets were viewed, all
manifest hashes and `unzip -t` passed, and the ZIP SHA-256 is
`509c6f57cd91212a6c343bf22ea9a87507dd142a665b85d0c04c7dc1393691a5`. Final gates pass at 944 Python
tests, 58 Web tests and both Chrome E2Es. The package default remains unchanged for compatibility; the
explicit local mode now has a completed real operational Pipeline and Delivery.

The materialization bridge now creates revisions and clean renders for both validated sets and marks
the ten risk-bearing items with advisory `manual_review` provenance. Generation 3
Run `a446bdd3c2ed448185ee0f71b26750da` reused the exact 78 ASR, 36 Discovery and one Global Review
caches with zero new Provider calls, then rendered 13/13 clips in one successful attempt. At the user's
explicit direction, manual selection approved all 13 and published Delivery
`81fdfe69f891430fa6bf2553b658cd63` v002. Its 451,682,649-byte ZIP SHA-256 is
`482d5cbab0937b3e862edacd2bf793002a710427d1da04165d2c5418367ef19e`; every manifest checksum, ZIP
member and full MP4 decode passes, all streams are H.264/AAC, and all 13 contact sheets were viewed
without an observed orientation, black-frame, crop or composition defect. Final gates pass at 946
Python tests, 58 Web tests, Mock Chrome 1/1 and real API/Worker/SQLite/FFmpeg Chrome 1/1.

On 2026-09-04 the user made the Delivery rule explicit: automatic/manual provenance must not split
default inclusion. `SelectionService` therefore selects every new retained revision; the upstream
deterministic `score > 75` gate remains authoritative and risk flags remain visible in the manifest.
Fresh Project `4ee1c923ffbb486f8cd438f60b8cb281` proved the ASR transcript was byte-equivalent at the
canonical segment/time/text level to the earlier accepted run, but fresh Codex Discovery/Global Review
was not editorially stable: 41 rather than 39 Discovery candidates and seven rather than 13 retained
clips. Delivery v002 contains all seven scores (85–89), including three advisory manual-review items.
The post-change full gate passes 946 Python tests, 58 Web tests, Mock Chrome 1/1 and real
API/leased-Worker/SQLite/FFmpeg Chrome 1/1.
