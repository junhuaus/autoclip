# LiveClip status snapshot

Updated: 2026-08-11 13:08 CST
Current milestone: M8 complete, independently verified and published; user-requested generation-3 rerun and old-generation cleanup complete
Branch: `main` tracking `origin/main`
Latest implementation commit: `2bbdd4f` (`milestone: complete real-provider clean-proxy acceptance`)
Implementation baseline: `0a0b08a` (M7 OpenRouter ASR + Codex editor)

## Current user-visible outcome

The user-selected real chain is working on the repository input: OpenRouter `openai/whisper-large-v3` performs timestamped Chinese ASR, then the installed hardened Codex CLI scores bounded transcript candidates and creates title/Hook/reason/risk metadata. Review proxies are now clean 540×960 video clips with no LiveClip-generated title or captions. Editorial fields and editable caption cues are separate metadata; only an approved final render may burn text.

The local API/Worker/Web are running. Open `http://127.0.0.1:5173`. Project `7.28` (`f91cb996f7534a6682aa5e5f01374b7b`) is `pending_review`; current generation-3 run `634c68f9d0b24c99b16ddac8d14ddfd7` is `completed` at 100% with 15 candidates. Generations 1 and 2 no longer appear in the active database or project run directory.

Top clip:

- Clip ID: `73ab6116e49d4d9d837d469274aa47d5`
- Title: `KTV唱歌前的快速热身法`
- Video: `/Users/junhuaxu/Workspace/AGI/liveclip-ai/data/projects/f91cb996f7534a6682aa5e5f01374b7b/runs/g003/renders/proxies/73ab6116e49d4d9d837d469274aa47d5/r001/review.mp4`
- Contact sheet: `/Users/junhuaxu/Workspace/AGI/liveclip-ai/data/projects/f91cb996f7534a6682aa5e5f01374b7b/runs/g003/renders/proxies/73ab6116e49d4d9d837d469274aa47d5/r001/review-quality/contact-sheet.png`
- Media asset: `a7b6fa9867bf4cb6b01734e6fc8b3b69`; a 1,024-byte Range request returned HTTP 206 with the correct MP4 Content-Range and ETag.

## Real-provider evidence

Historical generation 1 (`cf49e19a317d42eea50b720b1a5882f1`) processed read-only `input/7.28.mp4` (2,190,937,089 bytes, 2,780.437 seconds). It was removed from the active database after generation 3 passed:

- OpenRouter: 33/33 successful requests, 0 retries, 2,942.016 overlap-inclusive audio seconds, 172.314 seconds summed request latency, USD 0.0735504 Provider-reported cost.
- Transcript: 233 absolute-time segments covering 0.284–2,780.256 seconds. Observed optional word timing was not reliably alignable, so word timing is truthfully `unavailable`; 0 word timestamps were invented.
- Rough candidates: 39.
- The restricted Codex sandbox could not initialize its nested app-server client (`Operation not permitted`), so generation 1 truthfully used deterministic degraded editing. This is retained as failure/recovery evidence, not claimed as LLM success.

Historical generation 2 (`5ed80fea40ea48eca37fa10e8c4f1a06`) proved recovery and the real editor. It was also removed from the active database after generation 3 passed:

- Reused 33/33 ASR caches from generation 1 under the then-current key-first identity; it created no new OpenRouter usage row and did not repay/reupload the chunks. A post-run canonical comparison confirmed all 33 tuples of chunk ID, interval, preprocessing key and actual audio-byte SHA-256 were identical. The reviewed v2 identity now binds both hashes; it is regression-tested but was not the code used during g2 and was not re-proven with another paid long run.
- Host Worker completed 39/39 Codex candidate calls, 0 failures. All 15 selected EditPlans have `degraded=false` and distinct Chinese titles/reasons.
- A dense 532 ms partial caption tail initially caused `EDIT_OUTPUT_INVALID`. The exact cause was fixed, 36 focused caption/edit/stage tests passed, and the same stage was manually retried from the 39 immutable Codex caches without another model call.
- 15/15 clean review proxies succeeded. The top proxy is H.264/AAC 540×960, 83.233 seconds versus 83.216 expected, 26,784,712 bytes; ffprobe, complete decode, black/edge/crop heuristics and automatic quality all passed.
- The top contact sheet was actually viewed: foreground/source-native livestream UI and blurred portrait background look coherent; no LiveClip title/caption overlay, black/blank frame or wrong orientation is visible. The committed automated report still records visual status pending; this observation is recorded here and in the ExecPlan without rewriting its committed Asset bytes.

Current generation 3 (`634c68f9d0b24c99b16ddac8d14ddfd7`) is a fresh user-requested rerun under the final dual-hash cache contract:

- All six stages succeeded. OpenRouter completed 33/33 fresh calls with 0 retries, 2,942.016 overlap-inclusive audio seconds, 117.0 seconds summed request latency and USD 0.0735504 Provider-reported cost. It produced 248 absolute-time transcript segments covering 0.284–2,780.256 seconds.
- Codex completed 41/41 calls with 0 failures/retries, 374,878 input tokens, 222,208 cached input tokens and 13,974 output tokens. Candidate generation produced 41 rough candidates; all 15 selected current EditPlans have `degraded=false`.
- All 15 clean 540×960 review proxies succeeded. All 15 reports record automatic checks and full decode as passed; maximum duration error is 32 ms. The top H.264/AAC proxy is 58.567 seconds and 18,686,049 bytes.
- The top generation-3 contact sheet was actually viewed: the portrait foreground and blurred-background layout are coherent, source-native livestream UI remains, and there is no LiveClip-generated title/caption, blank frame or wrong orientation. The immutable report remains truthfully `visual_inspection_status=pending` because it was committed before this external viewing.
- Before cleanup, SQLite was checkpointed and copied to `data/projects/migration-backups/liveclip-pre-g1-g2-prune-20260811.sqlite3` (SHA-256 `95fc7e26786dd30319b606ef07f29c2ad9b2bf23d2fc739f6d3abd6f2be7310f`). Generations 1 and 2 had no reviews or deliveries. One transaction deleted their 2 PipelineRuns and 168 Asset rows with cascades; integrity and foreign-key checks passed. Their 393 MiB of files are recoverably isolated at `data/projects/.trash/f91cb996f7534a6682aa5e5f01374b7b-g001-g002-20260811T125244/` and are not visible to LiveClip. The source file is unchanged by size, mtime, inode and persisted SHA-256.
- After the user reported stale entries in the project list, 10 development/Smoke/failed projects were audited: none had reviews or deliveries. Backup `data/projects/migration-backups/liveclip-pre-old-project-prune-20260811.sqlite3` (SHA-256 `cbcee9b26c4c5e1be53c6ba16d11c595ea0f6f843c44bc6fd73899db9d1ccf00`) preserves the pre-cleanup state. One transaction removed 10 projects, 10 runs and 108 Assets; their 96 MiB of files are isolated at `data/projects/.trash/old-test-projects-20260811T130500/`. Post-restart `/api/v1/projects` returns exactly the single current `7.28` project.

## Implemented in the current worktree

- Hardened OpenAI/OpenRouter ASR response compatibility while preserving strict segment timing and explicit unavailable word timing.
- Default ASR chunk size changed to 90 seconds.
- Added same-Project cross-generation ASR cache reuse with correct historical call attribution; the final v2 identity requires both a valid preprocessing key and content SHA-256 and rejects same-key/different-byte fallback reuse.
- Added renderer text modes `none` and `title_and_captions`; pipeline/manual proxies use `none`, final/Demo delivery uses reviewed overlays.
- Added migration and query-time fencing so legacy text-bearing proxies become `stale` and cannot be presented as clean; queued legacy jobs are cancelled and running jobs receive cancellation.
- Added Web wording/tests for clean proxy plus separate high-value metadata.
- Added CLI Hook and clip-relative caption metadata output for both candidate listing and review results.
- Added caption splitting/dense-boundary behavior and a versioned EditPlan pipeline contract.
- Added bounded payload-free local validation diagnostics and same-run implementation-repair retry for `UNEXPECTED_STAGE_ERROR`/`EDIT_OUTPUT_INVALID`.
- Added Alembic migrations `d2c59b8e4f31` (legacy Asset scope repair), `e7b14c2d9a60` (remove obsolete unique RenderJob task constraint) and `b81e3c7a4d20` (stale legacy text-bearing proxies). Current database is at `b81e3c7a4d20`; after the user-requested old-generation cleanup, integrity/FK checks pass and only generation 3 plus its 15 succeeded clean proxies remain active for `7.28`.
- Pre-migration backups remain under `data/projects/migration-backups/`; `liveclip-pre-b81e3c7a4d20.sqlite3` SHA-256 is `952d53edb1aa5b8773ed5895c5bd7372e84dc389acaeb755abf65f6b5793f4ee`.
- Product Spec, Solution, README, architecture, API/EditPlan notes, OpenRouter research/integration guide, ADR-010 and the Living ExecPlan are being updated to the real evidence.

## Validation already run for this worktree

- ASR-focused regressions: 103 passed.
- Clean-proxy/render-focused backend regressions: 73 passed; Web typecheck and component tests passed.
- Migration/proxy persistence regressions: 5 passed; pipeline-retry/migration set: 23 passed.
- Cross-generation transcript/stage/proxy set: 34 passed.
- Latest caption/edit/stage set: 36 passed; latest pipeline/caption set: 26 passed.
- Targeted Ruff formatting/checks and mypy on changed core modules pass.
- Fresh real long rerun: generation 3 completed all six stages, 33 OpenRouter calls, 41 Codex calls and 15 validated proxies. API health is `ok`, Web is HTTP 200, media Range is HTTP 206 and the project-list API returns exactly one project after both cleanup passes.
- Final host `make doctor`: READY with one expected text-filter warning; OpenRouter and Codex are ready, and an actual `h264_videotoolbox` H.264/AAC encode succeeded. A separate restricted-sandbox run truthfully exercised the successful `libx264` fallback.
- `make lint`: PASS after review repairs; Ruff and 169-file format gate, mypy over 105 source files, EditPlan Schema drift and TypeScript all pass.
- First full `make test`: 514/515 Python exposed a punctuation-preservation regression. After all independent-review repairs, the final complete gate is 527/527 Python, 13/13 Web, one Mock browser E2E and one real API/Worker/SQLite/FFmpeg browser E2E.
- Fresh `make demo`: `demo_20260811T032338_6f7414aa`, three candidates, `delivered`, immutable v001 ZIP. Proxy and final contact sheets were actually viewed; both reports record `viewed_passed`. Final is H.264/AAC 1080×1920, 12.000 seconds, 9,216,424 bytes, SHA-256 `0d9a4255b5d3dd0a5d0367652b5023355a6c509c6c432e9536561777e224adfe`; ZIP integrity passes.
- Fresh `make smoke-openrouter`: project `a8d1035f78c24b28b392308bdde33d05`, run `0b523cdc396148b5af6d36cc5559edfe`; two OpenRouter requests + one Codex request, zero retries, 95.104 audio seconds, USD 0.0023776 Provider cost, non-degraded title `高音别硬喊：强混声与假声区别`, no Mock evidence.
- Independent Product-Spec M8 verifier: `PASS`, P0=0/P1=0/P2=0 after reproducing and closing optional-word, cache identity, legacy proxy and CLI metadata gaps. Its focused gate passed 138 tests; final commit is allowed after the staged secret/scope check.

## Not yet verified in M8

- Representative 2–4 hour Apple M3 peak memory/runtime/disk. The actual available source is 46:20 and the host is Apple M2.
- Whether the Groq-specific vocabulary hint improves a chosen target term; ordinary real success proves transport, not terminology accuracy.
- A second generation reusing generation-3 caches under the new dual-hash cache identity. Generation 3 itself exercised the final identity with fresh paid calls; same/different-byte reuse behavior remains covered locally without paying for a fourth long run.

## Security and worktree state

- The local OpenRouter credential is present only in ignored environment and was accepted by the real service. Its value has never been printed or persisted by this work.
- `OPENROUTER_SETUP.md` is explicitly ignored and must never be staged. Likewise never stage `.env`, `.env.local`, `input/`, databases, media, caches, delivery output or migration backups.
- Source video remains a read-only reference and was not modified.
- Local API/Worker/Web are currently running at `127.0.0.1:8765` and `127.0.0.1:5173`. The Browser plugin still exposes no attached controllable browser in this session; HTTP/API/Range behavior was checked directly, and the previously checked host-Chrome E2E remains the browser evidence for the unchanged code.
- The 53-file M8 implementation scope passed cached whitespace and secret-format scans with zero forbidden paths or key-pattern hits. Commit `2bbdd4f` is pushed to `git@github.com:junhuaus/AGI-Live-Clip.git` on `main`; ignored local secrets/input/generated data were not committed.

## Next concrete task

Run `make dev`, open `http://127.0.0.1:5173`, review the 15 real `7.28` candidates, revise title/bounds/captions as needed, approve selected clips, render finals and create the next immutable Delivery.

## Resume instructions

Read `AGENTS.md`, `docs/PRODUCT_SPEC.md`, `docs/SOLUTION.md`, `.agent/PLANS.md`, `docs/exec-plans/liveclip-v1.md` and this file. Run `git status --short --branch`, `git log -5 --oneline`, verify generation 3 and the 15 clips through the API, and continue with the first command in “Next concrete task.” Preserve all ignored user/generated data, including the explicit cleanup backup/trash unless the user asks for permanent reclamation. Do not repeat the paid 46:20 ASR run. New engineering work starts after the completed M8 checkpoint rather than reopening verified tasks without evidence.
