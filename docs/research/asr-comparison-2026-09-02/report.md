# OpenRouter versus local MLX ASR text-only comparison — 2026-09-02

## Accepted result

The accepted blind comparison used the same 6,634,001 ms source and the same 78 preprocessed audio
chunks. Anonymous system A was the final local MLX v4 transcript; system B was the retained
OpenRouter transcript. The mapping was not disclosed until after the judge returned.

Codex `gpt-5.6-sol` at maximum reasoning selected local MLX with medium confidence:

| Metric | Local MLX v4 | OpenRouter |
| --- | ---: | ---: |
| Text-quality proxy | 60.6 | 55.0 |
| Chinese fluency | 6.3 | 5.8 |
| Contextual coherence | 6.5 | 6.0 |
| Terminology consistency | 5.6 | 4.9 |
| Completeness proxy | 6.9 | 6.4 |
| Timestamp continuity | 5.0 | 4.4 |

The total is mechanically required to equal twice the five subscore sum, and the preferred system
must have the higher total. The accepted result passed those local semantic checks. Codex found the
local result generally better on core singing terminology, local context, content retention and
overlap control. OpenRouter retained some longer causal passages and a few song fragments better.

This is the user's accepted text-only quality criterion. It is not CER, WER or acoustic accuracy:
Codex did not hear the audio and no human reference transcript was supplied. The result cannot detect
errors made by both systems and is appropriately only medium-confidence.

## Compared artifacts

| Artifact | Segments | Characters | SHA-256 |
| --- | ---: | ---: | --- |
| OpenRouter | 1,137 | 24,290 | `f9b62475a0ffdace4ac52232b1b0186326218768bb98543ffe29ad8a6b7387d4` |
| Local MLX v4 | 3,159 | 22,558 | `464409fc760d5ae6a1c68705df5cafe06d74b64c05c47d681a4e1f48565f3062` |

The v4 transcript completed all 78 calls without a retry. Its final segment ends at 6,630,860 ms,
followed only by the source tail. Across the complete transcript, the known long `直播`, `我们` and
`哈哈` loop signatures are absent. One unrelated fixed template remains. The new decoder-failure
filter rejected zero segments in the full v4 run because disabling the problematic prompt prevented
the high-compression outputs before filtering was needed.

## Root cause and iterations

The first complete local transcript used `condition_on_previous_text=true`. Its blind result favored
OpenRouter 74 to 53 with high confidence because the local transcript contained long repeated
templates, counters, single words and laughter. The pinned `mlx-whisper` runtime explicitly documents
that previous-text conditioning can get stuck in repetition loops. Setting it to `false` removed the
three worst loops in exact real-audio reruns.

The second complete local transcript still contained a 29.98-second `直播` loop at the start of a
chunk. A controlled same-chunk experiment isolated the shared vocabulary prompt
`LiveClip、直播、高光、切片`: with the prompt, the decoder returned the loop at compression ratio
26.76; without the prompt, the failed output disappeared. The v4 contract therefore fixes
`initial_prompt=None` for local accuracy mode.

Pinned `mlx-whisper` checks compression ratio and average log probability when deciding whether to
retry, but a temperature-zero-only run has no fallback decode to try and returns the final failed
result. LiveClip v4 now also omits and counts segments with compression ratio above 2.4 or average log
probability below -1.0. A focused unit regression proves a rejected loop does not remove a valid
neighboring segment.

The intermediate v3 judge output is retained for audit but is not accepted: its prose preferred local
MLX while its raw 0–10 subscore fields contradicted that conclusion. The final judge contract now
defines score direction and arithmetic and rejects such an internally inconsistent result.

## Judge evidence

The accepted call used the reviewed project-pinned Codex CLI 0.147.0, tool-free read-only execution,
`gpt-5.6-sol`, maximum reasoning, 118,141 input tokens and 18,927 output tokens. Thread ID:
`01a065bb-0fdc-73a2-b173-4073b78231ce`. The structured result and run metadata are in this directory's
`v4` subdirectory. Earlier v2 and non-accepted v3 outputs remain immutable comparison evidence.

## Decision

`mlx-codex` is ready for an explicit full Pipeline test and is the accuracy/stability-preferred mode
for this source under the user's Codex text-only criterion. `openrouter-codex` remains the package
default for compatibility and for machines without the pinned 3.08 GB model; operators select local
mode explicitly. No claim of measured acoustic accuracy is made.

Final gates passed: `make lint` covered Ruff, formatting, strict mypy for 170 source files, Schema drift
and Web TypeScript; `make test` passed 935 Python tests, 58 Web tests, Mock browser E2E and real
API/leased-Worker/FFmpeg browser E2E.
