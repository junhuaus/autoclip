# SD-7 Product Spec clause classification

Prepared 2026-09-15 UTC by a read-only inspection of the accepted source,
retained artifacts and append-only QA evidence. Writing this report did not
mutate product code, user data or source media. Baseline: branch
`liveclip-v2/loop-engineering`, HEAD
`6009b23859564b2bfdc193eee366afd990b9ef5d`, accepted SD-5 B2 source. The
worktree intentionally contains the accepted delivery as uncommitted files.

Classification vocabulary:

- **Implemented**: a current production path exists.
- **Tested**: deterministic tests passed on the accepted source.
- **Actually run**: the named behavior ran on this delivery host with retained evidence.
- **Unverified**: required evidence has not run or cannot be inferred.
- **Gap**: an acceptance input or result is missing.
- **Risk**: behavior is supported but present evidence has a material operational limit.

The accepted-source formal full suite passed 2425 Python and 78 Web tests,
Mock Chrome and two real-service Chrome scenarios under Runner QA
`20260914T230500Z-a9b9`; [SD-5 B2 acceptance](stable-delivery-sd5b2-accepted-2026-09-14.md)
binds the source and artifacts. Original-worktree full QA
`20260914T235154Z-d6b3` remains **Unverified** until its command ends and a
correlated append-only report exists. A test request is never counted as PASS.

## Product outcome and runtime

| Clause | Classification | Direct evidence and limit |
| --- | --- | --- |
| Local-first Chinese clipping flow through immutable Delivery | Implemented, Tested, Actually run on synthetic media | Original `make demo` QA `20260914234410Z-3c86`; B2 real-service fixtures. Real Chinese source-to-Delivery is still Unverified. |
| Apple Silicon, Python 3.11+, Node LTS, FFmpeg/SQLite | Actually run, Risk | Original Doctor QA `20260914234349Z-3478`: Apple Silicon, Python 3.12.13, Node 22.11.0, FFmpeg 8.1.2 and WAL-safe SQLite. One current host only. |
| M3 performance target and 2–4 hour input | Gap | Current host/input inventory has no distinct 2h or 4h source; supplied `8-30.ts` is about 110m34s. |
| Independent Worker and shared application rules | Implemented, Tested | `tests/integration/test_completion_worker.py`, `test_completion_api_recovery.py`, `test_cli_completion_watch.py`; accepted B2 browser evidence. |

## Doctor and ingest boundary

| Clause | Classification | Direct evidence and limit |
| --- | --- | --- |
| Doctor inspects host, tools, filters, fonts, SQLite, paths and Provider presence | Implemented, Actually run | QA `20260914234349Z-3478`; no credential value was printed. |
| Real tiny VideoToolbox encode with libx264 fallback | Actually run | Same Doctor QA reports VideoToolbox PASS. FFmpeg lacks `drawtext`/`subtitles`; tested Pillow raster fallback is the disclosed host Risk. |
| Absolute regular file under strict allowed root; reject traversal/symlink/nonexistent | Tested | `tests/unit/test_secure_files.py`, `tests/unit/test_settings.py`, `tests/integration/test_cli_pipeline.py`. |
| Source stays read-only and outside generated data | Tested, Actually inspected | Supplied source full SHA-256/inode/size/duration inventory; original and 30-second MLX smoke left its hash unchanged. Full pipeline has not run on it. |
| ffprobe requires audio and video; stream hash and persist identity | Tested | `tests/unit/test_media_process.py`, `test_secure_files.py`, pipeline integration suite. |
| Isolated Project directories and duplicate-fingerprint behavior | Tested | `tests/integration/test_persistent_mock_pipeline.py`, `test_completion_identity.py`, source identity/unit suites. |
| Recheck mutation before dependent work/publication | Tested | source mutation, Asset and Delivery regressions in integration/unit suite; formal retained-package verifier. |

## Preprocess and ASR

| Clause | Classification | Direct evidence and limit |
| --- | --- | --- |
| FFmpeg mono extraction, bounded overlapping chunks, byte/hash/cache manifest and silence signals | Tested, Actually run on synthetic media | Pipeline/ASR tests and Demo QA. Real 5-minute excerpt/full source is pending. |
| Cancellation and partial-file safety | Tested | pipeline/Worker/media cancellation and secure publication tests. |
| Mock, OpenAI, OpenRouter and MLX provider implementations | Implemented, Tested | provider unit suites; implementation under `src/liveclip/providers/asr/`. Current cloud capability is Unverified. |
| Pinned full-precision local MLX snapshot, deterministic one-worker decoding and no implicit download/fallback | Tested, Actually called on real-source slice | QA `20260914234828Z-5d3d`: pinned `openai/whisper-large-v3`, nine segments, inference 13.369s. This is no accuracy score. |
| Chinese text, segment times, word-time honesty and overlap conversion | Tested; Actually run partially | MLX smoke returned Chinese segments and explicitly `word_timing_status=unavailable`. Human transcript accuracy is Unverified. |
| Bounded retry classification, cache-before-peer-failure and concurrency rules | Tested | `tests/unit/test_openai_asr.py`, `test_openrouter_asr.py`, `test_mlx_asr.py`, stage handler and recovery suites. No current real rate-limit/retry event. |
| Durable transcript JSON/SRT/segments | Tested, Actually run on synthetic Demo | Demo and retained browser artifacts. Real full-source transcript is historical evidence only. |
| Cloud smoke does not fall back to Mock | Tested, Unverified with current account | No regenerated OpenRouter Key has been established. Previously exposed Key is prohibited and unused. |

## Semantic processing and EditPlan

| Clause | Classification | Direct evidence and limit |
| --- | --- | --- |
| Algorithm A deterministic candidates/fallback | Implemented, Tested | candidate and integration suites; synthetic Demo. |
| Versioned Algorithm B/semantic_global/semantic_windowed behavior and immutable historical replay | Implemented, Tested | SD-1A–SD-3 acceptance reports; semantic global/windowed/lineage/transport suites. |
| High-recall Discovery, Boundary Review and candidate-level Global Review with complete deterministic validation | Implemented, Tested | `tests/unit/test_semantic_global.py`, `test_semantic_profiles.py`, semantic validation/lineage/runtime suites. |
| Mini-lesson Fragment/Link/Chain/Boundary/Global stages and 90–300-second gate | Implemented, Tested | SD-1B/SD-2/SD-3 reports and mini-lesson/semantic lineage tests. Real current mini-lesson output is Unverified. |
| One bounded complete-error repair, no silent A/Mock fallback, durable call/audit evidence | Implemented, Tested | SD-1A repair/status/multipart reports and semantic executor/recovery suites. |
| OpenAI Responses, Codex CLI and Mock LLM; strict output, no tools, untrusted transcript | Implemented, Tested; Codex channel Actually run | tool-disabled Codex smoke QA `20260914234954Z-ee7d` on synthetic Chinese text. Real-source editorial quality is Unverified. |
| Model/prompt/request/usage persistence and configurable optional prices | Tested | structured provider, semantic invocation and database suites. Current tariff/cost is Unverified. |
| Strict EditPlan bounds/enums/no executable model fields; immutable revisions | Implemented, Tested | schema, EditPlan, rendering, review and prompt-injection tests; `make lint` schema check QA `20260914233622Z-09a1`. |

## Rendering, selection and Delivery

| Clause | Classification | Direct evidence and limit |
| --- | --- | --- |
| 1080×1920 single-layer clean H.264/AAC master plus independent SRT | Implemented, Tested, Actually run on synthetic Demo | QA `20260914234410Z-3c86`; 12-second master SHA-256 is in the accepted report. |
| Validated `shell=False` FFmpeg argv, cancellation, atomic no-overwrite publication and encoder fallback | Tested | renderer/media/secure-file/Worker suites. |
| ffprobe, duration/size/aspect, full decode, frames/contact sheet and overlay safety evidence | Actually run on synthetic Demo | Full decode, ZIP and contact sheet inspection passed. No real content/audio assessment. |
| CLI/Web edit, select, rerender and current-revision fencing | Implemented, Tested | review/delivery integration tests, 78 Web tests and real Chrome scenarios. |
| Grounded Hook/keyword timing and honest segment precision | Tested | review export/API/semantic metadata tests. Real content usefulness is Unverified. |
| Immutable vNNN package, safe filenames/ZIP, index, checksums and selected-current-only contents | Implemented, Tested, Actually run on synthetic artifacts | Demo and B2 four retained-package audits, including full MP4 decode and wrong-producer rejection. |

## Persistence, security and operator commands

| Clause | Classification | Direct evidence and limit |
| --- | --- | --- |
| Separate state machines and required durable records | Implemented, Tested | state transition, migration, repository and completion suites. |
| WAL/FK/busy timeout, atomic claims, leases, heartbeats, fencing, retry/cancel/recovery | Implemented, Tested | task queue, action recovery, completion Worker and process-level integration suites. Disposable operational recovery drill pending. |
| Project membership isolation and environment-only credentials | Tested | authorization, identity/API/media and real Chrome denial scenarios. |
| Source/artifacts local; MLX uploads no audio; LLM receives bounded text; secrets redacted | Implemented, Tested; local ASR Actually run | provider/config/log tests and local smoke. Codex cloud receives bounded text; no audio. |
| Model output cannot control code, paths, SQL, commands or filtergraphs | Tested | schema/security/FFmpeg/provider test suites; Runner remains fixed deny-default. |
| `make setup` from a fresh installation | Unverified | Existing local dependencies were reused; no clean-machine install ran. |
| `make doctor`, `make lint`, `make demo`, `make loop-doctor` | Actually run | QA `3478`, `09a1`, `3c86`, `7e5f` respectively. |
| `make test` on original worktree | Unverified while running | QA request `20260914T235154Z-d6b3`; classify only after report. Formal accepted-source Runner full test already PASS. |
| `make dev` startup and Ctrl-C cleanup | Tested; fresh operator run Unverified | Dev script and E2E exercise the components; no release-specific foreground `make dev` drill yet. |
| Cloud smoke when valid configuration is available | Unverified, conditional | No acceptable regenerated Key evidence; old exposed Key remains ineligible. |
| `make clean-demo` safe deletion boundary | Tested | Demo cleanup/security tests. A post-evidence cleanup is optional because retained Demo artifacts are acceptance evidence. |
| Database backup/restore, integrity and no-clobber | Tested; operator drill pending | `tests/integration/test_database_backup.py`; prepared ignored CLI drill has no result yet. |
| README, Product Spec, Solution, API, recovery, ADR, ExecPlans and STATUS maintained | Implemented, Risk | Files exist and B2 docs were CAS-published. Recovery review fixed stale `auto`/`resume` and Worker command wording. Full fresh-operator walkthrough remains pending. |

## Acceptance decision at this checkpoint

Engineering implementation through SD-5 B2 is accepted. Local host readiness,
lint, synthetic Demo, fixed-Runner control plane, bounded MLX ASR and one
tool-disabled Codex call have actual evidence. Release engineering is still
open while original full test, operational recovery and database restore
drills are unfinished. Product quality/performance acceptance is blocked by
missing frozen human labels/listening, a current real source-to-Delivery run,
repeated per-profile evidence, a second generalization source and distinct
2h/4h inputs. Both Completion presets remain experimental.

Next verifier action: consume only the correlated result for QA
`20260914T235154Z-d6b3`, then append separate recovery and backup/restore QA
requests. Update rows from Unverified only after each result exists.
