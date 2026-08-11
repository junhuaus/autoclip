# LiveClip status snapshot

Updated: 2026-08-11 12:06 CST
Current milestone: M8 independently verified PASS; Git publication in progress
Branch: `master` (must become `main` before push)
Latest local commit: `6afded7` (`docs: prepare OpenRouter ASR smoke fixture`)
Implementation baseline: `0a0b08a` (M7 OpenRouter ASR + Codex editor)

## Current user-visible outcome

The user-selected real chain is working on the repository input: OpenRouter `openai/whisper-large-v3` performs timestamped Chinese ASR, then the installed hardened Codex CLI scores bounded transcript candidates and creates title/Hook/reason/risk metadata. Review proxies are now clean 540×960 video clips with no LiveClip-generated title or captions. Editorial fields and editable caption cues are separate metadata; only an approved final render may burn text.

Run `make dev`, then open `http://127.0.0.1:5173`. Project `7.28` (`f91cb996f7534a6682aa5e5f01374b7b`) is `pending_review`; current generation-2 run `5ed80fea40ea48eca37fa10e8c4f1a06` is `completed` at 100% with 15 candidates.

Top clip:

- Clip ID: `4914ad2599c243be9582c31c9d526e34`
- Title: `没天赋也能学好唱歌`
- Video: `/Users/junhuaxu/Workspace/AGI/liveclip-ai/data/projects/f91cb996f7534a6682aa5e5f01374b7b/runs/g002/renders/proxies/4914ad2599c243be9582c31c9d526e34/r001/review.mp4`
- Contact sheet: `/Users/junhuaxu/Workspace/AGI/liveclip-ai/data/projects/f91cb996f7534a6682aa5e5f01374b7b/runs/g002/renders/proxies/4914ad2599c243be9582c31c9d526e34/r001/review-quality/contact-sheet.png`
- Media asset: `8ff4c680b9c7458ba3a2717f59147a0c`; Range request returned HTTP 206.

## Real-provider evidence

Generation 1 (`cf49e19a317d42eea50b720b1a5882f1`) processed read-only `input/7.28.mp4` (2,190,937,089 bytes, 2,780.437 seconds):

- OpenRouter: 33/33 successful requests, 0 retries, 2,942.016 overlap-inclusive audio seconds, 172.314 seconds summed request latency, USD 0.0735504 Provider-reported cost.
- Transcript: 233 absolute-time segments covering 0.284–2,780.256 seconds. Observed optional word timing was not reliably alignable, so word timing is truthfully `unavailable`; 0 word timestamps were invented.
- Rough candidates: 39.
- The restricted Codex sandbox could not initialize its nested app-server client (`Operation not permitted`), so generation 1 truthfully used deterministic degraded editing. This is retained as failure/recovery evidence, not claimed as LLM success.

Generation 2 (`5ed80fea40ea48eca37fa10e8c4f1a06`) proves recovery and the real editor:

- Reused 33/33 ASR caches from generation 1 under the then-current key-first identity; it created no new OpenRouter usage row and did not repay/reupload the chunks. A post-run canonical comparison confirmed all 33 tuples of chunk ID, interval, preprocessing key and actual audio-byte SHA-256 were identical. The reviewed v2 identity now binds both hashes; it is regression-tested but was not the code used during g2 and was not re-proven with another paid long run.
- Host Worker completed 39/39 Codex candidate calls, 0 failures. All 15 selected EditPlans have `degraded=false` and distinct Chinese titles/reasons.
- A dense 532 ms partial caption tail initially caused `EDIT_OUTPUT_INVALID`. The exact cause was fixed, 36 focused caption/edit/stage tests passed, and the same stage was manually retried from the 39 immutable Codex caches without another model call.
- 15/15 clean review proxies succeeded. The top proxy is H.264/AAC 540×960, 83.233 seconds versus 83.216 expected, 26,784,712 bytes; ffprobe, complete decode, black/edge/crop heuristics and automatic quality all passed.
- The top contact sheet was actually viewed: foreground/source-native livestream UI and blurred portrait background look coherent; no LiveClip title/caption overlay, black/blank frame or wrong orientation is visible. The committed automated report still records visual status pending; this observation is recorded here and in the ExecPlan without rewriting its committed Asset bytes.

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
- Added Alembic migrations `d2c59b8e4f31` (legacy Asset scope repair), `e7b14c2d9a60` (remove obsolete unique RenderJob task constraint) and `b81e3c7a4d20` (stale legacy text-bearing proxies). Current database is at `b81e3c7a4d20`; integrity/FK checks passed. Dirty render `709244f4fac84980ae81e1713bf2a79e` is stale, while all 15 current clean `7.28` proxies remain succeeded.
- Pre-migration backups remain under `data/projects/migration-backups/`; `liveclip-pre-b81e3c7a4d20.sqlite3` SHA-256 is `952d53edb1aa5b8773ed5895c5bd7372e84dc389acaeb755abf65f6b5793f4ee`.
- Product Spec, Solution, README, architecture, API/EditPlan notes, OpenRouter research/integration guide, ADR-010 and the Living ExecPlan are being updated to the real evidence.

## Validation already run for this worktree

- ASR-focused regressions: 103 passed.
- Clean-proxy/render-focused backend regressions: 73 passed; Web typecheck and component tests passed.
- Migration/proxy persistence regressions: 5 passed; pipeline-retry/migration set: 23 passed.
- Cross-generation transcript/stage/proxy set: 34 passed.
- Latest caption/edit/stage set: 36 passed; latest pipeline/caption set: 26 passed.
- Targeted Ruff formatting/checks and mypy on changed core modules pass.
- Real long run: generation 2 completed all six stages and 15 proxies; API/Web health is HTTP 200 and media Range is 206.
- Final host `make doctor`: READY with one expected text-filter warning; OpenRouter and Codex are ready, and an actual `h264_videotoolbox` H.264/AAC encode succeeded. A separate restricted-sandbox run truthfully exercised the successful `libx264` fallback.
- `make lint`: PASS after review repairs; Ruff and 169-file format gate, mypy over 105 source files, EditPlan Schema drift and TypeScript all pass.
- First full `make test`: 514/515 Python exposed a punctuation-preservation regression. After all independent-review repairs, the final complete gate is 527/527 Python, 13/13 Web, one Mock browser E2E and one real API/Worker/SQLite/FFmpeg browser E2E.
- Fresh `make demo`: `demo_20260811T032338_6f7414aa`, three candidates, `delivered`, immutable v001 ZIP. Proxy and final contact sheets were actually viewed; both reports record `viewed_passed`. Final is H.264/AAC 1080×1920, 12.000 seconds, 9,216,424 bytes, SHA-256 `0d9a4255b5d3dd0a5d0367652b5023355a6c509c6c432e9536561777e224adfe`; ZIP integrity passes.
- Fresh `make smoke-openrouter`: project `a8d1035f78c24b28b392308bdde33d05`, run `0b523cdc396148b5af6d36cc5559edfe`; two OpenRouter requests + one Codex request, zero retries, 95.104 audio seconds, USD 0.0023776 Provider cost, non-degraded title `高音别硬喊：强混声与假声区别`, no Mock evidence.
- Independent Product-Spec M8 verifier: `PASS`, P0=0/P1=0/P2=0 after reproducing and closing optional-word, cache identity, legacy proxy and CLI metadata gaps. Its focused gate passed 138 tests; final commit is allowed after the staged secret/scope check.

## Not yet verified in M8

- Final staged-scope/secret check, local commit, branch rename to `main`, remote add and push.
- Representative 2–4 hour Apple M3 peak memory/runtime/disk. The actual available source is 46:20 and the host is Apple M2.
- Whether the Groq-specific vocabulary hint improves a chosen target term; ordinary real success proves transport, not terminology accuracy.
- A paid real cross-generation run under the new dual-hash cache identity. It is deliberately not repeated because historical g1/g2 manifests were post-verified byte-identical and same/different-byte behavior is covered locally.

## Security and worktree state

- The local OpenRouter credential is present only in ignored environment and was accepted by the real service. Its value has never been printed or persisted by this work.
- `OPENROUTER_SETUP.md` is explicitly ignored and must never be staged. Likewise never stage `.env`, `.env.local`, `input/`, databases, media, caches, delivery output or migration backups.
- Source video remains a read-only reference and was not modified.
- Local API/Worker/Web are currently stopped after test isolation. The Browser plugin still exposes no attached controllable browser; checked host-Chrome E2E passed independently.
- The worktree contains intentional M8 source/test/doc changes plus three new migration files, the renderer contract module and focused tests. No remote is configured yet.

## Next concrete task

Inspect the complete diff/staged scope, exclude `OPENROUTER_SETUP.md` and all ignored secrets/input/generated data, commit locally, rename the branch to `main`, add the exact user-specified SSH remote and push without force. Restart `make dev` afterward so the review Web remains available.

## Resume instructions

Read `AGENTS.md`, `docs/PRODUCT_SPEC.md`, `docs/SOLUTION.md`, `.agent/PLANS.md`, `docs/exec-plans/liveclip-v1.md` and this file. Run `git status --short --branch`, `git log -5 --oneline`, verify the database project/run facts above, and continue with the first command in “Next concrete task.” Preserve `OPENROUTER_SETUP.md` and all ignored user/generated data. Do not repeat the paid 46:20 ASR run or misattribute generation-1 deterministic editing as Codex success.
