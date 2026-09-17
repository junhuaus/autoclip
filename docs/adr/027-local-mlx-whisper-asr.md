# ADR-027: Optional pinned local MLX Whisper ASR

Status: accepted for implementation; real accuracy acceptance pending

Date: 2026-09-02

## Context

Repeated full runs can differ because cloud ASR/upstream routing and later editorial inference are not
byte-deterministic. The user prioritizes stable, accurate Chinese recognition over elapsed time and has
an Apple M2 Mac with 24 GB unified memory. LiveClip still needs real segment timing and must preserve
existing cloud modes and durable cache rules.

## Decision

Add explicit `mlx-codex`. Its ASR adapter uses `mlx-whisper==0.4.3` and the full, unquantized
`mlx-community/whisper-large-v3-mlx` snapshot at commit
`49e6aa286ad60c14352c404340ded53710378a11`. Installation is explicit and model bytes live only under
ignored operational data. Runtime accepts a local directory, validates exact config/weight hashes and
never asks the Hub to resolve a model.

Decode is fixed to Chinese `transcribe`, FP16, temperature `0.0`, deterministic greedy selection,
`condition_on_previous_text=false`, no generic initial prompt and word timestamps. The initial full-input evaluation used `true`
and exposed long repeated-template, counter, single-word and laughter loops. The pinned runtime itself
documents that disabling previous-text conditioning reduces this failure mode; targeted real reruns of
the three worst intervals removed those loops. An exact boundary-chunk experiment additionally proved
that the generic product vocabulary prompt caused a 29.98-second “直播” loop with compression ratio
26.76; the same chunk without that prompt had no failed decode. Segments exceeding the frozen 2.4
compression-ratio threshold or falling below the frozen -1.0 average-log-probability threshold are
dropped and counted rather than published. The pinned runtime explicitly does not implement beam
search, so the unsupported option is forbidden instead of ignored. Local ASR concurrency is one. The exact model
and decode fingerprint is the Provider contract used by immutable PipelineRun config and chunk caches.
Verified chunk bytes are decoded through fixed FFmpeg argv to a private local WAV. There is no fallback
to OpenRouter, OpenAI or Mock. Codex remains the later cloud-backed editorial provider and receives
transcript text, not audio.

`openrouter-codex` remains the default until a labelled representative Chinese set compares character
error rate, domain terms, omissions, repetitions and timestamp error, and three cache-bypassed local
runs establish observed repeatability.

## Consequences

- Base installs remain usable without local model weights; local ASR is an optional dependency and an
  explicit setup step.
- Model installation consumes about 3.1 GB plus package/cache space and first inference must load the
  model into unified memory.
- Exact pins favor reproducibility over automatic upgrades. Any package, model or decode change is a
  new contract and requires deliberate re-acceptance.
- The shared vocabulary prompt is intentionally ignored by local accuracy mode; domain prompting can
  return only through a separately evaluated immutable contract.
- Audio privacy improves in `mlx-codex`, but editorial text still crosses the Codex trust boundary.
- MLX inference cannot be assumed deterministic across different hardware/runtime revisions; measured
  claims are scoped to the pinned host and contract.
