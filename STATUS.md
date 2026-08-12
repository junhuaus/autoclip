# LiveClip status snapshot

Updated: 2026-08-12 11:21 CST
Current milestone: M12 candidate-focused horizontal highlight list complete and published
Branch: `main` tracking `origin/main`
Latest implementation commit: `4e81d6c` (`ui: focus review on highlight moments`)
Implementation baseline: `0a0b08a` (M7 OpenRouter ASR + Codex editor)

## Current user-visible outcome

The user-selected real chain is working on the repository input: OpenRouter `openai/whisper-large-v3` performs timestamped Chinese ASR, then the installed hardened Codex CLI scores bounded transcript candidates and creates title/Hook/reason/risk metadata. Layout is no longer model-selected. Every review/final render uses one direct source-video layer with center crop; blurred backgrounds and duplicated/shrunken foreground composition are prohibited. Review proxies are clean 540×960 clips with no LiveClip-generated title or captions. Editorial fields and editable caption cues are separate metadata; only an approved final render may burn text. The board is now named `高光时刻` and reviews the existing candidates—there are no A/B variants—as a single-column list. Each full-width desktop row places video left and editorial content right; its complete subtitle block is last. The persisted current-revision Hook is shown as audience-oriented `高光语句`; ASR-grounded timed terms are explicitly `编辑关键词` for editor navigation. Atomic multi-candidate approve/reject remains intact. The redundant full-livestream `源视频绝对时间 / 转写` panel is not rendered or requested by the Web; persisted transcript/ASR and the REST transcript endpoint remain available for processing and external consumers.

The local API/Worker/Web are running. Open `http://127.0.0.1:5173`. Project `7.28` (`f91cb996f7534a6682aa5e5f01374b7b`) is `pending_review`; current generation-3 run `634c68f9d0b24c99b16ddac8d14ddfd7` is `completed` at 100% with 15 candidates. Generations 1 and 2 no longer appear in the active database or project run directory.

Top clip:

- Clip ID: `73ab6116e49d4d9d837d469274aa47d5`
- Title: `KTV唱歌前的快速热身法`
- Video: `/Users/junhuaxu/Workspace/AGI/liveclip-ai/data/projects/f91cb996f7534a6682aa5e5f01374b7b/runs/g003/renders/proxies/73ab6116e49d4d9d837d469274aa47d5/r002/s-baa64c00a3180462/t-215fc4b619474c48/review.mp4`
- Contact sheet: `/Users/junhuaxu/Workspace/AGI/liveclip-ai/data/projects/f91cb996f7534a6682aa5e5f01374b7b/runs/g003/renders/proxies/73ab6116e49d4d9d837d469274aa47d5/r002/s-baa64c00a3180462/t-215fc4b619474c48/quality/contact-sheet.png`
- Media asset: `8fae25df095446c696651440bd42be03`; a 1,024-byte Range request returned HTTP 206 with the correct MP4 Content-Range and ETag.

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
- The historical pre-M9 top contact sheet was actually viewed and exposed the blurred portrait composition later rejected by the user. That proxy is no longer active and cannot be adopted under the no-blur contract.

Current generation 3 (`634c68f9d0b24c99b16ddac8d14ddfd7`) is a fresh user-requested rerun under the final dual-hash cache contract:

- All six stages succeeded. OpenRouter completed 33/33 fresh calls with 0 retries, 2,942.016 overlap-inclusive audio seconds, 117.0 seconds summed request latency and USD 0.0735504 Provider-reported cost. It produced 248 absolute-time transcript segments covering 0.284–2,780.256 seconds.
- Codex completed 41/41 calls with 0 failures/retries, 374,878 input tokens, 222,208 cached input tokens and 13,974 output tokens. Candidate generation produced 41 rough candidates; all 15 selected current EditPlans have `degraded=false`.
- All 15 clean 540×960 review proxies succeeded. All 15 reports record automatic checks and full decode as passed; maximum duration error is 32 ms. The top H.264/AAC proxy is 58.567 seconds and 18,686,049 bytes.
- The historical pre-M9 generation-3 contact sheet exposed the inconsistent blurred-background composition. Migration `c91f4e2a7b63` marked that proxy stale; the current replacement is the single-layer proxy recorded below.
- Before cleanup, SQLite was checkpointed and copied to `data/projects/migration-backups/liveclip-pre-g1-g2-prune-20260811.sqlite3` (SHA-256 `95fc7e26786dd30319b606ef07f29c2ad9b2bf23d2fc739f6d3abd6f2be7310f`). Generations 1 and 2 had no reviews or deliveries. One transaction deleted their 2 PipelineRuns and 168 Asset rows with cascades; integrity and foreign-key checks passed. Their 393 MiB of files are recoverably isolated at `data/projects/.trash/f91cb996f7534a6682aa5e5f01374b7b-g001-g002-20260811T125244/` and are not visible to LiveClip. The source file is unchanged by size, mtime, inode and persisted SHA-256.
- After the user reported stale entries in the project list, 10 development/Smoke/failed projects were audited: none had reviews or deliveries. Backup `data/projects/migration-backups/liveclip-pre-old-project-prune-20260811.sqlite3` (SHA-256 `cbcee9b26c4c5e1be53c6ba16d11c595ea0f6f843c44bc6fd73899db9d1ccf00`) preserves the pre-cleanup state. One transaction removed 10 projects, 10 runs and 108 Assets; their 96 MiB of files are isolated at `data/projects/.trash/old-test-projects-20260811T130500/`. Post-restart `/api/v1/projects` returns exactly the single current `7.28` project.

## M9 no-blur evidence

- The real data confirmed the issue: 10/15 current plans selected `vertical_blur_background`; five selected `center_crop`.
- Layout is removed from `EditorialSuggestionWire` and `editing_v2`; OpenAI/Codex can no longer choose composition. Deterministic fallback fixes layout to `center_crop`.
- FFmpeg has one scale-to-fill/center-crop video branch. `boxblur` and the background/foreground split were removed; a historical blur request raises before argv construction.
- Renderer contract is `ffmpeg-renderer-v3.no-blur`, manual spec schema is 4, and Pipeline clean-proxy contract is `clean-proxy-v2.no-blur-v1`. Migration `c91f4e2a7b63` staled all 15 prior proxies.
- The pre-migration DB backup is `data/projects/migration-backups/liveclip-pre-no-blur-c91f4e2a7b63.sqlite3`, SHA-256 `905d073bd9005d2441dfb022bc02ad6f8ee92473173c17010a19cd7aa171d7aa`.
- Ten affected candidates now have immutable revision 2; the five already-direct candidates remain revision 1. All 15 current plans are `center_crop`, and all 15 new Schema-4 proxy renders succeeded.
- All 15 quality reports pass automatic checks and complete decode at 540×960; maximum duration error is 32 ms. The top proxy is H.264/AAC, 58.567 seconds and 19,449,931 bytes.
- A former-blur contact sheet and a former-center contact sheet were both actually viewed. They consistently show a single direct source crop with no blurred canvas, duplicated/shrunken foreground, blank frame, wrong orientation or LiveClip-generated text.
- Legacy blur revisions remain readable for audit but cannot be approved, exposed as render actions or enqueued. Any human edit creates an immutable `center_crop` revision before approval/rendering can continue.

## M10 grounded multi-candidate review evidence

- Scope is intentionally the 15 existing candidates. No A/B scheme, variant/group entity or duplicate render was introduced.
- The current transcript remains run `634c68f9d0b24c99b16ddac8d14ddfd7`: 248 persisted segments, zero persisted words and `word_timing_status=unavailable`. M10 did not call ASR or the editorial model. Read-only Provider evidence remained `74 api_usage rows / SUM(request_count)=74` across metadata requests.
- The live clip list returns 15 clean videos, 90 current-revision caption cues and 34 keyword occurrences. All 34 use explicit `segment` precision; an independent cross-check proved each normalized phrase occurs in its exact persisted TranscriptSegment, each returned source interval equals that segment, and every segment is fully contained by the current clip.
- Batch review accepts 1–100 unique clips and validates Project generation, current revision and active layout before any write. Decisions, Delivery invalidation and the Idempotency-Key record share one `BEGIN IMMEDIATE`; one conflict rolls back the entire batch. A real two-item request with one deliberately wrong revision returned 409 and persisted zero decisions.
- Web retries preserve the exact failed body/key and first reconcile server state. Dirty drafts, changed revisions or missing clips disable an old retry. Dirty candidates are removed from selection, editor writes are locked while a batch is in flight, and successful detail snapshots update open-editor caches.
- Historical M10 acceptance opened `http://127.0.0.1:5173` on the actual `7.28` Project and observed 15 videos, 15 subtitle sections, 15 keyword sections, 34 keyword buttons and no A/B text. Its old DOM order was `video → subtitles/keywords → card body`; M12 intentionally supersedes that presentation with `video + content → subtitles last`. Clicking `热身` moved only the first video from 0 to 55.144 seconds; batch selection enabled approval; an unsaved title draft disabled that clip's batch selection.
- Actual viewed board/card screenshots are `/Users/junhuaxu/Workspace/AGI/liveclip-ai/data/projects/f91cb996f7534a6682aa5e5f01374b7b/runs/g003/validation/m10/review-board.png` and `.../first-card.png`. The fixed Web page header crossed the element screenshot but is not burned into media. Extracted same-time source/proxy frames under that directory prove the proxy is a direct center crop with no blur or LiveClip-generated text.
- Independent M10 review returned `PASS`, P0=0/P1=0/P2=0 after closing word-provenance and four batch/draft/cache retry races.

## M11 Web transcript-panel removal evidence

- Removed the complete-livestream `TranscriptPanel` and its styles from the review workspace. The Web no longer calls `GET /projects/{project_id}/transcript` while loading a Project.
- Candidate-local subtitles, grounded keyword ranges and the candidate-detail transcript remain directly associated with the video being reviewed. Pipeline stage progress still truthfully reports the Chinese transcription stage.
- A component regression installs a transcript endpoint spy and proves both that `源视频绝对时间`/the `转写` heading are absent and that the endpoint receives zero requests.
- Both checked M11 Chrome flows explicitly asserted the full panel was absent and per-card subtitles/keywords remained visible. The real-backend success screenshot was actually viewed and showed Pipeline progress followed directly by the review board; M12 subsequently renamed that heading to `高光时刻`.
- No ASR, LLM, source-media, Project, candidate or render state changed. This is a Web presentation/query reduction only.

## M12 horizontal high-impact review evidence

- The review heading is `高光时刻`; candidates render as semantic ordered-list rows rather than a multi-column card grid.
- Desktop CSS and Chrome geometry checks prove video is left of editorial content. The row's subtitle section is a direct final sibling after the main horizontal grid; narrow screens collapse to one column without changing DOM order.
- `ClipSummary` now includes the exact current-revision persisted EditPlan Hook. The Web labels it `高光语句` with `推荐上屏`; this is distinct from timed `编辑关键词`, which are labelled `仅供编辑定位`.
- The restarted real API returned 15/15 non-empty existing Hooks for `7.28`, including `KTV唱歌前做十个蹲起，能快速找状态吗？`. No ASR/LLM call, Project revision or render change occurred.
- The checked real-backend Chrome screenshot was actually viewed: layout, hierarchy and subtitle-last order are correct; the clean proxy remains no-text and no-blur.

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
- Added Alembic migrations `d2c59b8e4f31` (legacy Asset scope repair), `e7b14c2d9a60` (remove obsolete unique RenderJob task constraint), `b81e3c7a4d20` (stale legacy text-bearing proxies) and `c91f4e2a7b63` (stale all pre-no-blur/removed-layout renders). Current database is at `c91f4e2a7b63`; integrity/FK checks pass and only generation 3 plus its 15 succeeded no-blur proxies remain active for `7.28`.
- Added deterministic read-only keyword occurrences, current-revision captions/keywords on clip list/detail DTOs, and one atomic revision-fenced batch review service/REST endpoint.
- Added per-card subtitle/keyword seek, batch selection/approve/reject, exact idempotent retry, dirty-draft fencing and list/detail cache reconciliation to the Web review board.
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
- M9 gates: `make lint` PASS; final-tree `make test` PASS with 531 Python, 13 Web, one Mock Chrome E2E and one real FastAPI/SQLite lease Worker/FFmpeg Chrome E2E. After the review-only migration coverage repair, 30 targeted tests pass. Independent M9 re-review is `PASS`, P0=0/P1=0/P2=0; the reviewer also viewed all 15 current contact sheets.
- M10 final `make doctor`: READY with two expected warnings. Host VideoToolbox failed this invocation and the required actual `libx264` fallback encode succeeded; OpenRouter and Codex readiness passed without displaying secrets.
- M10 final `make lint`: PASS; Ruff, 173-file format gate, mypy over 106 source files, EditPlan schema sync and TypeScript typecheck all pass.
- M10 final host-permission `make test`: PASS with 540 Python tests, 19 Web tests, one Mock Chrome E2E and one real FastAPI/SQLite lease Worker/FFmpeg Chrome E2E. A preceding restricted launch failed before assertions with macOS Chrome `SIGABRT/EPERM`; no assertion was suppressed, and the exact complete host run exited 0.
- Real Chrome/CDP acceptance on the unchanged `7.28` data passed all DOM/count/seek/selection/dirty checks and the viewed media comparison described above.
- M11 final `make lint`: PASS; Ruff, 173-file format gate, mypy over 106 source files, EditPlan schema sync and TypeScript typecheck all pass.
- M11 final `make test`: PASS with 540 Python tests, 20 Web tests, one Mock Chrome E2E and one real FastAPI/SQLite lease Worker/FFmpeg Chrome E2E. The real-flow delivery screenshot was actually viewed after the run.
- M12 final `make lint`: PASS; Ruff/format, mypy over 106 source files, EditPlan schema sync and TypeScript typecheck all pass.
- M12 final `make test`: PASS with 540 Python tests, 21 Web tests, one Mock Chrome E2E and one real FastAPI/SQLite lease Worker/FFmpeg Chrome E2E. Both browser flows assert horizontal geometry, high-impact copy, editor-keyword naming and subtitle-last order.

## Not yet verified in M8

- Representative 2–4 hour Apple M3 peak memory/runtime/disk. The actual available source is 46:20 and the host is Apple M2.
- Whether the Groq-specific vocabulary hint improves a chosen target term; ordinary real success proves transport, not terminology accuracy.
- A second generation reusing generation-3 caches under the new dual-hash cache identity. Generation 3 itself exercised the final identity with fresh paid calls; same/different-byte reuse behavior remains covered locally without paying for a fourth long run.

## Security and worktree state

- The local OpenRouter credential is present only in ignored environment and was accepted by the real service. Its value has never been printed or persisted by this work.
- `OPENROUTER_SETUP.md` is explicitly ignored and must never be staged. Likewise never stage `.env`, `.env.local`, `input/`, databases, media, caches, delivery output or migration backups.
- Source video remains a read-only reference and was not modified.
- Local API/Worker/Web are currently running at `127.0.0.1:8765` and `127.0.0.1:5173`. The user's existing Chrome debugging session at port 9222 opened and exercised the actual review board; no browser extension was installed or required.
- The 9-file M11 implementation scope passed whitespace and credential-pattern checks. Commit `df8b8db` is pushed to `origin/main`; ignored local secrets/input/generated data and E2E screenshots were not committed.
- The 18-file M12 source/test/document scope passed whitespace, forbidden-path and credential-pattern checks. Commit `4e81d6c` is pushed to `origin/main`; input, secrets, database, generated media and browser evidence remain ignored and uncommitted.

## Next concrete task

Use the Web `高光时刻` list to review the 15 current `7.28` clips, final-render approved revisions and create a new immutable Delivery. Do not rerun ASR/LLM unless the source or content-analysis requirements actually change.

## Resume instructions

Read `AGENTS.md`, `docs/PRODUCT_SPEC.md`, `docs/SOLUTION.md`, `.agent/PLANS.md`, `docs/exec-plans/liveclip-v1.md` and this file. Run `git status --short --branch`, `git log -5 --oneline`, verify generation 3 and the 15 clips through the API, and continue with the first command in “Next concrete task.” Preserve all ignored user/generated data, including validation screenshots and explicit cleanup backup/trash unless the user asks for permanent reclamation. Do not repeat the paid 46:20 ASR/LLM run. New engineering work starts after the completed M12 checkpoint rather than reopening verified tasks without evidence.
