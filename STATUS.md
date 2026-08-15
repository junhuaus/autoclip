# LiveClip status snapshot

Updated: 2026-08-13 CST

Current product baseline: `0.1.0`

Current milestone: v0.2 V2-M3 selective editor handoff starting

Branch: `main` tracking `origin/main`

Latest committed v0.2 checkpoint: `f12b7f8` (`feat: add professional project lifecycle`)

## Current user-visible result

LiveClip now has local administrator/member accounts, administrator user management, private-by-default Projects, owner/editor/reviewer/viewer roles, atomic ownership transfer and capability-gated Web/API behavior. The V2-M2 worktree adds a professional business lifecycle independent of Pipeline/Delivery status, assignment, priority, due date, private/workspace visibility, archive/restore, activity history and lifecycle-oriented dashboard filters.

Open `http://127.0.0.1:5173`. Local API/Worker/Web are running through `make dev`; health is `ok`. Current real Project `7.28` remains ID `f91cb996f7534a6682aa5e5f01374b7b`, generation-3 run `634c68f9d0b24c99b16ddac8d14ddfd7`, with 15 clean no-blur review proxies. It is still private, assigned to `local-admin`, priority `normal`, and was conservatively backfilled to business lifecycle `editorial_review`. It was not reprocessed and no paid ASR/LLM call was made during identity/lifecycle work.

The UI displays business lifecycle and technical status separately. A Project may correctly show `编辑审核` together with technical `已交付`; creating a file package is not evidence that a human published it.

## Completed v0.2 work

- V2-M0: product/research contract, ADR-014 and phased Living ExecPlan.
- V2-M1: Argon2id credentials; opaque hashed sessions; CSRF; persisted login throttling; administrator create/edit/disable/reactivate/reset/role changes; last-administrator invariant; private Project isolation; viewer role; ownership transfer; capability DTOs and Web gating.
- V2-M2 core: `draft|processing|needs_attention|editorial_review|changes_requested|approval|ready_to_publish|published|archived`; central legal transitions; optimistic `management_version`; active-member assignment; priority; timezone-aware due date; archive/restore; Pipeline system signals; append-only Project activity; lifecycle dashboard filters; workspace-visible read-only Projects.
- Removing a currently assigned member returns a stable 409 until reassigned. Archived Projects allow only read plus owner restore/management. An active Pipeline run must finish or be cancelled before archive.
- Migration `a84e2d7c9f10` is additive for SQLite and does not rebuild the referenced `projects` parent table.

## Real database evidence

- Old API/Worker/Vite processes were stopped before migration.
- Pre-migration `PRAGMA quick_check` returned `ok`; foreign-key check returned no rows; revision was `f42b7c1d9e63`; one Project existed and `7.28` matched its stable ID.
- WAL checkpoint completed before backup.
- Ignored backup: `data/projects/migration-backups/liveclip-pre-a84e2d7c9f10-20260815T090223+0800.sqlite3`.
- Backup SHA-256: `82ec8dfeb374ceb5c91b39d740171b4830816aa55b570072c7152ce5a6794926`.
- Real migration to `a84e2d7c9f10` succeeded. Post-migration quick check is `ok`, foreign-key check is empty, and the same one Project remains.

## Latest validation

- `make lint`: passed Ruff, Ruff format, mypy (117 source files), EditPlan schema and TypeScript.
- `make test`: Python collected and passed `575` tests with 13 warnings; Web passed `28` tests.
- `npm run e2e:mock`: passed one controlled Chrome flow after adding the Project activity route fixture.
- `npm run e2e:real`: passed one isolated real FastAPI + leased Worker + SQLite + FFmpeg + login + revision + final render + Delivery ZIP Chrome flow. The test asserts business `editorial_review` beside technical `delivered`.
- Fresh temporary `alembic upgrade head` and `alembic check`: passed with no generated migration operations.
- Real API health and `GET /projects` returned Project `7.28` with private visibility, owner capability set and legal next lifecycle targets.
- MCP/in-app Browser discovery provided no controllable browser instance in this environment. Host Google Chrome was used by Playwright E2E; MCP Browser success is not claimed.

## Still pending

- V2-M3: selectable individual current MP4/SRT downloads and immutable Jianying/CapCut-friendly `EditPackage` containing clean H.264/AAC MP4, basename-matched UTF-8 SRT, CSV/JSON descriptions, thumbnails, checksums, Chinese import guide and ZIP.
- V2-M4: versioned platform presets, release metadata/checklists/calendar and manually recorded publication outcome.
- V2-M5: retention/storage policy, security/recovery hardening, external Jianying/CapCut import acceptance where installed, final full acceptance and independent verification.
- Threaded timecode comments, reusable saved views and cross-Project bulk assignment are staged production-workflow enhancements after the V2-M3 handoff slice.
- Optional scoped PATs and explicit audited administrator Project override remain documented extensions. The v0.1 environment Bearer bridge stays for CLI/API compatibility.
- Representative 2–4 hour Apple M3 resource measurements remain unverified. The existing 46:20 real OpenRouter/Codex result remains the longest actual run and must not be repeated for v0.2 metadata/export work.

## Security and worktree

- Never stage `.env`, `.env.local`, `OPENROUTER_SETUP.md`, `input/`, SQLite, media, caches, E2E output, deliveries or migration backups.
- No credential value was read or printed. No source media, Project content, render, Delivery or Provider usage was changed.
- V2-M2 is committed locally at `f12b7f8`. Only the following recovery-document update should remain before its documentation checkpoint.

## Next concrete task

Commit/push this V2-M2 recovery update, then begin V2-M3 by defining the immutable `EditPackage` domain/application contract and migration. Reuse current final/proxy Assets; do not call ASR/LLM or reprocess `7.28`.

## Resume instructions

Read `AGENTS.md`, `docs/PRODUCT_SPEC.md`, `docs/PRODUCT_SPEC_V0.2.md`, `docs/SOLUTION.md`, `.agent/PLANS.md`, `docs/exec-plans/liveclip-v0.2.md` and this file. Run `git status --short --branch`, `git log -5 --oneline`, `LIVECLIP_DATABASE_PATH=$PWD/data/projects/liveclip.sqlite3 .venv/bin/alembic current`, and `curl -sS http://127.0.0.1:8765/api/v1/health`. Continue with “Next concrete task”; preserve ignored real media/data and do not repeat paid Provider work.
