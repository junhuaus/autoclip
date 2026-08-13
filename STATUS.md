# LiveClip status snapshot

Updated: 2026-08-13 12:08 CST
Current milestone: M14 collaborative video-editor Project workspace implementation complete; Git checkpoint pending
Branch: `main` tracking `origin/main`
Latest committed implementation: `1ec1437` (`feat: export fenced offline review packages`)

## Current user-visible outcome

Open `http://127.0.0.1:5173`. The home page is now a concise “我的项目” workspace for video editors:

- personal Project, attention, processing and delivered counts;
- search plus workflow-state filters;
- one card per accessible Project with status, next action, owner, member count and current role;
- a focused Project workspace with owner-managed editor/reviewer membership;
- existing horizontal “高光时刻” rows, “高光语句”, editor-only timed keywords and subtitles last.

This is not a browser-only filter. Migration `d31a6e9f4b72` adds local workspace users, Project owner and memberships. `GET /projects` and every Project/run/clip/render/Delivery route enforce current membership; inaccessible resources return not-found. Only the owner manages members. Distinct usernames can authenticate through environment-only Bearer tokens; token values never enter SQLite, logs, responses or the frontend bundle. v1 roles describe workflow responsibility; all members otherwise share editing/review actions.

The real Project remains `7.28` (`f91cb996f7534a6682aa5e5f01374b7b`), generation-3 run `634c68f9d0b24c99b16ddac8d14ddfd7`, `pending_review`, with 15 non-degraded clean no-blur proxies. M14 assigned it to migrated owner `local-admin` without rerunning ASR/LLM or changing clip/review/render/Delivery state.

## Durable real-media evidence retained

- Source: ignored read-only `input/7.28.mp4`, 2,190,937,089 bytes, 2,780.437 seconds, persisted SHA-256 `595cc75a65fe8d9faa3b41ba9f5b58b307d1b0a41236f7fc6016c0c1ae8acd03`.
- Real generation 3: 33/33 OpenRouter Whisper calls, 248 absolute-time segments, 41/41 Codex editorial calls and 15/15 non-degraded selected plans.
- Current proxies: all 15 are H.264/AAC 540×960 direct center crops, automatically validated and fully decoded; blurred background and duplicated foreground are prohibited.
- Top clip `73ab6116e49d4d9d837d469274aa47d5`: `KTV唱歌前的快速热身法`.
- Top video: `/Users/junhuaxu/Workspace/AGI/liveclip-ai/data/projects/f91cb996f7534a6682aa5e5f01374b7b/runs/g003/renders/proxies/73ab6116e49d4d9d837d469274aa47d5/r002/s-baa64c00a3180462/t-215fc4b619474c48/review.mp4`.
- Top contact sheet: `/Users/junhuaxu/Workspace/AGI/liveclip-ai/data/projects/f91cb996f7534a6682aa5e5f01374b7b/runs/g003/renders/proxies/73ab6116e49d4d9d837d469274aa47d5/r002/s-baa64c00a3180462/t-215fc4b619474c48/quality/contact-sheet.png`.
- Current offline review package: `/Users/junhuaxu/Workspace/AGI/liveclip-ai/data/projects/f91cb996f7534a6682aa5e5f01374b7b/offline-review-packages/v003` with 15 MP4s/SRTs/descriptions and `offline-review.zip`; manifest SHA-256 `7f52624db226c71cf3d661b3db30066f67810545424328264a7b837de6f07f25`, ZIP SHA-256 `5851d26406258838a140f0ece4f5be44bb8a1ff325189055f26bc10d754eb645`.

## M14 implementation

- Added `WorkspaceUser`, `ProjectMember`, `Project.owner_id`, service/repository ports and safe member DTOs.
- Added Alembic revision `d31a6e9f4b72`; applied it to the real database. Alembic head/drift, `PRAGMA integrity_check` and `PRAGMA foreign_key_check` pass.
- Added `GET /api/v1/session` and Project member list/add/remove routes.
- Added environment-authenticated caller identity, distinct per-user token mapping and per-caller idempotency scope.
- Added server-side access checks to Project/run/clip/render/Delivery queries and mutations.
- Rebuilt Web home as an editor Project manager; moved Provider/token diagnostics to the account/system popover.
- Added owner-only membership UI and kept the existing candidate-local review experience intact.
- Added backend, migration, API, component and both Chrome E2E regression coverage.
- Updated Product Spec, Solution, API, architecture, README, ADR-013 and Living ExecPlan.

## Validation for this worktree

- `make lint`: PASS; Ruff, format (180 files), mypy (111 source files), EditPlan schema drift and TypeScript all pass.
- `make test`: PASS; 559 Python tests, 23 Web component tests, one Mock Chrome E2E and one real FastAPI/leased-Worker/SQLite/FFmpeg Chrome E2E.
- Latest real E2E: Project `3ced841d8d21439d9d9be233e7f4c27e`, six stages, eight Tasks/attempts, Delivery v001; it used isolated temporary Mock AI and cleaned up after success.
- Actual host-Chrome screenshots were viewed: the Project dashboard hierarchy/search/filter/card layout is coherent, and the real delivered workspace still shows members, pipeline, high-impact row/editor and Delivery controls correctly.
- Browser skill initialization followed the prescribed runtime, but browser discovery returned `[]`; no MCP-control success is claimed. Host Playwright Chrome provided the checked visual and browser-flow evidence.
- The real API currently returns one `7.28` Project for `local-admin`, with owner/member/current-role fields. Provider health reports the configured OpenRouter/Codex chain ready without exposing credentials.

## Not rerun or externally unverified

- No paid OpenRouter/Codex call was made for M14 and no existing long Project was reprocessed.
- Representative 2–4 hour Apple M3 peak memory/runtime/disk remains unmeasured; the real available sample is 46:20 on Apple M2.
- The separate file-only v003 offline page still lacks an MCP-browser visual check because no browser is registered to that runtime; its files, checksums, ZIP structure and all video decodes already pass.

## Security and worktree state

- Never stage `.env`, `.env.local`, `OPENROUTER_SETUP.md`, `input/`, SQLite, media, caches, E2E output, deliveries or migration backups.
- The local OpenRouter credential remains only in ignored environment; its value was not printed or persisted by M14.
- Source video and all existing generated media are unchanged.
- Local API/Worker/Web should be running at `127.0.0.1:8765` and `127.0.0.1:5173`; restart `make dev` after source migration/auth changes before handoff.
- Current source/docs/tests changes are unstaged pending final diff, secret-scope check, commit and push.

## Next concrete task

Restart `make dev`, verify `/api/v1/session`, member-scoped `/api/v1/projects` and the Vite home page, then create/push the scoped M14 checkpoint and record its hash here.

## Resume instructions

Read `AGENTS.md`, `docs/PRODUCT_SPEC.md`, `docs/SOLUTION.md`, `.agent/PLANS.md`, `docs/exec-plans/liveclip-v1.md` and this file. Run `git status --short --branch`, `git log -5 --oneline`, and verify the most recent M14 test results above. Preserve ignored input/generated data and do not repeat the paid `7.28` ASR/LLM run.
