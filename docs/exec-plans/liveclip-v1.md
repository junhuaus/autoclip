# LiveClip v1 Living ExecPlan

This plan follows `.agent/PLANS.md`. It is the durable implementation and recovery record for the product contract in `docs/PRODUCT_SPEC.md` and the decisions in `docs/SOLUTION.md`.

## Purpose / Big Picture

A user on Apple Silicon macOS can import a local Chinese livestream by absolute path, process it through a recoverable local pipeline with OpenRouter/OpenAI or deterministic Mock providers, review and revise accurate vertical highlight clips from CLI/Web, and create an immutable verified ZIP delivery. Completion is observable through real playable media, database state, HTTP/UI flows and reproducible commands—not interface stubs.

## Context and Orientation

The repository began empty on 2026-08-03 with an initialized Git repository, `master`, no commits/remotes and a clean worktree. M0 discovery found macOS 26.4.1 on Apple M2/24 GB; the target remains M3. Default Python 3.9 is unsupported and the existing Miniconda 3.12 is x86_64, so setup will install a project-local native arm64 Python 3.12 through uv. Default Node 26 is not LTS; `/usr/local/bin/node` 22.11.0 is arm64 LTS.

The host FFmpeg 8.1.2 has the media/layout/audio filters, AAC, libx264 and VideoToolbox needed except `subtitles`/`drawtext`. ADR-003 chooses Pillow-rendered RGBA text with FFmpeg overlay. VideoToolbox actually encoded on the host but returns OSStatus -12903 in the Codex sandbox; libx264 succeeds there.

Important paths:

- Product contract: `docs/PRODUCT_SPEC.md`
- Architecture: `docs/SOLUTION.md`, `docs/architecture.md`, `docs/adr/`
- Python package: `src/liveclip/`
- Entry adapters: `apps/api`, `apps/worker`, `apps/web`, `src/liveclip/cli`
- Tests: `tests/unit`, `tests/integration`, `tests/e2e`
- Runtime data: ignored `data/demo` and `data/projects`

## Scope

All M0–M6 requirements remain in scope. Milestones may close independently, but no later feature is treated as complete merely because a type or route exists. M0–M6 are locally committed after independent review. M7 added the installed Codex CLI as a real editorial provider and OpenRouter Whisper Large V3 as the selected real ASR. M8 is the user-authorized real-input acceptance and presentation correction: process `input/7.28.mp4` with both real providers, make review proxies clean while keeping editorial descriptions separate, repair discovered legacy/recovery defects, and close with reproducible gates and Git publication. M9 makes the user's no-blur requirement a system invariant and replaces every active long-video proxy with one direct source-video crop. M10 adds multi-candidate batch review plus subtitle and truthfully timed keyword navigation beneath each clean proxy. The user explicitly declined A/B variants; M10 operates only on the existing candidate set and reuses the existing transcript without another ASR call. M11 removes the redundant full-livestream transcript panel from the Web review workspace while retaining persisted ASR/transcript data, the REST transcript endpoint and candidate-local subtitles/keywords. M12 renames the board `高光时刻`, uses one full-width horizontal row per clip, promotes the persisted Hook to `高光语句`, labels timed terms as editor-only keywords and makes subtitles the final row section. M13 adds a self-contained offline-review package for current clean proxies and their complete editorial metadata without conflating it with formal approved Delivery state. M14 makes the home page a member-scoped video-editor Project workspace with durable owner/editor/reviewer membership, local per-user authentication and server-side resource isolation.

## Architecture Summary

CLI/API/Worker call shared application commands/queries and a fixed pipeline executor. Pure domain models enforce canonical integer-millisecond timing, state transitions, immutable EditPlan revisions and delivery eligibility. SQLAlchemy/SQLite, local filesystem/FFmpeg, OpenAI/Mock and delivery are adapters behind ports. Tasks use fenced leases. Artifacts are validated immutable nodes published atomically. The Web is an API client.

## Milestones and progress

### M0 — Discovery, Solution and foundation

- [x] 2026-08-03 Inspect empty repository, Git state and existing conflicts.
- [x] 2026-08-03 Run three read-only agents: Explorer, Architecture Critic, Verifier/Documentation Researcher.
- [x] 2026-08-03 Inspect OS/runtime/SQLite/FFmpeg/fonts and run host/sandbox codec spikes.
- [x] 2026-08-03 Verify current official OpenAI Audio/Responses documentation without a paid call.
- [x] 2026-08-03 Create Product Spec, Solution, research notes, ADR baseline and architecture diagrams.
- [x] 2026-08-03 Create ExecPlan rules, Living ExecPlan, AGENTS and initial STATUS.
- [x] 2026-08-03 Create Python/project command skeleton and native arm64 3.12 environment.
- [x] 2026-08-03 Spike Pillow Chinese RGBA overlays through FFmpeg and visually inspect output.
- [x] 2026-08-03 Run M0 targeted lint/tests and initial read-only milestone review.
- [x] 2026-08-03 Fix all six initial review findings and add regression coverage (27 tests pass, including exact environment-name behavior).
- [x] 2026-08-03 Run post-fix read-only M0 re-review; verdict PASS with no residual blocker.
- [x] 2026-08-03 Create local M0 commit `136d8bd` after staged scope and whitespace checks.

### M1 — Mock minimum end-to-end vertical slice

- [x] 2026-08-03 Generate copyright-free H.264/AAC Demo video with visual motion, audio and measured silence.
- [x] 2026-08-03 Securely ingest, ffprobe and stream-hash source.
- [x] 2026-08-03 Extract mono compressed audio into three overlapped chunks and emit recoverable silence/chunk manifest.
- [x] 2026-08-03 Mock Chinese transcript with absolute times, cache identity and overlap deduplication.
- [x] 2026-08-03 Generate three deterministic candidates and Mock-edited strict EditPlans.
- [x] 2026-08-03 Render and validate three 540×960 proxies with captions/title.
- [x] 2026-08-03 Create a human title revision, preserve history and prove old proxy stale.
- [x] 2026-08-03 Reapprove revision 2 and render/validate 1080×1920 final plus relative SRT.
- [x] 2026-08-03 Atomically create v001 manifest and path-safe delivery.zip with verified media hash.
- [x] 2026-08-03 Generate and actually view final contact sheet; record `viewed_passed` and UTC time.
- [x] 2026-08-03 Run `make demo` twice; each succeeds with a distinct project and required absolute paths.
- [x] 2026-08-03 Add 68 unit plus one real integration test; lint/type and all 69 tests pass.
- [x] 2026-08-03 Run independent read-only M1 review; fix the clean provenance gap and receive `VERDICT: PASS` with 70 tests green.
- [x] 2026-08-03 Create local M1 checkpoint `cfc8889` and record its hash.

### M2 — Domain persistence, Pipeline, CLI and Worker

- [x] 2026-08-03 Implement 20 persistent entities, central transition tables and SQLAlchemy repositories/UoW.
- [x] 2026-08-03 Add a drift-checked Alembic initial schema plus WAL/FK/busy-timeout/FULL integration and an unsafe-runtime gate.
- [x] 2026-08-03 Implement atomic Task claim, random lease token, heartbeat, expiry/crash recovery, bounded retry and generation fences.
- [x] 2026-08-03 Implement real six-stage Mock handlers with committed Asset checkpoints, exact downstream fingerprints, cancellation and resume.
- [x] 2026-08-03 Implement pipeline CLI `run --wait`, `status`, `clips`, and `worker` through shared services. Review/rerender/delivery CLI commands remain paired with their M3 application services; product scope is unchanged.
- [x] 2026-08-03 Implement independent Worker and foreground ownership/polling with a real competition integration test proving one execution per stage.
- [x] 2026-08-03 Replace long FFmpeg validation/extraction/render calls with process-group cancellation; cancellation never publishes a successful artifact.
- [x] 2026-08-03 Run migration round-trip/drift/integrity checks, strict lint/types and 204 local tests including real persistent media and CLI chains.
- [x] 2026-08-03 Complete two independent read-only review passes, fix every P0/P1 finding and receive final `PASS` with 82 focused and 204 full tests green.
- [x] 2026-08-03 Create scoped local M2 milestone commit `09a6f10`; record it in the documentation checkpoint.

### M3 — REST API, Web review and versioned delivery

- [x] 2026-08-03 Freeze initial M3 ownership: main Agent owns shared schema/migration/services/API integration; three existing Agents perform disjoint read-only backend, REST-security and Web planning audits before implementation delegation.
- [x] 2026-08-03 Implement all required `/api/v1` routes, strict DTOs, truthful 202 replay status, atomic idempotency, stable errors, Bearer auth and loopback CORS.
- [x] 2026-08-03 Implement allowlisted generated-asset serving with scoped Delivery ZIPs, short-lived path/purpose-bound HMAC URLs, single Range and reopen-time file identity fences.
- [x] 2026-08-03 Implement React/Vite review console and complete UI states.
- [x] 2026-08-03 Implement atomic title/boundary/caption revisions, decisions, epoch-driven stale/rerender, immutable delivery versions and matching CLI commands.
- [x] 2026-08-03 Add API, component and Playwright core E2E tests; rerun the real Chrome flow after review fixes.
- [x] 2026-08-03 Complete independent M3 review and fix every P0/P1; Reviewer returned PASS after lint, 233 Python tests, 11 Web tests, 30 focused regressions and whitespace validation.
- [x] 2026-08-03 Create scoped local M3 milestone commit `f707e90` and record its evidence.

### M4 — Real OpenAI providers

- [x] 2026-08-03 Lock `openai==2.52.0` and contract-test its Audio and Responses request/response shapes without network calls.
- [x] 2026-08-03 Implement timestamp-capable OpenAI ASR, usage, bounded retries, hardened per-chunk cache and crash resume.
- [x] 2026-08-03 Implement Responses strict parsing, refusal/incomplete, exactly one repair, all-candidate scoring and deterministic degradation.
- [x] 2026-08-03 Version Prompt/provider/schema contracts in strict Pipeline config v2 and persist request/usage/cancellation evidence.
- [x] 2026-08-03 Implement strict no-Mock `make smoke-cloud` preflight, execution and pure false-success evidence validation.
- [x] 2026-08-03 Run cloud smoke preflight: `not_run` with every missing prerequisite; no key is configured and no paid request was attempted.
- [x] 2026-08-03 Complete two independent review passes, fix every P1/P2, and receive final `PASS` with 121 focused tests and no residual finding.
- [x] 2026-08-03 Diagnose the post-review intermittent FFmpeg timeout, bound raster/filter/encoder resources, preserve timeout evidence and pass three repeated real Demo integration runs.
- [x] 2026-08-03 Pass final M4 gates: `make lint`, 328 Python tests, 11 Web tests, post-fix `make demo`, full decode and actual contact-sheet inspection.
- [x] 2026-08-03 Create scoped local M4 commit `476ad89` after staged scope and whitespace checks.

### M5 — Long media, recovery, security and quality hardening

- [x] 2026-08-04 Exercise multi-chunk streaming, bounded process cancellation, lease-loss recovery, heartbeat and spawned-process crash recovery.
- [x] 2026-08-04 Test traversal/symlink/source replacement, committed-Asset tampering, media Range, ZIP endpoint/member replacement, cleanup ownership and redaction adversaries.
- [x] 2026-08-04 Run repository `input/7.28.mp4` read-only through the six-stage Mock pipeline: 2.19 GB/46:20, five overlapping chunks, 28.83 seconds, about 18 MB project data; preserve the explicit limitation that no available fixture is 2–4 hours and peak RSS was unavailable in this sandbox.
- [x] 2026-08-04 Cover real VFR, 90°/270° rotation, non-first/default audio selection, font identity and bounded caption/layout fanout.
- [x] 2026-08-04 Bind exact render bytes across ffprobe/full decode/frame extraction/publication, generate and inspect contact sheets, enforce black-frame/safe-area/crop checks and bound/redact diagnostics.
- [x] 2026-08-04 Complete two independent M5 reviews, repair all findings, receive final `PASS`, pass `make lint`, 428 Python tests, 11 Web tests and a fresh delivered Demo, then create local checkpoint `7c145ec`.

### M6 — Independent acceptance and documentation

- [x] 2026-08-04 Complete README, API/EditPlan/architecture/operations/troubleshooting documentation and a tracked drift-checked EditPlan v1 JSON Schema; documentation re-review returns PASS.
- [x] 2026-08-04 Run frontend type checks and both Chrome E2E paths; inspect the real-flow success screenshot.
- [x] 2026-08-04 Add an isolated browser-to-real-FastAPI/leased-Worker/SQLite/FFmpeg E2E and prove six stages, signed Range, revision stale, current final and v001 ZIP/delivered through UI plus persisted evidence.
- [x] 2026-08-04 Run repeatable `make setup`, `make doctor`, `make lint`, `make test` and a fresh `make demo`; all required local gates pass.
- [x] 2026-08-04 Run strict cloud-smoke preflight: `not_run` with provider/key/allowed-root prerequisites named; no DB/client/Mock false success.
- [x] 2026-08-04 Run independent read-only Verification Agent against every Product Spec item; final verdict `PASS`, zero P0/P1/P2.
- [x] 2026-08-04 Resolve all earlier review findings, rerun affected/full checks and record final artifact paths/results; no final-verifier gap remains.
- [x] 2026-08-04 Create scoped local implementation checkpoint `60283ba` and the following final documentation checkpoint; report truthful Git state.

### M7 — Codex editorial provider and truthful real-content readiness

- [x] 2026-08-04 Correct the earlier long-input claim: it used Mock ASR/LLM and proves streaming mechanics, not content understanding.
- [x] 2026-08-04 Verify current official Codex non-interactive/auth/schema/sandbox contracts and the absence of a documented audio-input contract.
- [x] 2026-08-04 Implement a tool-disabled, stdin-only, strict-schema, cancellable Codex CLI LLM adapter with bounded evidence, one repair and deterministic degradation.
- [x] 2026-08-04 Add explicit `openai-codex` and `mock-codex` modes; make `openai-codex` the normal default while retaining pure OpenAI and explicit Mock modes.
- [x] 2026-08-04 Run a real saved-ChatGPT-login `make smoke-codex`; record request/usage/structured EditPlan evidence without Mock fallback.
- [x] 2026-08-04 Add safe Provider readiness to Doctor/API/CLI/Web, block full-run creation when real ASR/LLM prerequisites are missing, and visibly label Mock ASR.
- [x] 2026-08-04 Pass the initial focused gate: 25 Python tests, 12 Web tests, Ruff, mypy and TypeScript.
- [x] 2026-08-05 Read the user-supplied OpenRouter setup, preserve the exposed-Key warning, and verify current official STT/model/error/app-attribution documentation.
- [x] 2026-08-05 Add `openrouter-codex` as the new user-selected default: strict official endpoint/model, Whisper Large V3 JSON `input_audio` timestamp ASR, documented Groq vocabulary option, generation/usage evidence, readiness, Doctor/API/Web/CLI and `make smoke-openrouter`.
- [x] 2026-08-05 Repair the first M7 review findings: exhaustive version-pinned Codex tool disabling and tool-event rejection, executable/profile byte fingerprint, repair-cancellation evidence, mandatory smoke thread/token evidence, proxy credential removal, and readiness-safe idempotency replay. Git history proves `run_scope` already existed when Pipeline schema v2 was introduced, so no fictitious v2 migration is added.
- [x] 2026-08-05 Pass 74 focused Python regressions, full mypy, Web TypeScript and 13 Vitest tests; run a post-hardening real Codex smoke with thread `019fd196-1428-7b10-a814-422f64f4f030`, input 8,899/output 105 tokens and a non-degraded validated plan.
- [x] 2026-08-05 Run full lint/test/Demo gates plus controlled and real-backend host-Chrome checks. The browser plugin exposed no attached instance, so Provider startup state was verified through health HTTP plus component tests rather than claiming an MCP visual inspection.
- [x] 2026-08-05 Pass the independent M7 re-review with zero P0/P1/P2 after repairing generation provenance/validation, documented vocabulary transport, strict usage validation and oversized/truncated Codex JSONL fail-closed handling.
- [x] 2026-08-05 Create scoped local M7 implementation checkpoint `0a0b08a`; update this plan and STATUS without staging the user-owned setup file.
- [x] 2026-08-05 Prepare and fully decode a bounded 90-second real-ASR fixture from source seconds 300–390 at `input/.liveclip-smoke/7.28-300s-90s.mp4`; record its SHA-256, prove the source stat identity did not change, and run the exact smoke preflight. It stopped `not_run` before upload/billing because no regenerated Key exists, with no Mock substitution.
- [ ] After a newly regenerated Key is configured locally, run `make smoke-openrouter` on a short sample and then the authorized 46:20 `input/7.28.mp4`; never use the previously exposed Key. This external verification may remain `not_run`, but cannot be called successful.

### M8 — Real long-video acceptance and clean review proxies

- [x] 2026-08-05 Run a 90-second slice through real OpenRouter ASR and the hardened Codex editor; persist generation/usage/thread evidence and one non-degraded EditPlan.
- [x] 2026-08-05 Process all 2,780.437 seconds of `input/7.28.mp4` read-only through OpenRouter: 33/33 chunks, 233 merged segments, 2,942.016 overlap-inclusive seconds and USD 0.0735504 Provider-reported cost.
- [x] 2026-08-05 Preserve valid segment transcripts when optional upstream word timing is missing, malformed, sentence-mirrored or unaligned; record words as unavailable instead of fabricating them.
- [x] 2026-08-05 Add and apply two narrow legacy-database migrations: repair missing Asset scope columns and remove the obsolete unique constraint on `render_jobs.task_id`; retain pre-migration backups and pass integrity/FK checks.
- [x] 2026-08-05 Implement `none` and `title_and_captions` renderer modes. Pipeline/manual review proxies are clean; final renders retain approved text. Update Web metadata presentation and regression tests.
- [x] 2026-08-05 Add same-Project cross-generation ASR cache reuse. Generation 2 restored 33/33 chunks under the then-current key-first identity without a new OpenRouter usage row; a later canonical manifest comparison confirmed all 33 preprocessing keys and byte SHA values were equal. The reviewed v2 identity now binds both fields and fails closed on partial identity; its new filename contract is regression-tested but was not re-proven through another paid long run.
- [x] 2026-08-05 Run generation 2 under the host Worker so nested Codex can initialize: 39/39 calls succeeded, 15/15 selected EditPlans are non-degraded and 15/15 clean proxies passed automatic validation/full decode.
- [x] 2026-08-05 Repair the one observed dense partial-caption boundary case, add regression tests and manually retry the same edit stage from immutable Codex caches without another model call.
- [x] 2026-08-05 Inspect the top real contact sheet: portrait composition and blurred background are present, there is no LiveClip title/caption overlay, and no black/blank/wrong-orientation defect is visible. HTTP Range returns 206 for the proxy.
- [x] 2026-08-11 Run final `make doctor`, `make lint`, `make test`, `make demo` and configured real-provider smoke. Doctor is READY; post-review lint passes over 169 files/105 typed modules; post-review `make test` passes 527 Python + 13 Web + two browser flows; fresh Demo is delivered and both proxy/final contact sheets were viewed/recorded; 90-second OpenRouter→Codex smoke succeeds without Mock/degradation.
- [x] 2026-08-11 Run an independent read-only M8/Product-Spec verification and fix every evidenced finding. The final verdict is `PASS`, P0=0/P1=0/P2=0, after optional-word truthfulness, dual-hash cache identity, legacy-proxy fencing and CLI metadata repairs; its focused gate passed 138 tests.
- [x] 2026-08-11 Update STATUS/this plan, create scoped implementation commit `2bbdd4f`, rename to `main`, add `git@github.com:junhuaus/AGI-Live-Clip.git` and push without staging secrets/input/generated data. The 53-file cached scope had zero forbidden paths and zero common credential-pattern hits.
- [x] 2026-08-11 At the user's request, run a fresh generation 3 from the unchanged full `input/7.28.mp4`: 33/33 OpenRouter calls, 41/41 Codex edits, 15/15 non-degraded selected plans and 15/15 clean validated proxies succeeded. View the top contact sheet and verify HTTP Range playback.
- [x] 2026-08-11 After generation 3 passed, checkpoint and back up SQLite, remove generations 1/2 from the active database in one foreign-key-safe transaction, and move their exact run directories to a recoverable project-local trash directory. Integrity/FK checks and post-restart API/Web checks pass; only generation 3 remains active.
- [x] 2026-08-11 Remove the 10 remaining development/Smoke/failed projects reported in the Web list after proving they have zero reviews and deliveries. Back up SQLite, isolate their exact directories, delete 10 projects/10 runs/108 Assets transactionally, and verify the restarted project-list API returns only current `7.28`.

### M9 — Single-layer rendering with no blurred backgrounds

- [x] 2026-08-11 Confirm the reported inconsistency in the real generation-3 data: 10 selected plans used `vertical_blur_background` while five used `center_crop`.
- [x] 2026-08-11 Remove layout from the real LLM wire schema and version prompts as `editing_v2`; make deterministic fallback and all new active plans system-owned `center_crop`.
- [x] 2026-08-11 Delete the FFmpeg blur/duplicated-foreground branch, reject the legacy value before argv construction, and version renderer/manual/pipeline proxy contracts as no-blur.
- [x] 2026-08-11 Add migration `c91f4e2a7b63` to stale pre-no-blur proxies and any render tied to the removed layout, with safe queued/running task cancellation.
- [x] 2026-08-11 Back up the real database, apply the migration, create immutable center-crop revisions for the 10 affected candidates, and render all 15 proxies under `ffmpeg-renderer-v3.no-blur`.
- [x] 2026-08-11 Verify all 15 current plans are center crop, all 15 new proxies pass automatic/full-decode validation, Range returns 206, and viewed former-blur/former-center contact sheets both show one consistent source layer without generated text.
- [x] 2026-08-11 Pass `make lint`, 531 Python tests, 13 Web tests, Mock Chrome E2E and real API/SQLite-lease Worker/FFmpeg Chrome E2E.
- [x] 2026-08-11 Complete independent read-only M9 review, fix its one P2 migration-test gap, receive final `PASS` with P0=0/P1=0/P2=0, and publish scoped implementation checkpoint `c14c910` without generated data or credentials.

### M10 — Multi-candidate review metadata and controls

- [x] 2026-08-11 Confirm product scope: no A/B variants and no repeat ASR for `7.28`.
- [x] 2026-08-11 Audit current review/list, caption, transcript timing and Web video-control contracts.
- [x] 2026-08-11 Add deterministic grounded keyword occurrences with explicit word/segment precision.
- [x] 2026-08-11 Add atomic revision-fenced batch review application service and REST endpoint.
- [x] 2026-08-11 Show each card's subtitles and keywords directly below its video with per-card seek controls.
- [x] 2026-08-11 Add multi-select approve/reject controls and observable conflict/error/retry states.
- [x] 2026-08-11 Run targeted Python/Web tests, verify current `7.28` through the API and host Chrome, and obtain an independent read-only `PASS`.
- [x] 2026-08-11 Update recovery evidence, create source/docs/tests-only checkpoint `cb7be17`, and push it to `origin/main` without local media, generated data or credentials.

### M11 — Candidate-focused review workspace

- [x] 2026-08-12 Remove the complete-livestream `源视频绝对时间 / 转写` panel and its unused styles from the Web review workspace.
- [x] 2026-08-12 Stop the Project workspace from requesting the full transcript while retaining ASR, persisted transcript data and the REST endpoint.
- [x] 2026-08-12 Keep per-candidate subtitles, grounded keyword time ranges and candidate-detail transcript controls beneath the relevant video.
- [x] 2026-08-12 Add component and both Chrome-flow regressions proving the full panel is absent and candidate-local metadata remains visible.
- [x] 2026-08-12 Pass `make lint` and complete `make test`: 540 Python, 20 Web, Mock Chrome and real FastAPI/SQLite Worker/FFmpeg Chrome flows.
- [x] 2026-08-12 Actually view the real-backend delivered screenshot and publish implementation checkpoint `df8b8db` without generated media, input or credentials.

### M12 — Horizontal high-impact moment list

- [x] 2026-08-12 Rename the review section and its loading/empty/batch language from candidates to `高光时刻`.
- [x] 2026-08-12 Expose the exact current-revision persisted EditPlan Hook in the list DTO and render it as audience-oriented `高光语句`.
- [x] 2026-08-12 Rename grounded timed terms to `编辑关键词` and state that they are only for editor navigation.
- [x] 2026-08-12 Replace the responsive multi-card grid with one semantic full-width row per highlight: video left, content right, subtitles last and full-width.
- [x] 2026-08-12 Add API equality, component semantic-order and both Chrome geometry/content regressions.
- [x] 2026-08-12 Restart the real local services, prove 15/15 existing Hooks without a Provider call, pass lint/full test, and actually view the real-browser screenshot.
- [x] 2026-08-12 Create and publish scoped M12 checkpoint `4e81d6c` without input, secrets, database, E2E output or generated media.

### M13 — Portable offline review package

- [x] 2026-08-12 Add shared `OfflineReviewPackageService` and `liveclip export-review PROJECT_ID --zip`; formal Delivery eligibility/state remains unchanged.
- [x] 2026-08-12 Atomically version and publish a self-contained package with clean MP4 proxies, SRT, per-clip/combined Markdown descriptions, JSON manifest, checksum file, offline HTML and verified ZIP.
- [x] 2026-08-12 Add regression coverage for metadata/offline HTML/ZIP/hash/version behavior and fail-closed proxy tampering.
- [x] 2026-08-12 Export real `7.28` generation 3. Immutable v001/v002 preserve pre-fence history; final v2-contract v003 contains 15 videos, 15 SRTs, 15 descriptions, 90 cues and 34 grounded keyword ranges. Every disk/ZIP member and all 15 full decodes pass; manifest SHA-256 is `7f52624db226c71cf3d661b3db30066f67810545424328264a7b837de6f07f25`, ZIP SHA-256 is `5851d26406258838a140f0ece4f5be44bb8a1ff325189055f26bc10d754eb645`.
- [x] 2026-08-12 Add transactionally captured run/generation/epoch/revision/review/RenderJob/producer Task/Asset lineage; fence immediately before and after atomic publication, withdraw a raced version, and safely recover strictly named crash-orphan attempts.
- [x] 2026-08-12 Prove the configured maximum of 100 clips/305 ZIP members, eight database mutation classes, state-preserving export, post-publish withdrawal and orphan/symlink safety. Final gates: lint PASS, 554 Python + 21 Web + both browser E2Es PASS, then 16 post-gate targeted tests PASS.
- [x] 2026-08-12 ffprobe and fully decode all 15 packaged H.264/AAC 540×960 videos with zero error; Project remains `pending_review`.
- [ ] Complete a browser visual/playback check of the file-only `index.html`. Strict Browser retries exposed no attached browser (`[]`) and found no registered Codex Chrome extension/native host; the skill prohibited fallback browser control, so visual/playback confirmation remains truthfully blocked until that plugin connection is restored.

### M14 — Collaborative video-editor project workspace

- [x] 2026-08-13 Replace the diagnostic-heavy home page with a concise “我的项目” editor dashboard: personal workload counts, search, workflow filters, owner/member/role context and one next action per Project.
- [x] 2026-08-13 Add `WorkspaceUser`, `ProjectMember` and `Project.owner_id`; migrate every existing Project to the default local administrator without deleting or rebuilding media/domain state.
- [x] 2026-08-13 Add distinct environment-only member Bearer tokens, authenticated session identity and caller-scoped idempotency; no credential enters SQLite, logs, responses or the frontend bundle.
- [x] 2026-08-13 Enforce membership for Project lists and every Project/run/clip/render/Delivery route, hide inaccessible resources as not-found, and make membership administration owner-only.
- [x] 2026-08-13 Add a Project member panel for owner/editor/reviewer roles while preserving the horizontal `高光时刻`, `高光语句`, editor-keyword and subtitle-last review workflow.
- [x] 2026-08-13 Apply migration `d31a6e9f4b72` to the real database; Alembic drift, SQLite integrity and foreign-key checks pass, and existing `7.28` remains the sole visible Project for `local-admin`.
- [x] 2026-08-13 Pass `make lint`, 559 Python tests, 23 Web tests, Mock Chrome E2E and real FastAPI/leased-Worker/SQLite/FFmpeg Chrome E2E. The real E2E used an isolated temporary Mock-AI Project and did not mutate or reprocess `7.28`.
- [x] 2026-08-13 Inspect the latest host-Chrome dashboard and delivered-workspace screenshots. The dashboard hierarchy, filters and Project card are visually coherent; strict in-app Browser discovery still returns no registered browser (`[]`), so no MCP-control claim is made.
- [x] 2026-08-13 Create scoped M14 implementation checkpoint `d40ec81` without secrets, input, database, generated media or screenshots; publish it and the following status checkpoint to `origin/main`.

## Work breakdown and file ownership

The main agent exclusively edits shared schemas, dependencies/locks, Alembic head, `AGENTS.md`, `STATUS.md`, `.agent/PLANS.md`, this plan, `docs/SOLUTION.md` and cross-module integration. Read-only reviewers never edit. Parallel implementation, when used, receives disjoint directories and may not edit these shared files.

M1 dependency order:

1. Foundation/config/domain types and tests.
2. Media ingest/preprocess and renderer primitives.
3. Mock providers/candidates/EditPlan.
4. Demo application service and review revision flow.
5. Delivery/quality validation.
6. CLI/Make target integration and real artifact inspection.

Active M1 file ownership (recorded before delegation):

- `m1_media`: only `src/liveclip/media/models.py`, `ingest.py`, `preprocess.py`, and `tests/unit/test_ingest.py`, `test_preprocess.py`.
- `m1_content`: only `src/liveclip/providers/asr/base.py`, `mock.py`, `src/liveclip/providers/llm/base.py`, `mock.py`, `src/liveclip/pipeline/transcript.py`, `candidates.py`, and `tests/unit/test_transcript.py`, `test_candidates.py`.
- Main Agent: shared domain schemas, Settings/dependencies, Demo/review/render/delivery integration (including `src/liveclip/delivery/package.py`), CLI/Makefile, all persistent planning documents and cross-module tests. A third write delegation was not started because the agent thread limit was reached.

Agents may read the full repository but may not modify another owner's files. The main Agent integrates and reviews all returned changes before any test or checkpoint claim.

M2 introduces persistence behind the M1 service ports rather than creating an alternate pipeline. M3 and M4 can proceed on separate adapters after M2; M5 integrates both.

Active M2 file ownership (recorded before delegation):

- Main Agent: `domain/state_transitions.py`, shared ORM/entity schemas, repositories/UoW, Task queue integration, Alembic head, application services, CLI/Worker integration, dependencies and persistent planning documents.
- `m1_media`: only `src/liveclip/db/engine.py` and `tests/unit/test_db_engine.py`; implement SQLite connection/transaction configuration without editing Settings, ORM models or migrations.
- `m1_content`: read-only M2 state/lease/idempotency/crash-recovery acceptance matrix; no file changes.
- `verifier_researcher`: read-only primary-source check of current SQLAlchemy 2, Alembic and SQLite behaviors relevant to `BEGIN IMMEDIATE`, pragmas and atomic claim; no file changes.

No delegated M2 task may modify shared schemas, migrations, dependencies or status documents. Main integrates returned evidence before declaring any persistence behavior.

M2 integrated shape:

1. `PipelineService` creates a Project, immutable PipelineRun config, six visible StageRuns, and only the dependency-free ingest Task.
2. `StageTaskRunner` is shared by foreground CLI and Worker. It claims a fenced lease, starts a stage, heartbeats on an independent connection, executes external I/O without a DB transaction, and commits through one repository boundary.
3. Each handler reserves Assets before I/O, writes under an attempt identity, validates and atomically publishes bytes, commits Asset hashes, then completes the Stage. Only then is the next Task created from the actual upstream output plus config fingerprint.
4. The persistent Mock chain stores source metadata, audio chunks, transcript rows, rough candidates, selected immutable EditPlan revisions, captions and real validated proxy RenderJobs.
5. CLI review/rerender/deliver commands intentionally remain unimplemented until M3 supplies the shared revision/render/delivery services; adapters will not grow duplicate domain logic to make M2 appear complete.
6. Asset scope is derived inside the reservation/commit transaction from TaskAttempt → Task → PipelineRun → Project. Caller-provided project/generation/revision values are assertions, not authority; only the same logical Task may recover its failed/lost pending reservation.
7. Typed stage checkpoint validation proves both committed artifacts and required domain rows before stage success. Stage/Task/Run/Project updates share an active lease and generation fence under `BEGIN IMMEDIATE`.
8. Proxy RenderJobs are durable before media I/O and transition through the centralized state model. Failure, cancellation and lease expiry persist a safe error code; success requires every associated Asset to be committed.

Active M3 file ownership (recorded before implementation):

- Main Agent: ORM/public DTO schemas, Alembic head, dependencies/locks, shared review/render/delivery services and repositories, Task dispatcher, API integration/auth/idempotency/media boundary, CLI, cross-module tests and all persistent planning documents.
- `m1_content`: read-only audit of existing review/delivery/domain persistence and proposed transaction algorithms; no file changes.
- `verifier_researcher`: read-only required-route, HTTP/security and API acceptance matrix with primary-source verification where needed; no file changes.
- `m1_media`: initially read-only Web inventory/UI/test plan. Any later Web write delegation will be confined to `apps/web/src`, `apps/web/tests` and `apps/web/e2e` after the main Agent freezes API DTOs and package dependencies; it may not edit package/lock files or shared backend/docs.

The Web write handoff was activated on 2026-08-03 after the main Agent froze `src/liveclip/api/app.py`, `schemas.py`, Vite/TypeScript/Playwright configuration and exact package lock. `m1_media` owns only `apps/web/src`, `apps/web/tests` and `apps/web/e2e` until it returns its test evidence. Main continues to own dependency/configuration files and all Python/API integration.

No M3 Agent may edit another owner's files. The main Agent will record any later write handoff before it begins and will integrate/validate the returned tree before claiming a UI path.

Active M4 file ownership (recorded before provider implementation):

- Main Agent: all provider code, common telemetry schema, Pipeline integration, usage persistence, CLI cloud smoke, prompt files, integration tests, research notes and persistent planning documents.
- `verifier_researcher`: read-only official OpenAI Audio/Responses verification and acceptance evidence; no file changes or paid calls.
- `m1_media`: read-only ASR/cache/persistence/recovery audit; no file changes or network calls.
- `m3_reviewer`: read-only Responses/prompt/cloud-smoke implementation audit; no file changes or network calls.

The three audits are independent and must return before the main Agent begins large provider edits. Shared schema, migration head, dependencies and prompt contracts remain main-Agent-owned.

All three audits returned before integration began. A subsequent bounded test-only handoff is active while the main Agent integrates runtime code:

- `verifier_researcher`: may add only `tests/unit/test_openai_retry.py` and `tests/unit/test_openai_asr.py`; no production, fixture, dependency or documentation edits and no network/paid calls.
- `m1_media`: may add only `tests/unit/test_openai_llm.py`; no production, fixture, dependency or documentation edits and no network/paid calls.
- Main Agent retains every shared file and will inspect and rerun all delegated tests before accepting them.

The first independent M4 review returned FAIL with four P1 and two P2 findings. The main Agent fixed strict-output repair, config/Prompt/schema drift, cancellation telemetry, symlink/cache trust, empty word timing and cloud-smoke evidence tests. The second read-only review returned `PASS` after 121 focused tests, full Python/lint evidence and diff validation; it found no residual P0/P1/P2. A final read-only follow-up by `m3_reviewer` investigated the subsequently observed FFmpeg timeout and confirmed the bounded-thread remediation direction without changing files.

Active M5 file ownership (recorded before hardening edits):

- Main Agent: all production code, tests, dependencies, migrations and persistent planning documents; only the main Agent may modify repository files until the audits return and a later bounded handoff is explicitly recorded.
- `m1_media`: read-only long-media/streaming/cancellation/recovery audit, including read-only metadata of `input/7.28.mp4`; may run existing tests and write only ephemeral test output outside tracked paths.
- `verifier_researcher`: read-only adversarial security and acceptance-matrix audit for allowed roots, source replacement, cache/ZIP/Range and redaction; no source edits.
- `m3_reviewer`: read-only SQLite separate-process contention plus VFR/rotation/multi-audio/font/layout/process-diagnostic audit; no source edits.

All three M5 audits returned their initial evidence before corrective implementation. The
first two disjoint write handoffs completed and were integrated: bounded process output and
component-anchored immutable artifact publication. A second bounded test-only handoff is
active while the main Agent owns every production module, shared schema, migration and
persistent document:

- `m1_media`: may create or modify only
  `tests/integration/test_media_stream_selection.py`; add real FFmpeg evidence that a
  non-first default audio stream and selected video stream reach proxy/final rendering.
  Production code, fixtures, dependencies and documents are read-only.
- `verifier_researcher`: may create or modify only
  `tests/integration/test_task_queue_processes.py`; add spawn-mode, independent-Engine
  claim, heartbeat, crash-expiry and SQLite busy-recovery evidence. Production code,
  fixtures, dependencies and documents are read-only.
- `m3_reviewer`: read-only design review of durable, bounded, redacted FFmpeg diagnostics;
  no repository changes.
- Main Agent retains all production code, unit/API/security tests, shared schemas,
  migrations, configuration, documentation and integration of all returned work.

The repository input remains a read-only user asset and is excluded from Git. Its measured baseline is 2,190,937,089 bytes, 2,780.437 seconds (46:20), 1920×1200 H.264 with nominal 30 fps/variable average metadata, and 48 kHz stereo AAC. It is useful for multi-chunk and 2 GB streaming evidence but is shorter than the product's typical 2–4 hour source; final claims must retain that limitation.

The independent M5 review returned `NOT PASS` with five reproducible P1 findings:
render validation/publication byte binding, committed stage dependency hash verification,
directory-bound Delivery publication, fail-closed legacy stream-selection migration, and
caption-overlay fanout validation. Corrective file ownership recorded before remediation:

- Main Agent: render/quality byte binding, committed Asset dependency verification,
  Pipeline/source pin performance, diagnostic warnings, shared integration, persistent
  documents and final validation. It will not edit the delegated files until handoff.
- `m5_delivery`: may modify only `src/liveclip/media/secure_files.py`,
  `src/liveclip/delivery/package.py`, `tests/unit/test_secure_files.py`, and
  `tests/unit/test_delivery.py`; implement inode-bound no-replace directory publication
  and safe cleanup with adversarial replacement coverage.
- `m5_legacy_migration`: may modify only
  `migrations/versions/a71d4f9c2e10_add_source_stream_selection.py`,
  `src/liveclip/media/models.py`, `src/liveclip/db/models.py`, and a new isolated
  migration test; old rows must remain explicitly unverified rather than acquire guessed
  stream indices. Runtime upgrade integration remains main-Agent-owned.
- `m5_caption_budget`: may modify only `src/liveclip/domain/edit_plan.py`,
  `src/liveclip/renderer/text.py`, `src/liveclip/renderer/service.py`,
  `tests/unit/test_edit_plan.py`, and `tests/unit/test_text_overlay.py`; make renderer
  overlay resource constraints part of the domain/API acceptance boundary.

No delegated task may modify shared status/plan files, dependencies, the migration head,
API schemas, or another task's files. The Main Agent will review each diff and rerun the
full gate before accepting it.

The first remediation closed all five P1 findings and two adjacent P2 observations, but a
fresh read-only re-review found one additional P1: ZIP creation and final directory
publication still bound only ordinary member paths/root-directory identity. A second
bounded `m5_delivery` handoff modified only secure-file, Delivery package/handler and
their tests. It now pins every member and ZIP descriptor, streams members without
`ZipFile.write(path)`, validates the exact tree before/after no-replace publication, and
commits manifest/ZIP Assets with expected hashes. A separate VFR/rotation handoff added
only `tests/integration/test_media_rotation_vfr.py`. The original re-reviewer then replayed
both endpoint-replacement reproductions: each failed closed with `DeliveryError`, no
canonical `v001`, no attempt residue and no external-data inclusion. Its final verdict is
`PASS`, with no P0/P1/P2 after 58 focused tests, Ruff, mypy and diff validation.

Active M6 file ownership (recorded before acceptance changes):

- Main Agent: real composition fixture/process orchestration, Playwright config/spec integration, Make targets, all product/runtime code, shared dependencies and every persistent planning/documentation file.
- `m5_vfr_rotation`: read-only audit of the existing Web/Playwright/API/Worker composition and a proposed isolated real-backend browser flow; no repository edits.
- No other write Agent is active. Any later documentation or test handoff will receive disjoint explicit files. The final Product Spec Verification Agent is read-only and starts only after all gates pass.

The first M6 code review found one P1 and one P2: shell-background Workers could inherit ignored SIGINT and leave an independent FFmpeg process group, while E2E cleanup learned directory identity only at deletion time. The Main Agent owns the repair; `m5_rereviewer` performs the read-only re-review and `m5_delivery` independently rechecks documentation/Product Spec closure. Neither reviewer may edit files.

Active M7 file ownership:

- Main Agent: all Codex Provider/process/config/API/CLI/Web integration, public schemas, tests, ADR/research, Solution, ExecPlan, STATUS and final Git checkpoint.
- Final M7 Reviewer: read-only after the full gate; it must focus on command/tool escape, secret exposure, provider/config fingerprints, false-success claims, ASR/Codex separation and API/Web readiness behavior.
- No parallel writer may edit the M7 worktree or shared state files.

Active M8 file ownership:

- Main Agent: all production code, migrations, tests, public documentation, ExecPlan/STATUS, final integration and Git operations.
- Final M8 Reviewer: read-only after full gates; focus on real-provider evidence, optional timestamp handling, cross-generation cache provenance, migration safety, clean-proxy/final-overlay separation, recovery and secret/Git scope.
- No parallel writer edits the shared worktree or persistent state documents.

## Concrete commands and expected observations

From repository root:

```bash
make setup
```

Expected: project-local `.python` contains a native arm64 Python 3.12; `.venv/bin/python` reports 3.12 and arm64; Python dependencies are locked/installed; frontend dependencies install when its lock exists; data roots exist. A repeat run changes nothing material.

```bash
make doctor
```

Expected on the discovery host: Python/Node/SQLite/data checks pass; `subtitles`/`drawtext` are reported absent with raster fallback; a real VideoToolbox attempt may fail in sandbox and must report verified libx264 fallback. The selected Codex CLI/login and presence—not value—of local OpenRouter configuration are checked. Current configuration reports both Providers ready. M2 versus target-M3 performance is a documented limitation, not a doctor capability failure.

```bash
make lint
make test
```

Expected: nonzero on any Ruff/type/unit/integration failure; output states test count and skips. Standard tests make no cloud request.

```bash
make demo
```

Expected: exit zero only after the real-media M1/M6 acceptance chain, and print project ID plus absolute final, contact-sheet and ZIP paths. Re-running creates a separate Demo project/version and does not overwrite an immutable delivery.

```bash
make smoke-cloud INPUT=/absolute/path/to/short.mp4
```

Expected now: nonzero, with missing variable names and `not_run`, because no OpenAI key/model environment is configured. With configuration it must prove both real provider calls and never instantiate Mock.

```bash
make smoke-codex
```

Expected on this host: one real `codex_cli` editorial result with a nonempty Codex thread/correlation ID and positive token usage, strict bounds/title/score, and no degraded or Mock evidence. This validates the text editor only; it must never be recorded as ASR or real-video proof.

```bash
make smoke-openrouter INPUT=/absolute/path/to/short.mp4
```

Expected now: success using the ignored local credential and `/Users/junhuaxu/Workspace/AGI/liveclip-ai/input/.liveclip-smoke/7.28-300s-90s.mp4` (90.033 seconds, both streams fully decoded, SHA-256 `f603658f7eba804ab2201366c02811de786f9868a17f2c6c7339313e263a0a13`). Success requires OpenRouter generation IDs, Codex thread/token evidence, non-degraded selected plans and no Mock evidence. Missing/rejected configuration must still stop without fallback.

## Validation criteria

Each milestone validates observable outputs described in its checklist. Media success requires ffprobe, full decode and hashes; UI success requires rendered browser behavior; queue success requires competing workers and expired-token evidence; cloud success requires persisted real provider/request metadata. Interface-only or mocked subprocess assertions do not satisfy end-to-end criteria.

## Idempotency, retry and recovery

Setup and Demo generation use isolated/generated targets. A stage re-run compares input fingerprints and validated output manifests. Tasks use fenced leases and bounded retries. Temp files have attempt identities and never count as success. Immutable revisions/deliveries are never overwritten. Failed cloud smoke preserves accurate failure status and cannot downgrade. Recovery starts from the first unsucceeded current-generation stage after validating prior checkpoints.

## Surprises and Discoveries

- 2026-08-12: The real editorial model had already produced a useful Hook for all 15 current `7.28` revisions, but the list DTO omitted it and the Web exposed only grounded keywords. A summary DTO field closes the UX gap without schema migration, model rerun or N+1 detail requests.

- 2026-08-12: M10 correctly placed actionable subtitles and keywords beneath each video but left the older full-livestream transcript panel in the workspace. Removing the component also removes one large, redundant transcript fetch per Project view; the backend/API contract does not need to change.

- 2026-08-05: The real OpenRouter response contained valid timestamped segments but optional word data sometimes mirrored a whole sentence or could not be aligned. Rejecting the entire response discarded usable ASR. The Adapter now degrades only optional word timing to `unavailable`; segment timing remains strict and 233 real segments were persisted with zero invented words.
- 2026-08-05: The historical database predated Asset scope and allowed only one RenderJob per Task through an obsolete unique `task_id` constraint. Backups were taken before each narrow migration; Alembic reached `e7b14c2d9a60`, SQLite integrity/FK checks passed, and the real pipeline subsequently persisted all 15 proxy RenderJobs.
- 2026-08-05: Generation 1 completed all paid ASR calls but its Codex child could not initialize an in-process app server inside the restricted Codex sandbox, so it truthfully degraded. The same Project's generation 2 reused all 33 historical caches under the then-current key-first identity and ran Codex under the host Worker: 39 successes, zero failures, 15 selected plans, zero degraded. Post-run manifest comparison confirmed both preprocessing key and byte SHA matched for every chunk; the later dual-hash v2 enforcement is tested but was not the code used during that paid run.
- 2026-08-05: One selected clip ended 532 ms into a 129-character Provider sentence without word timing. Assigning the whole sentence to that overlap was false and exceeded caption density. The domain now omits only such uncertain dense boundary tails while retaining strict failure for a complete dense in-clip segment.
- 2026-08-05: A viewed real contact sheet shows a clean 540×960 blurred-background proxy with source-native livestream UI but no LiveClip-generated title/caption. Automatic report fields confirm H.264/AAC, 83.233 seconds versus 83.216 expected, full decode and all heuristics passed.
- 2026-08-11: The first final `make test` caught one user-visible regression: caption splitting applied NFKC storage normalization and changed Chinese `，` to `,` after a boundary edit. Storage now uses NFC and preserves source punctuation while the renderer still uses a normalized display copy. The original API flow plus a new unit regression pass, followed by the complete 516-test Python gate.
- 2026-08-11: Fresh Demo `demo_20260811T032338_6f7414aa` reached `delivered`. The clean 540×960 proxy and text-bearing 1080×1920 final contact sheets were both actually viewed and their reports record `viewed_passed`; ZIP integrity and manifest/final SHA checks pass.
- 2026-08-11: Fresh real smoke `0b523cdc396148b5af6d36cc5559edfe` succeeded with two OpenRouter generation IDs, one Codex thread, zero retries, 95.104 overlap-inclusive ASR seconds, USD 0.0023776 Provider cost and non-degraded title `高音别硬喊：强混声与假声区别`.
- 2026-08-11: Final M8 review reproduced short/offset sentence mirrors, incomplete word arrays and same preprocessing key with different audio bytes. Optional words now become available only when every segment's normalized text is completely represented; real cache identity binds both key and content SHA. The focused reviewer gate passed 138 cases, and the complete post-fix gate passed 527 Python tests.
- 2026-08-11: Review also found an old succeeded text-bearing proxy that the new Web would have called clean. Migration `b81e3c7a4d20` plus query-time fencing stale ambiguous legacy proxies and cancel active legacy work. The actual DB upgrade changed dirty render `709244f4fac84980ae81e1713bf2a79e` to stale while preserving all 15 current clean long-run proxies and two other clean proxies; integrity/FK checks pass.
- 2026-08-11: The user-requested generation-3 rerun deliberately missed historical key-first cache filenames and therefore exercised the final dual-hash cache path through 33 fresh paid OpenRouter calls. It produced 248 segments and 41 rough candidates; all 41 Codex calls, 15 selected non-degraded plans and 15 clean proxy validations succeeded. This proves fresh processing under v2 identity but does not claim a fourth-run cache-reuse observation.
- 2026-08-11: Old-generation cleanup first attempted to delete Assets, but `audio_chunks.asset_id ON DELETE RESTRICT` correctly rejected and rolled back the transaction. Deleting the two PipelineRuns first cascaded their chunks/candidates/renders, after which deleting 168 generation-scoped Assets succeeded in the same transaction. A pre-cleanup byte-identical SQLite backup is retained; FK/integrity checks pass.
- 2026-08-11: The first cleanup addressed generations inside current `7.28`, not separate Project rows. The Web correctly continued to show 10 historical development/Smoke/failed projects. After confirming all 10 had zero reviews/deliveries, a second backed-up transaction removed them and their 108 Assets; the restarted API now returns exactly one Project.
- 2026-08-11: Generation 3 exposed a user-visible layout inconsistency rather than an encoding failure: 10 of 15 LLM plans selected a blurred fill plus shrunken foreground, while five selected a direct center crop. Contract `v3.no-blur` now has only one FFmpeg video branch. The LLM cannot return layout, the deterministic plan selects center crop, and the historical blur enum is decode-only plus fail-closed at active validation/rendering.
- 2026-08-11: Migration `c91f4e2a7b63` staled all 15 old proxies. Ten affected clips received immutable revision 2 through the API while five already-correct clips remained revision 1; all 15 were manually rerendered under Schema 4/renderer v3. Both a former-blur and former-center contact sheet were viewed and now show the same direct single-layer crop.
- 2026-08-11: The M9 reviewer found no implementation defect and one P2 migration-test gap. Adding explicit blur-final, center-final and current no-blur-proxy cases exposed a fresh-upgrade ordering issue: `b81e3c7a4d20` must recognize the later clean/no-blur contracts before `c91f4e2a7b63` applies the final layout fence. The repaired chain passes 30 targeted tests; independent re-review passes with no residual finding.
- 2026-08-11: The current `7.28` transcript has 248 timestamped segments but zero persisted words. Keyword navigation therefore truthfully exposes segment windows. All 34 returned occurrences were cross-checked against the same run: every phrase is an exact normalized substring of its persisted segment, every range equals that segment, and every segment is fully inside its current clip. API usage remained unchanged before/after the derived read.
- 2026-08-11: Independent review reproduced three browser concurrency hazards around lost batch responses and editor drafts. The Web now retains an exact body/key retry operation, reconciles server state after failure, excludes dirty candidates, locks writes while a batch is in flight, updates open detail caches on success, and disables a failed operation if its membership/revisions/drafts are no longer safe. Six component tests cover these states.
- 2026-08-11: Host Chrome opened the actual generation-3 board and observed 15 videos, 15 subtitle sections, 15 keyword sections and 34 keyword controls. A keyword click moved only its card from 0 to 55.144 seconds; selection and dirty-draft fencing worked, and no A/B text appeared. The fixed page header crossed an element screenshot but was not in media bytes: source/proxy frame extraction proved the current proxy is the original image center-cropped with no blur or LiveClip-generated text.
- 2026-08-11: The first restricted launch of the test-only headless Chrome received macOS `SIGABRT/EPERM` before any assertion. Re-running the exact final `make test` with required host GUI permission passed 540 Python tests, 19 Web tests and both browser flows. This was an execution-permission failure, not a product retry or relaxed assertion.
- 2026-08-16: Real `8-16-1.ts` playback exposed a transport-stream sync defect that container/decode validation could not detect. VLC preserved the PTS/PCR clock, while LiveClip sought directly into a non-keyframe HEVC GOP and independently reset audio/video `STARTPTS`; the 1368-second cut lost about 2.04 seconds of decodable video lead-in. A ten-second preroll plus accurate output seek and one preserved source timeline fixes the defect. All 15 v4 proxies now measure 0/40 ms stream-start deltas and pass full decode.

- 2026-08-05: A bounded 90-second fixture was generated from `input/7.28.mp4` seconds 300–390 for the first paid ASR smoke. It is 4,906,445 bytes with H.264 video/AAC audio, fully decodes without errors, and the original source stat identity remained unchanged. Preparing the fixture does not prove ASR; the cloud call remains `not_run` until a new safe Key exists.
- 2026-08-05: `OPENROUTER_SETUP.md` correctly warns that the original Key was exposed and contains no usable secret. Local Settings confirms `OPENROUTER_API_KEY` is absent, so no paid ASR call is authorized or possible yet.
- 2026-08-05: Current OpenRouter primary docs confirm `/api/v1/audio/transcriptions`, JSON `input_audio`, M4A/AAC support, `verbose_json` segment/word timestamps, `X-Generation-Id`, actual `usage.cost`, no SRT/VTT and a 60-second upstream timeout. They also state multipart `prompt` is ignored and document `provider.options.groq.prompt`; LiveClip therefore uses JSON, one bounded 24 MB chunk at a time, and treats Groq vocabulary influence as best effort rather than a smoke guarantee.
- 2026-08-05: The installed OpenAI SDK 2.52.0 parses OpenRouter's minimal verbose response but is permissive about missing fields. The Adapter now requires an exact non-truncated generation header, validates finite nonnegative root duration/usage seconds/cost plus segment/word values, and records a 200-but-malformed body as deterministic INVALID without retry or Mock fallback.
- 2026-08-05: The first M7 reviewer proved Codex 0.146.0 still enabled apps/browser/computer/plugins under the earlier partial flags. The corrected profile pins that exact CLI version, disables every known tool surface, rejects any JSONL tool item, removes credential-bearing proxy variables, fingerprints executable bytes/profile, and rechecks before each call. A real smoke passed this hardened profile.
- 2026-08-05: Provider readiness must not precede completed Idempotency-Key replay. API create paths now replay the canonical resource first, return conflict for changed payload, and gate only genuinely new work; an integration restart test proves the behavior.
- 2026-08-04: The installed Codex CLI 0.146.0 is already authenticated through ChatGPT. A real tool-disabled strict-schema smoke succeeded with request `019fcf6a-a03e-7520-a3b4-fff735271737`, 11,371 input/101 output tokens and a validated Chinese editorial result.
- 2026-08-04: The first real Codex schema call reached OpenAI but failed strict validation because every object property must also be in `required`. The adapter now gives Codex only the model-owned editorial fields and keeps candidate/model/prompt/degraded identity system-owned.
- 2026-08-04: Official `codex exec` documentation exposes image attachments but no audio-transcription input. The installed CLI therefore solves the editorial LLM requirement but cannot replace timestamped ASR; `openai-codex` deliberately requires both independent prerequisites.
- 2026-08-04: macOS exposes the default temporary path through `/var`, which is a symlink. Secure no-follow publication correctly rejected it; resolving the system temp root to `/private/var` preserves the no-follow invariant without weakening validation.

- 2026-08-03: Repository was completely empty; there are no user changes or compatibility constraints.
- 2026-08-03: Installed Python 3.12 is x86_64 despite arm64 host; project-local native Python is required.
- 2026-08-03: Node 22 LTS exists but default Node 26 is non-LTS.
- 2026-08-03: FFmpeg help for an unknown filter can still exit zero. Doctor must parse the actual filter list.
- 2026-08-03: FFmpeg lacks both common text filters but has overlay; this led to the safer raster-overlay design.
- 2026-08-03: VideoToolbox fails only inside the Codex sandbox and succeeds on host; capability claims need real context.
- 2026-08-03: Current Vite 8 requires Node 22.12 but the installed native LTS is 22.11. ADR-006 pins supported Vite 6.4.3/Vitest 3.2.7; npm audit reports zero vulnerabilities.
- 2026-08-03: HTML5 video cannot attach a Bearer header. API DTOs therefore issue short-lived HMAC URLs bound to GET, canonical path, resource purpose/ID and expiry; Vite/uvicorn access logs must not record their query strings.
- 2026-08-03: M3 final pre-review gate is green at 233 Python tests and 11 Web tests; the API integration drives Mock pipeline, atomic review, final render, versioned ZIP and Range media, and the host Playwright Chrome flow passes in 5.5 seconds.
- 2026-08-03: The Codex in-app browser runtime reported no available browser, so no in-app visual claim is made. The repository Playwright suite did launch real host Chrome and passed the user-visible create/review/edit/rerender/delivery/download flow.
- 2026-08-03: Independent review exposed that Delivery eligibility changes on both EditPlan revision and review decision. Both paths now fail active snapshots and cancel/request-cancel their durable tasks in the same SQLite transaction; succeeded immutable deliveries remain untouched.
- 2026-08-03: Relative captions cannot be reused blindly after an absolute source-boundary change. The Web sends a differential PATCH and omits unchanged captions, causing the backend to rebuild cue-relative milliseconds from absolute transcript segments.
- 2026-08-03: Node 26 exposes an undefined experimental Web Storage global without a backing file. Web tests install an isolated in-memory Storage implementation; production remains targeted at Node LTS and the UI keeps the optional Bearer token only in React memory.
- 2026-08-03: The independent M3 Reviewer returned `PASS` with no remaining P0/P1 after independently running lint, 233 Python tests, 11 Web tests, 30 focused regressions and diff validation. It retained one product-test P2: Playwright mocks the API, so M6 will add browser-to-real-backend composition even though the real backend chain already has API integration coverage.
- 2026-08-03: The user authorized read-only long-video testing from repository `input/` after implementation. M5/final acceptance will record runtime, peak resources, disk growth, recovery and quality; source media and outputs remain ignored.
- 2026-08-03: Current general ASR recommendation lacks required timestamps; v1 defaults to the older timestamp-capable model rather than fabricate alignment.
- 2026-08-03: The official file-transcription guide still caps uploads at 25 MB and explicitly limits `timestamp_granularities[]` to `whisper-1`; current `gpt-transcribe` remains the general recommendation when alignment is not required.
- 2026-08-03: `uv.lock` pins official `openai==2.52.0`. Local introspection confirms `audio.transcriptions.create`, `responses.parse(text_format=...)`, public object `_request_id`, failure `request_id`, refusal content, incomplete reasons and token/audio usage types without making a cloud call.
- 2026-08-03: M4 uses `whisper-1` as a capability-driven timestamp default despite the newer general transcription recommendation. Empty word arrays are `unavailable`; unaligned provider words are rejected rather than silently discarded.
- 2026-08-03: The first M4 review found SDK Pydantic errors bypassing repair, unbound Prompt/provider/schema drift, cancelled-call evidence loss and cache symlink/tamper trust. Fixes include strict Pipeline config v2 fingerprint loading, multi-call cancellation evidence bound to the historical attempt, and an anchored component-by-component `openat`/`O_NOFOLLOW` immutable cache.
- 2026-08-03: Cache corruption and final/ancestor symlink tests prove zero provider calls. Cache-before-database ordering is intentional: an immutable successful response can survive a callback crash and replay its original call ID under the current DB fence.
- 2026-08-03: The application disables official SDK retries and owns request counts, bounded exponential jitter and Retry-After. A retry is counted only when the next request can actually be attempted, so cancellation during backoff preserves `retry_count < request_count`.
- 2026-08-03: Mock runtime mode now discards any residual OpenAI key and rejects a persisted OpenAI run before handler execution; cloud smoke independently rejects missing request IDs, degraded/wrong-model plans, failed evidence and any non-OpenAI evidence.
- 2026-08-03: A post-review full run exposed a second intermittent 120-second libx264 timeout while rendering the second 540×960 proxy. The retained fixture proved overlay creation completed and no MP4 was published. Exact-input reruns completed in 2–3 seconds, while FFmpeg verbose evidence showed default libx264 expanding to 12 encoder threads plus filter/input workers, so this was resource-sensitive rather than deterministic bad media.
- 2026-08-03: Raster PNG inputs are now finite one-frame sources held by explicit framesync semantics; filter/libx264 workers are capped at 2/4, a runtime timeout gets one 1/1-thread retry, and the process runner preserves bounded partial stderr. Thirteen focused process/renderer tests, three repeated real Demo integration chains, `make lint`, 328 Python tests and 11 Web tests pass.
- 2026-08-03: Post-hardening `make demo` delivered project `demo_20260804T054112_c87bf8bc`. Its 1080×1920 H.264/AAC final fully decoded; the three-frame contact sheet was actually viewed with safe Chinese title/captions, correct portrait layout and no black/blank/severe-crop issue, and the quality report records `viewed_passed`.
- 2026-08-03: The current session could not hot-load the newly configured OpenAI Developer Docs MCP. The main Agent followed the skill fallback using only official OpenAI domains plus the locked official SDK; a later session can use the configured MCP directly.
- 2026-08-03: First viewed overlay contact sheet revealed a false truncation ellipsis caused by trimming a wrap-boundary space. The wrap algorithm now tracks actual truncation; a regression test and second viewed render pass.
- 2026-08-03: Initial M0 review found six concrete gaps. Publication now validates container/codecs/decode/frames/edges/safe bounds before exposure, uses an atomic hard-link no-clobber operation, and falls back on VideoToolbox runtime exceptions. Font detection no longer points from renderer into CLI, and EditPlan tests cover generic paths, shell commands and FFmpeg option fragments.
- 2026-08-03: The post-review render `/private/tmp/liveclip-m0-overlay-reviewed.Ot6m6j/vertical-overlay.mp4` passed MP4/H.264/AAC, exact 540×960/4.000s, full decode, automatic quality and actual contact-sheet inspection. Its SHA-256 is `4713a270416b9def76a023211fd5b40e9a72538739e33f9b1000b6e7d8e19e56`.
- 2026-08-03: Settings initially applied the `LIVECLIP_` prefix to fields whose public contract is explicitly unprefixed (`ASR_CHUNK_SECONDS`, `DEFAULT_TOP_N`, and peers). Explicit validation aliases and an environment behavior test now keep runtime parsing aligned with `.env.example`.
- 2026-08-03: M1 uses a 32-second generated source and explicit 8–12 second candidate limits so a full local acceptance finishes in about 23 seconds; configured product defaults remain 30–90 seconds. It still exercises three overlapped audio chunks, three proxies, revision invalidation, a 1080×1920 final and ZIP delivery.
- 2026-08-03: The first full Demo `demo_20260803T075537_0e3ca9f9` reached `delivered`. Final MP4 is H.264/AAC 1080×1920, 12.000s, 3,411,094 bytes, SHA-256 `f1ddd09178868745ea88c82995b35a5f7ecd1542d7ba616e0559db7ab7ac2ddd`; complete decode and actual visual review passed.
- 2026-08-03: A second `make demo` created distinct project `demo_20260803T075904_1fdd3288`, proving rerun isolation rather than overwriting the first immutable v001.
- 2026-08-03: M1 review identified that directory confinement alone did not prove `clean-demo` ownership. Cleanup now requires both a generated project-name shape and a valid `.phase.json` marker; unknown and unmarked content is preserved. The independent Reviewer returned PASS after 70 tests, lint and retained-artifact inspection.
- 2026-08-03: SQLite 3.51.0 on the system runtime is inside an officially disclosed WAL-reset race range; the project CPython embeds SQLite 3.53.1. Setup, doctor and runtime now reject known-unsafe branches instead of trusting the standalone `sqlite3` executable.
- 2026-08-03: Pre-creating all six Tasks produced false downstream input fingerprints. M2 now pre-creates StageRuns for visibility but creates each downstream Task only after validating the prior stage's committed Asset hashes.
- 2026-08-03: Chunk-boundary cancellation was insufficient for a long FFmpeg call. A shared `Popen(..., shell=False, start_new_session=True)` runner polls the durable heartbeat signal and terminates the owned process group on cancellation, lease loss or timeout.
- 2026-08-03: The real persistent Mock pipeline produces three 270×480 H.264/AAC proxies from six leased stages; a separate foreground/Worker race test observes one handler execution for every stage and no duplicate claim.
- 2026-08-03: Initial M2 review demonstrated that an arbitrary committed Asset could satisfy a stage and that StageStateStore mutations were not lease-fenced. Completion now uses typed per-stage domain checkpoints and all related mutations validate Task/Attempt/Run/Project generation in one immediate transaction.
- 2026-08-03: Final M2 review demonstrated that caller-supplied Asset scope could cross project/revision boundaries and that proxy render rows appeared only after successful I/O. Asset scope is now database-derived, cross-logical-Task adoption is forbidden, and observable RenderJobs persist through running/failure/cancel/lease-expiry states.
- 2026-08-03: Ingest, preprocess and quality subprocess timeout paths are explicitly transient. Argument, media-contract and validation errors remain deterministic, so bounded retry does not conceal bad inputs.
- 2026-08-03: The independent final M2 Reviewer returned `PASS` after 82 focused tests, lint, 204 full tests and whitespace validation. It retained three P2 risks for M3/M5: non-interruptible in-process fingerprint/ffprobe latency, non-generation-scoped canonical paths and lack of a true separate-process contention test.
- 2026-08-04: Read-only `input/7.28.mp4` is 2,190,937,089 bytes, SHA-256 `595cc75a65fe8d9faa3b41ba9f5b58b307d1b0a41236f7fc6016c0c1ae8acd03`, 2,780.437 seconds, 1920×1200 H.264 plus stereo AAC. A six-stage Mock run completed in 28.83 seconds with five 600-second/5-second-overlap M4A chunks, 14 committed Assets and about 18 MB generated data. The before/after source stat/hash matched. The fixture is 46:20, not a representative 2–4 hour source; `/usr/bin/time -l` could not expose peak RSS because sandbox `sysctl kern.clockrate` failed after the child had already succeeded.
- 2026-08-04: The default Mock transcript is intentionally only 0–32 seconds, so the long run produced one 32-second candidate/proxy. This proves streaming/chunk chronology and artifact bounds, not long-timeline content quality or candidate density.
- 2026-08-04: Generated real FFmpeg fixtures prove VFR (`r_frame_rate=30/1`, `avg_frame_rate=750/59`), 90° and 270° display rotation, explicit video/audio stream indices and successful 270×480 H.264/AAC proxy validation/full decode/contact sheets. Separate fixtures prove a non-first/default audio stream reaches rendering.
- 2026-08-04: The first M5 review exposed five byte/state boundary defects: render validation versus publication, committed stage-Asset trust, Delivery directory replacement, guessed legacy stream indices and caption fanout drift. Fixes pin media bytes, verify typed dependency Assets, fail closed for legacy rows, share the display-cue budget and hash a long source only once per proxy stage.
- 2026-08-04: A fresh re-review found that binding a Delivery root directory still did not bind each member or the final ZIP. ZIP creation now streams from pinned member FDs, pins/verifies the ZIP FD, and rebinds/rehashes the exact regular-file tree across no-replace publication and Asset commit. Both original replacement reproductions fail closed; final independent M5 verdict is `PASS` with no P0/P1/P2.
- 2026-08-04: Final M5 gates passed: `make lint` over 153 formatted files/97 typed source files plus TypeScript, 428 Python tests in 135.02 seconds, 11 Vitest tests, and Demo project `demo_20260804T085309_96fb7a31`. Its 1080×1920 H.264/AAC final fully decoded; ZIP integrity and hashes passed; the contact sheet was actually viewed and recorded `viewed_passed`.
- 2026-08-04: M6's real Chrome test starts isolated FastAPI, Worker, SQLite, Vite and FFmpeg with Mock AI. The post-fix run passed in 18.4 seconds: project `6bc5aab3f1174ce2abdcd2539eb74b37`, run `376d68a406a6471ca65a16c48ede130f`, six succeeded stages, eight succeeded Tasks/attempts with unique leases, stale proxy r1, succeeded final r2 and succeeded v001 ZIP. Its full-page delivered screenshot was actually viewed; temporary roots, both listeners and matching service/media processes were absent after cleanup.
- 2026-08-04: A real-E2E review reproduced Bash background SIGINT inheritance as `SIG_IGN`. Worker entry now explicitly installs SIGINT/SIGTERM handlers that raise through active media work, allowing `run_cancellable_process` to terminate the owned process group. A real child/grandchild regression passes. `make dev` and the E2E harness use bounded graceful cleanup before KILL.
- 2026-08-04: E2E temporary-root allocation now returns original device/inode from the allocating process. Fixture creation, config verification, persisted-evidence verification and cleanup all require that identity; a replaced endpoint is retained and makes cleanup/test fail instead of being deleted.
- 2026-08-04: The Codex in-app/MCP Browser adapter still exposed zero browser instances even after the user confirmed a local MCP Chrome was running. No MCP-control claim is made. The checked Playwright suite directly launched installed host Chrome and produced inspectable evidence.
- 2026-08-04: Final M6 gates after both review repairs: repeatable `make setup` PASS; Doctor READY with four expected warnings; lint covers 157 formatted files/99 typed source files plus Schema/TypeScript; `make test` passes 433 Python, 11 Vitest, one controlled Mock Chrome E2E and one real-backend Chrome E2E. Cloud smoke exits `not_run` because provider/key/allowed root are absent.
- 2026-08-04: Fresh Demo `demo_20260804T134521_1efe11b0` reached `delivered` with three candidates and v001. Final is 1080×1920 H.264/AAC, 12.000 seconds, 3,385,827 bytes, SHA-256 `7286b956031c1132e7d3caaa366a074cee5ef5caa8f931eb8bd325e566b867c4`; full decode, ZIP test and manifest/member hash checks pass. The contact sheet was actually viewed and report records `viewed_passed` at `2026-08-04T13:46:13.971417+00:00`.
- 2026-08-04: The final independent Product Spec-wide Verification Agent returned `PASS` with zero P0/P1/P2. Its matrix covered Doctor, import, preprocessing, ASR, candidates/editing, EditPlan, rendering/quality, persistence/leases, CLI/API/Web, revision stale, immutable Delivery, security, cloud boundaries and every required command. It retained only the already disclosed external verification limits: no cloud credential, no representative 2–4 hour M3 run, sandbox VideoToolbox result, unavailable MCP attachment and no Linux execution.

## Decision Log

- 2026-08-13: Adopt ADR-013 environment-authenticated workspace identities and durable Project memberships; rationale: “每个人看自己的项目” is an authorization requirement, so a browser-only filter over a global collection would be both misleading and bypassable.
- 2026-08-13: Make the current creator the Project owner and reserve member administration to that owner, while treating editor/reviewer as workflow labels in v1; rationale: this provides a clear accountability model without copying an incomplete permission state machine into API/Web adapters.
- 2026-08-13: Keep Provider readiness and API-token controls in the account/system popover rather than the main Project dashboard; rationale: an editor's primary surface should prioritize assigned work, attention state and the next action.

- 2026-08-12: Present persisted EditPlan `hook` as `高光语句` and grounded timed phrases as `编辑关键词`; rationale: the Hook is audience-facing editorial copy that may be reviewed for on-screen use, whereas keyword ranges exist to help an editor navigate evidence and should not be mistaken for finished copy.
- 2026-08-12: Use one semantic ordered-list row per high-impact moment, with a desktop video/content split and subtitles as the final sibling; rationale: reviewers compare complete moments vertically while retaining a direct relationship between video, copy, navigation and full subtitles.

- 2026-08-12: Keep offline review export separate from formal Delivery and bind its v2 snapshot to Pipeline generation, Project epoch, EditPlan/review, clean RenderJob, producer Task and committed Asset; rationale: editors need a portable pre-approval package without mutating review truth, and long ZIP construction must not publish mixed concurrent state.
- 2026-08-12: Fence offline publication immediately before and after atomic rename, withdraw a raced canonical directory, and clean only strictly named/no-follow identity-pinned crash attempts under the package lock; rationale: a 288 MiB export must be recoverable without stale publication, overwrite or unbounded orphan leakage.

- 2026-08-12: Treat the persisted transcript as a processing/API capability rather than a separate Web review panel; rationale: candidate review needs subtitles, keywords and local context attached to the exact video, while removing ASR itself would break candidate generation, captions and grounded timing.

- 2026-08-05: Adopt ADR-010 clean review proxies with separate editorial metadata and reserve text overlays for final renders; rationale: the user must judge the underlying slice before approving generated presentation text.
- 2026-08-05: Permit verified ASR cache reuse only across generations of the same Project and record no new call evidence on a cache hit; rationale: retries/config generations should not repay identical chunks, while historical Provider provenance must not be copied or misattributed.
- 2026-08-11: Bind real ASR cache identity to both the preprocessing key and published audio-byte SHA-256; rationale: a deterministic configuration key cannot alone prove encoder output bytes are identical, and partial identity must fail closed.
- 2026-08-05: Treat malformed optional word timing as unavailable when segment timing remains valid; rationale: word data is optional and must neither erase usable transcription nor become fabricated timing.
- 2026-08-05: Allow explicit same-run manual retry for `EDIT_OUTPUT_INVALID` after an installed code repair, alongside `UNEXPECTED_STAGE_ERROR`; rationale: immutable Provider caches and lease fences make implementation-repair recovery safe, while ordinary deterministic input/config failures remain rejected.
- 2026-08-11: Satisfy the user's old-clip deletion request by removing generations 1/2 from LiveClip's active database and run tree only after generation 3 is fully validated, while retaining a SQLite backup and moving exact old run directories into a recoverable project-local trash; rationale: the user-visible result is clean without risking unrecoverable loss during an operational rerun.
- 2026-08-11: Prohibit blurred-background/duplicated-foreground rendering globally and make center crop system-owned rather than model-selected; rationale: the user requires one consistent direct-video presentation, and a single trusted template removes both visual inconsistency and unnecessary LLM control over composition. See ADR-011.
- 2026-08-16: Adopt ADR-019 bounded preroll plus output-accurate seeking and preserve one source A/V PTS timeline; rationale: fast seek remains practical for multi-hour media without converting HEVC reference-frame recovery into a permanent audio/video content offset.
- 2026-08-11: Adopt ADR-012 derived grounded keyword ranges plus one atomic revision-fenced batch endpoint over the existing candidate set; rationale: multi-candidate review needs truthful navigation and all-or-nothing decisions, not A/B duplication, fabricated word times or browser fan-out.

- 2026-08-05: Adopt ADR-009 `openrouter-codex` as the default real chain at the user's explicit direction; rationale: Whisper Large V3 supplies the timestamped Chinese ASR that Codex cannot provide, while retaining direct OpenAI alternatives.
- 2026-08-05: Permit only exact `https://openrouter.ai/api/v1` and `openai/whisper-large-v3` in the v1 Adapter; rationale: configurable arbitrary endpoints could exfiltrate the ASR credential, while model drift could invalidate the timestamp/cache contract.
- 2026-08-05: Refuse the previously exposed OpenRouter Key and require a regenerated local `.env.local` credential; rationale: cloud success based on a compromised secret is neither safe nor acceptable evidence.
- 2026-08-05: Pin Codex 0.146.0 to an exhaustive reviewed tool-free profile and hash its executable identity into Pipeline config; rationale: read-only sandbox and partial feature flags did not close browser/apps/plugin side effects.
- 2026-08-04: Add ADR-008 `openai-codex` as the normal mode and keep ASR separate; rationale: honor the user's local-Codex editorial request without falsely claiming Codex can hear video or running local model weights.
- 2026-08-04: Execute Codex with no model tools, read-only/no-approval, isolated config/rules, stdin payload, strict schema and a secret-stripped child environment; rationale: transcript/model output remains untrusted data and cannot gain an execution channel.
- 2026-08-04: Block full run creation and disable the Web start action when either selected real provider is not ready, while visibly warning on explicit Mock modes; rationale: a queued job must not look like real AI processing when ASR is absent.

- 2026-08-03: Choose modular monolith/ports and adapters; rationale: three entry points need one business implementation.
- 2026-08-03: Choose integer milliseconds; rationale: exact revision, SQLite, JSON, SRT and FFmpeg conversions.
- 2026-08-03: Choose fenced SQLite Task leases plus immutable atomic artifacts; rationale: CLI/Worker crash/race safety.
- 2026-08-03: Choose Pillow RGBA overlays; rationale: host compatibility and strong text/filter syntax separation.
- 2026-08-03: Choose `whisper-1` as capability-driven v1 default; rationale: official real segment/word timestamps.
- 2026-08-03: Choose stateless strict Responses with no tools and at most one repair; rationale: privacy and deterministic safety boundary.
- 2026-08-03: Publish validated renderer output with `link(2)` from a same-directory private temp name and fail if the destination exists; rationale: `os.replace` can overwrite a competing immutable revision artifact after an `exists()` race.
- 2026-08-03: Gate the active Python SQLite library on officially fixed WAL branches and use `synchronous=FULL`; rationale: durability and lease correctness depend on the embedded library, not a separate CLI version.
- 2026-08-03: Create only the next dependency Task after stage commit; rationale: its idempotency identity must include actual validated upstream output.
- 2026-08-03: Use one cancellation-aware process-group runner for pipeline FFmpeg/ffprobe work; rationale: a durable cancel must stop owned work before any success publication.
- 2026-08-03: Treat caller Asset scope only as a checked assertion and derive authority from the active TaskAttempt graph; rationale: API/service bugs must not widen a lease into another project, generation, candidate or revision.
- 2026-08-03: Persist proxy RenderJob intent and running state before FFmpeg I/O; rationale: failure, cancellation and crash recovery must remain user-observable and retryable.
- 2026-08-03: Use explicit transient exception types for bounded process timeouts; rationale: retry behavior must not depend on fragile message matching or generic runtime exceptions.
- 2026-08-03: Bind generated media access to committed Asset IDs and short-lived method/path/purpose HMAC URLs; rationale: HTML5 Range seek cannot attach Bearer headers, while local paths must never become a generic file interface.
- 2026-08-03: Treat Delivery input as an immutable approved-render snapshot and fail active snapshots atomically on revision or decision change; rationale: an offline Worker must not leave stale work appearing current.
- 2026-08-03: Send Web clip edits as field-level deltas; rationale: unchanged relative captions must be regenerated from absolute transcript time when source boundaries move.
- 2026-08-03: Freeze all cloud-affecting settings and provider/Prompt/schema versions in a closed canonical Pipeline config v2; rationale: queued or resumed work must never execute new semantics under an old fingerprint.
- 2026-08-03: Own OpenAI retries in the application with SDK retries disabled; rationale: request/retry/latency evidence and cancellation behavior must be exact and testable.
- 2026-08-03: Publish provider caches through an anchored `openat`/`O_NOFOLLOW` directory chain and fail closed on any present invalid record; rationale: unsafe cache bytes must be rejected before a paid request or DB success promotion.
- 2026-08-03: Permit only append-only provider evidence through an exact historical TaskAttempt fence after cancellation/lease loss; rationale: paid call facts must survive cancellation without granting stale workers any domain mutation authority.
- 2026-08-03: Bound FFmpeg raster rendering to finite still inputs and explicit 2/4 normal plus 1/1 retry thread profiles; rationale: one heavy task must remain locally predictable and a transient encoder stall must neither publish partial media nor lose its last progress evidence.
- 2026-08-04: Require committed stage dependencies to match their exact producing Task, canonical no-follow endpoint, size and SHA before consumption; rationale: a database success row or pathname alone cannot authorize changed bytes.
- 2026-08-04: Carry pinned descriptor/size/SHA evidence from render validation through immutable publication and Asset commit; rationale: ffprobe/full decode success must describe the exact bytes exposed to users.
- 2026-08-04: Stream Delivery ZIP members only from pinned FDs and revalidate the exact member tree after atomic no-replace rename; rationale: a root directory inode does not bind independently replaceable files inside it. See ADR-007.
- 2026-08-04: Persist unknown legacy stream selection as `NULL` and require a matching modern ingest to verify it; rationale: migration must not invent video/audio stream choices that were never observed.
- 2026-08-04: Use one shared domain/render caption expansion budget of at most 64 overlays; rationale: accepted EditPlans must be renderable without renderer-side silent truncation or unbounded FFmpeg fanout.
- 2026-08-04: Make the checked host Chrome path an explicit test-only setup contract with an overridable executable path; rationale: `make test` must fail early and actionably rather than discover an undeclared browser prerequisite after Python/Web tests.
- 2026-08-04: Export EditPlan v1 to a tracked JSON Schema and drift-check it in lint/tests; rationale: an in-memory schema assertion does not satisfy the product's exported-contract requirement.
- 2026-08-04: Fence temporary E2E cleanup with the device/inode captured at allocation and explicitly reinstall Worker signal handlers; rationale: cleanup and process ownership must survive endpoint replacement and non-job-control Bash signal inheritance.

## Risks and Mitigations

- Raster overlay performance: Spike with multiple Chinese cues and measure before M1 closes; use one static image per cue, not per frame.
- Sandbox VideoToolbox false-negative: always implement and test libx264 fallback; record host doctor separately.
- Long-media resource use: streaming I/O, bounded chunks/logs and single heavy worker are implemented; a 2.19 GB/46:20 run used about 18 MB project storage and 28.83 seconds, while 2–4 hour peak RSS/M3 throughput remains an explicitly unverified acceptance limitation.
- Source reference mutation: stat identity/re-hash checkpoints and deterministic failure.
- SQLite/filesystem split-brain: immutable paths, lease/revision fencing, hashes, validation and atomic publish.
- Model/schema drift: pinned SDK, configurable models, contract smoke, local validation and deterministic fallback.
- Visual heuristics overclaim: quality report distinguishes automatic from actual viewed status.
- Generation-scoped paths are implemented and covered by second-run/import-only migration plus long-media artifact-scope checks.
- Spawned-process independent-Engine claim, heartbeat, crash-expiry and busy-recovery tests now exercise the SQLite fence outside one process.
- Pinned file hashing polls cancellation in bounded blocks; FFmpeg/ffprobe use process-group cancellation and lease monitors. A short atomic filesystem operation remains non-preemptible, but it cannot publish after a failed lease/revision/hash fence.

## Recovery Notes

M14 implementation is complete at checkpoint `d40ec81`. Migration `d31a6e9f4b72` is applied to the real database; integrity/FK/drift checks pass and existing `7.28` is owned by `local-admin`. The Web opens as “我的项目”, and API authorization is membership-scoped through every descendant resource. `make lint` plus 559 Python, 23 Web, Mock Chrome and real API/Worker/SQLite/FFmpeg Chrome tests pass. The host-Chrome dashboard and workspace screenshots were viewed; the Browser skill runtime itself still exposes no registered browser. No long-input ASR/LLM call or `7.28` domain/media mutation occurred.

M12 implementation is complete at checkpoint `4e81d6c` on `origin/main`. Project `f91cb996f7534a6682aa5e5f01374b7b`, current generation-3 run `634c68f9d0b24c99b16ddac8d14ddfd7`, remains unchanged at 15 non-degraded descriptions and 15 succeeded Schema-4/no-blur clean proxies. The restarted clip-list API returns all 15 exact persisted Hooks; no paid Provider request was made. The board is `高光时刻`, one full-width horizontal row per clip, with `高光语句`, editor-only timed keywords and subtitles last. Final gates pass 540 Python, 21 Web and both Chrome flows. The in-app browser adapter again exposed no attached browser, so no MCP-control claim is made; the checked suites launched installed host Chrome and the real-backend success screenshot was actually viewed.

Before resuming, read the five files listed in `AGENTS.md`, run `git status --short --branch` and inspect the last five commits. Verify the most recent command recorded in `STATUS.md`; do not repeat completed discovery.

## Outcomes and Retrospective

M0 is complete at commit `136d8bd`. M1 is complete at commit `cfc8889`: two bounded subagent implementations integrated, 70 tests pass, two real Demos reached `delivered`, the first final was fully decoded and actually viewed, its immutable ZIP/hash/state were inspected, and the independent Reviewer returned PASS. M2 is complete at commit `09a6f10` with independent `PASS`: Alembic and the persistent six-stage pipeline are real, foreground/Worker ownership is shared and fenced, cancellation terminates subprocess groups, Asset authority is database-derived, RenderJob failures are durable, and 204 tests pass. M3 is complete at commit `f707e90` with independent `PASS`: FastAPI, Web, complete review/render/delivery CLI, signed Range media, atomic revision/decision invalidation and immutable Delivery are integrated; 233 Python tests, 11 Web tests and host Chrome E2E pass. The remaining mocked-API browser-composition P2 is explicitly assigned to M6. M4 is complete at commit `476ad89`: pinned real OpenAI adapters, strict cloud contracts, immutable caches, bounded retry/usage/cancellation evidence, no-Mock smoke validation and renderer reliability hardening passed both independent reviews, 328 Python tests, 11 Web tests and an actually viewed post-fix Demo. Real cloud entitlement remains honestly `not_run`.

M5 is complete at commit `7c145ec`. Long/chunked input, cancellation/lease recovery, spawned-process SQLite contention, explicit stream selection, VFR/rotation, exact committed-Asset dependencies, pinned render validation/publication, caption resource bounds, safe diagnostics and exact immutable Delivery publication are integrated. The final reviewer returned `PASS` after replaying the two prior Delivery races. Full gates are 428 Python plus 11 Web tests, and the fresh delivered Demo's final/contact sheet/manifest/ZIP were actually inspected. The available long fixture is only 46:20 on Apple M2, so 2–4 hour peak memory and M3 throughput remain truthful limitations for M6/final reporting rather than hidden success claims.

M6 is complete at implementation checkpoint `60283ba` plus the following documentation checkpoint. The browser-to-real-backend gap is closed with repeated host-Chrome runs and persisted lease/render/Delivery proof. Documentation/schema export, both focused re-reviews and the final Product Spec-wide verifier are PASS; setup, Doctor, lint, 433 Python/11 Web/two browser flows and a freshly viewed delivered Demo pass. The LiveClip v1 baseline is `delivered`; only the explicitly disclosed external cloud/hardware measurements remain unverified.

M7 local implementation is complete at checkpoint `0a0b08a`. The default real chain is strict OpenRouter Whisper Large V3 JSON ASR followed by the version-pinned hardened Codex CLI editor. Final local gates pass at 498 Python tests, 13 Web tests and both host-Chrome flows; Demo `demo_20260805T120045_8bc01ec3` reached `delivered`, its 1080×1920 final fully decoded, its ZIP passed integrity, and its contact sheet was actually viewed and recorded. The independent M7 Reviewer returned PASS with zero P0/P1/P2. Real OpenRouter cloud and the authorized 46:20 content run remain truthfully `not_run` because no regenerated safe Key exists.

M8 is complete at implementation commit `2bbdd4f` plus the publication-document checkpoint on `origin/main`. The latest real 46:20 generation 3 reaches `pending_review` with 33/33 fresh OpenRouter chunks, 41/41 host Codex edits, 15/15 non-degraded selected plans and 15/15 clean validated proxies. Historical generations 1/2 and 10 separate test projects were then removed from active state after exact backups and recoverable file isolation; only current `7.28` remains visible. Legacy schema/proxy, caption-boundary/punctuation, optional-word, cross-generation cache identity and CLI metadata gaps were reproduced and fixed with coverage. Final host Doctor/lint/527 Python/13 Web/two browser/Demo/real-smoke gates pass, and the final read-only verdict is `PASS` with P0=0/P1=0/P2=0. No credential, input media, database or generated artifact entered Git.

M9 is complete at implementation commit `c14c910` on `origin/main`. Layout is no longer an LLM output; active plans, review approval, render enqueue and FFmpeg execution all fail closed unless the system-owned layout is `center_crop`. The renderer contains one scale-to-fill/center-crop source branch and no blur/duplicated-foreground graph. Migration `c91f4e2a7b63` invalidated older media; all 15 real proxies were regenerated, fully decoded and independently viewed as consistent single-layer crops. Final gates pass at 531 Python tests, 13 Web tests and both browser flows; the M9 reviewer returned `PASS` with P0=0/P1=0/P2=0. No generated media, database, input or credential entered Git.

M10 is complete at implementation checkpoint `cb7be17` on `origin/main`. It adds no A/B entities or media. Existing candidates receive current-revision captions and read-only grounded keyword ranges; the batch service is one revision-fenced/idempotent SQLite transaction; and the Web owns independent video seek state plus conservative dirty/retry fencing. Real `7.28` acceptance observed 15 cards, 90 cues and 34 transcript-segment keyword ranges without changing Provider usage. Final gates pass at 540 Python tests, 19 Web tests and both Chrome flows, and independent review returned `PASS` with P0=0/P1=0/P2=0.

M11 is complete at implementation checkpoint `df8b8db` on `origin/main`. The review workspace now goes from Pipeline progress directly to the candidate board; it neither displays nor fetches the redundant full transcript. Per-candidate subtitles, grounded keyword navigation and candidate-detail context remain intact, while backend transcript/ASR capability is unchanged. Full gates pass at 540 Python tests, 20 Web tests and both host-Chrome flows; the real-backend delivered screenshot was actually viewed.

M12 is complete at checkpoint `4e81d6c` on `origin/main`. `ClipSummary.hook` is now the list's `高光语句`; timed phrases are explicitly internal `编辑关键词`. A semantic one-column list renders video/content horizontally on desktop and subtitles as each row's final section. The real `7.28` API proved all 15 Hooks without changing Provider usage or media, and full gates pass at 540 Python, 21 Web and both host-Chrome flows with an actually viewed screenshot.

M13 is complete at implementation checkpoint `1ec1437`. It adds a state-preserving `export-review` path and immutable v2 offline package with clean MP4s, SRTs, complete editorial descriptions, grounded keyword timing, CSP-constrained file HTML, manifest, checksums and ZIP. A transactionally captured publication fence proves every current revision/render/producer/asset and withdraws concurrent races; crash attempts are safely recovered. Real `7.28` v003 has 15 clips, all hashes/ZIP members/full decodes pass, and Project/review/Delivery/Provider state is unchanged. Full gates pass at 554 Python, 21 Web and both normal browser E2Es; 16 final package/fence/orphan tests pass after review hardening. Independent final verification is `PASS` with P0=0/P1=0/P2=0. The file-only page's separate in-app-browser visual check is truthfully blocked because the Browser runtime exposes no registered Chrome connection.

M14 is complete at implementation checkpoint `d40ec81` plus the following status checkpoint. Durable workspace identities and Project memberships now back the editor-facing “我的项目” dashboard; Project and every descendant API resource are server-side member-scoped, and owner-only membership management is enforced independently of the Web. Existing single-user loopback operation remains compatible. The real database migrated without data loss, and the unchanged `7.28` Project is immediately visible to its migrated owner. Full gates pass at 559 Python, 23 Web and both Chrome E2Es; the real test uses isolated Mock AI plus actual API, leased Worker, SQLite and FFmpeg. No paid Provider call was repeated.

The 2026-08-16 transport-stream synchronization correction is complete pending its Git checkpoint. Real `8-16-1.ts` ran through 60 successful OpenRouter ASR chunks and 45 successful Codex editorial calls before the defect was reported. The renderer now uses the ADR-019 shared-timeline accurate-seek contract, and all 15 proxy jobs were regenerated as immutable v4 artifacts without repeating either Provider. Their measured MP4 stream starts differ by at most one 25-fps frame, all 15 quality/full-decode reports pass, `make lint` passes, and the complete gate passes at 726 Python tests, 57 Web tests, Mock Chrome 1/1 and isolated real API/Worker/SQLite/FFmpeg Chrome 1/1.
