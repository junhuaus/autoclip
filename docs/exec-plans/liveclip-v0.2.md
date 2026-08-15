# LiveClip v0.2 Living ExecPlan

This plan follows `.agent/PLANS.md`. It is the durable implementation contract for `docs/PRODUCT_SPEC_V0.2.md`. The v0.1 baseline and historical evidence remain in `docs/exec-plans/liveclip-v1.md` and must not be rewritten as if new v0.2 work had already existed.

## Purpose / Big Picture

A small video-production team can sign in to one local LiveClip installation, work only on authorized Projects, move each Project through an auditable editorial/release lifecycle, select exact current clips and download an immutable package that imports clean video and editable subtitles into Jianying/CapCut Desktop/Web. An administrator can safely manage accounts, authority and ownership without handling plaintext credentials or reprocessing media.

## Context and Orientation

Baseline Git checkpoint is `0f34e2b` on `main`; package version is `0.1.0`. v0.1 already provides real OpenRouter ASR, Codex editing, durable SQLite Tasks, clean no-blur proxies, Project memberships, exact revision/render fences, formal Delivery, offline review packages and the editor-facing “我的项目” dashboard. V2-M1 is committed through `d513abf`. Existing real Project `f91cb996f7534a6682aa5e5f01374b7b` must remain intact and must not trigger paid ASR/LLM during identity, lifecycle or export implementation.

Relevant current locations:

- Identity bridge: `src/liveclip/application/workspace.py`, `src/liveclip/db/workspace_repository.py`, `src/liveclip/api/security.py`.
- Persistence: `src/liveclip/db/models.py`, Alembic head `a84e2d7c9f10` after the V2-M2 checkpoint.
- API composition: `src/liveclip/api/app.py`, `schemas.py`, `bootstrap.py`.
- Web shell and Project workspace: `apps/web/src/App.tsx`, `ProjectWorkspace.tsx`, `api.ts`, `types.ts`.
- Delivery/export patterns: `src/liveclip/application/deliveries.py`, `offline_review.py`, `src/liveclip/delivery/`.
- v0.2 product contract/research: `docs/PRODUCT_SPEC_V0.2.md`, `docs/research/editor-handoff-platforms.md`, ADR-014.

## Scope and non-goals

All v0.1 behavior remains supported. v0.2 adds accounts, authorization, lifecycle, selective editor export and release planning. It does not add an external IdP/database/queue, anonymous public Projects, social-platform credential storage, automatic browser posting, or undocumented Jianying native draft generation. A later verified FCPXML adapter is optional and cannot delay the MP4/SRT package.

## Architecture Summary

The existing dependency direction remains unchanged. New application services own authentication, administration, authorization policy, lifecycle, audit, edit-package and release operations. SQLAlchemy/SQLite provides adapters. FastAPI sets one authenticated principal; Web renders returned capabilities and never recreates access rules. Technical processing state and business lifecycle are separate projections. Export snapshots exact selected revisions and committed Assets, builds outside the write transaction and rechecks the fence around no-replace publication.

## Milestones and progress

### V2-M0 — Freeze v0.1 and design v0.2

- [x] 2026-08-13 Confirm clean `main` at `0f34e2b`, package `0.1.0`, current database/media and passing M14 evidence.
- [x] 2026-08-13 Capture user/system/Project role matrix, default-private visibility, lifecycle and release concepts in `PRODUCT_SPEC_V0.2.md`.
- [x] 2026-08-13 Check current primary CapCut, YouTube, TikTok and Apple interchange documentation and record evidence/limits.
- [x] 2026-08-13 Adopt ADR-014: local sessions, distinct authority dimensions, business lifecycle and immutable MP4/SRT editor package.
- [x] 2026-08-13 Create this self-contained Living ExecPlan and update the recovery snapshot.
- [x] 2026-08-13 Commit v0.2 planning checkpoint `dfc1639` without secrets/generated data and publish it with the following status checkpoint.

### V2-M1 — Accounts, administrator console and authorization

- [x] 2026-08-13 Add password/session/login-attempt/audit persistence migration and prove fresh/legacy migration checks. Real DB migration remains deferred until the user opts into a bootstrap password.
- [x] 2026-08-13 Add Argon2id password hashing and verification; salted verifier only, neutral login responses and secrecy tests.
- [x] 2026-08-13 Add bootstrap administrator, login/logout/current-session, expiry, hashed opaque session storage, revocation, CSRF and persisted rate limiting.
- [x] 2026-08-13 Add administrator user list/create/update/disable/reactivate/password-reset/system-role grant/revoke; forbid disabling/demoting the final enabled administrator.
- [x] 2026-08-13 Add central authorization policy for system and Project roles, route enforcement and client capability DTOs. Explicit administrator Project override and optional PATs are deferred extensions, not requirements for Project-owner isolation.
- [x] 2026-08-13 Add `viewer`, default-private visibility, atomic ownership transfer and server-derived allowed actions/capabilities.
- [x] 2026-08-13 Add Web login/logout and administrator console while retaining v0.1 token compatibility for CLI/API migration.
- [x] 2026-08-13 Unit/integration/component/browser coverage proves login, create/edit/disable, revocation, CSRF, Argon2 secrecy, role policy, legacy migration and two-user private Project/media/ZIP denial. PAT remains a documented later extension.
- [x] 2026-08-13 Run Ruff/mypy/TypeScript/full Python/Web tests, inspect isolated login/admin UI without paid Provider work, review, commit `a5e52a3` and push. Real database login opt-in remains intentionally deferred.

### V2-M2 — Project lifecycle and production operations

- [x] 2026-08-13 Add lifecycle/assignment/due-date/priority/archive/audit schemas, optimistic management version and central transition table.
- [x] 2026-08-13 Derive processing/attention signals without collapsing Pipeline state into business lifecycle; Delivery remains a separate technical fact and never implies publication.
- [~] Add Project activity timeline and revision/timecode comments with resolution state. The append-only Project activity timeline is complete; threaded timecode comments are staged after editor handoff.
- [~] Add professional dashboard filters, saved views and bulk assignment. Lifecycle filters, assignee and priority are complete; reusable saved views and cross-Project bulk assignment remain staged.
- [x] 2026-08-13 Cover illegal transitions, concurrent updates, active-run archive refusal, archived write denial, exact restore, activity history, workspace read-only access and assigned-member removal conflict.
- [x] 2026-08-13 Back up and migrate the real database to `a84e2d7c9f10`; preserve Project `7.28` as private and backfill it to `editorial_review` without paid Provider work or media mutation.
- [x] 2026-08-13 Pass Ruff/format/mypy/schema/TypeScript, 575 Python tests, 28 Web tests, Mock Chrome E2E and real FastAPI/leased-Worker/SQLite/FFmpeg Chrome E2E.

### V2-M3 — Selective editor handoff

- [ ] Define versioned `EditPackage` schema, selected-clip request and immutable DB status.
- [ ] Add individual current MP4/SRT downloads with authorization and stable filenames.
- [ ] Generate selected-package clean MP4/SRT, CSV/JSON metadata, thumbnails, Chinese Jianying guide, checksums and ZIP.
- [ ] Validate H.264/AAC/progressive/yuv420p/fast-start/full decode and plain UTF-8 no-BOM SRT with matching basenames.
- [ ] Add Web clip selection/export history/download; never include stale or unauthorized Assets.
- [ ] Import a generated package into installed CapCut/Jianying Desktop if available; otherwise record that external UI acceptance as pending without overclaim.

### V2-M4 — Release planning and platform packages

- [ ] Add versioned platform preset registry and preflight results.
- [ ] Add ReleaseItem metadata, assignment, approval, planned time and manually recorded outcome/URL.
- [ ] Add cover selection, safe-zone preview, Hook/first-frame/subtitle/right-risk checklists.
- [ ] Generate platform-ready package with chosen caption mode and editable release copy.
- [ ] Add release calendar/queue views and basic manually entered result snapshots.

### V2-M5 — Hardening and acceptance

- [ ] Exercise backup/restore, migration rollback, concurrent revocation, expired session/PAT and permission changes during long exports.
- [ ] Add storage/retention visibility and safe archive/purge policies.
- [ ] Run `make doctor`, `make lint`, `make test`, `make demo` and browser E2E; no real Provider call unless content generation itself changes.
- [ ] Run independent Product Spec verification, close evidenced gaps, update operator/admin/editor docs and publish v0.2 checkpoint.

## Work breakdown and file ownership

The main Agent exclusively owns migrations, shared schemas, dependency/lock changes, Product Spec/Solution/ADR, this ExecPlan and STATUS. If parallel writers are later used, authentication/admin, lifecycle and export work must receive disjoint modules and tests; no two writers modify `models.py`, Alembic head, `api/app.py`, Web `App.tsx` or shared TypeScript/Pydantic DTOs concurrently.

V2-M1 implementation order:

1. Write authorization matrix tests and credential/session model.
2. Add migration and repository/application services.
3. Integrate request principal, cookie/PAT authentication and CSRF.
4. Apply central policy to every route and legacy token bridge.
5. Add login/admin Web surfaces.
6. Migrate real data, run two-user tests, review and checkpoint.

V2-M2 implementation order:

1. Define pure lifecycle/priority values and one legal-transition table.
2. Add additive SQLite columns and conservative backfill without rebuilding the referenced `projects` parent table.
3. Add owner-only compare-and-swap management/lifecycle services and append-only activity queries.
4. Synchronize Pipeline terminal signals while preserving archived state and separate technical status.
5. Add capability-driven dashboard/workspace controls and exercise private/workspace viewers.
6. Checkpoint WAL, copy/hash the real database, migrate, validate `7.28`, run full gates and checkpoint.

V2-M3 begins with the existing Delivery/Asset/task patterns, but adds a distinct immutable `EditPackage`; it must not overload formal Delivery or claim undocumented native Jianying draft support.

## Concrete commands and expected observations

From repository root:

```bash
git status --short --branch
git log -5 --oneline
.venv/bin/alembic current
.venv/bin/alembic check
make lint
make test
make dev
```

Expected at V2-M0: only tracked planning documents differ; no input/data/secret file is staged. Expected at V2-M1: migration head advances once; old Project count/revisions/renders/usage remain unchanged; signed-out protected JSON returns 401; administrator login returns an HttpOnly session cookie; two users see different Project lists; role-denied mutations return stable 403; disabled-user sessions stop working immediately.

Expected at V2-M2: business and technical Project states are both visible; stale `management_version` writes return 409; a workspace-visible non-member has only `read`; archive blocks mutation and restores exactly; activity records actor/reason; `PRAGMA quick_check` is `ok`, foreign-key check is empty, and the real Project/media counts are unchanged.

## Validation and acceptance

- Authentication: verifier bytes cannot authenticate as plaintext, password/token values never appear in serialized models/logs/errors, session identifiers are random and stored hashed, logout/disable/reset revokes access.
- Authorization: matrix tests cover every unsafe route and each Project role. Enumeration of another user's private resource yields 404.
- Migration: v0.1 database backup, row counts, integrity, foreign keys and current `7.28` Project/Asset hashes match before/after except intended identity/lifecycle columns.
- Lifecycle: every legal/illegal transition and concurrency conflict is tested; history is append-only.
- Export: selection order, revision/Asset fence, codec/SRT/ZIP/checksum/path safety and retry/crash recovery are verified from actual bytes.
- UI: login, administrator users, private Project lists, lifecycle actions, selective export and all empty/loading/error/disabled states have observable component plus browser coverage.

## Idempotency, retry and recovery

User create/update/reset, ownership/role/visibility/lifecycle changes and export creation use explicit transaction boundaries and Idempotency-Key where a client retry could repeat an effect. Password reset/session revocation commit atomically. A failed/expired login attempt never creates a partial session. Edit-package allocation uses immutable versions; a crash leaves only a strictly named private attempt, recoverable by exact snapshot validation. Permission and selected-revision fences are rechecked immediately before and after publication; loss withdraws the new package without touching older versions.

Before each real migration, checkpoint WAL and copy the database to ignored `data/projects/migration-backups/` with hash evidence. Never use destructive reset or reprocess `7.28` to test non-media behavior.

## Surprises and Discoveries

- 2026-08-13: v0.1 package/version is already exactly `0.1.0`, so no source-version edit is needed to freeze the baseline.
- 2026-08-13: v0.1 Project membership correctly isolates resources but its environment-token identity cannot satisfy login, password reset, user disable, session revocation or administrator audit.
- 2026-08-13: Current CapCut documentation supports editable SRT import on Desktop/Web but not direct mobile import. Clean MP4 + matched UTF-8 SRT is therefore a truthful Jianying handoff; native draft files are not.
- 2026-08-13: YouTube and TikTok primary documentation support the current H.264/AAC MP4 direction, while account/platform-specific duration and policy checks cannot be represented by one permanent global number.
- 2026-08-13: OWASP recommends Argon2id and HttpOnly/SameSite browser sessions. V2-M1 uses Argon2id at 64 MiB/time-cost 3, opaque random session tokens stored only as SHA-256 digests, and synchronizer CSRF tokens derived from the HttpOnly token.
- 2026-08-13: `browser:control-in-app-browser` initialized successfully but `agent.browsers.list()` returned no browser instance. After following its troubleshooting instructions, an isolated host Chrome exercised login and administrator navigation and produced viewed screenshots; MCP Browser success is not claimed.
- 2026-08-13: Full Python regression passed 569 tests and Web regression passed 25 tests after the first V2-M1 slice. Targeted migration/identity/authorization tests subsequently passed 21 tests after user-edit support was added.
- 2026-08-13: Ownership transfer now updates both membership roles and `Project.owner_id` atomically, audits member/ownership changes with request correlation IDs, and exposes actions from the same server policy used by route enforcement. A known non-member receives 404 for private Project, committed media and Delivery ZIP IDs.
- 2026-08-13: The real Chrome E2E originally expected the v0.1 shared-token settings flow. v0.2 correctly rendered login instead, so the E2E was migrated to a temporary bootstrap administrator password and then passed the real FastAPI/Worker/SQLite/FFmpeg flow. Full gates passed 570 Python tests, 27 Web tests, Mock Chrome E2E and real Chrome E2E.
- 2026-08-13: Rebuilding SQLite's referenced `projects` parent table in Alembic failed safely before commit because `project_members` retains its foreign key. The final migration is additive `ALTER TABLE ADD COLUMN` plus indexes/backfill; typed domain values and compare-and-swap repositories enforce the new contract. Fresh migrations and `alembic check` pass.
- 2026-08-13: The real database was WAL-checkpointed and copied to ignored `data/projects/migration-backups/liveclip-pre-a84e2d7c9f10-20260815T090223+0800.sqlite3` (SHA-256 `82ec8dfeb374ceb5c91b39d740171b4830816aa55b570072c7152ce5a6794926`) before migration. Post-migration quick check is `ok`, foreign-key check is empty and Project `7.28` remains private at the same ID.
- 2026-08-13: The first updated real Chrome E2E expected the old derived `delivered` badge in the hero. The UI correctly showed business `editorial_review` beside technical `已交付`; the assertion now proves both states rather than collapsing them. Full gates pass with 575 Python and 28 Web tests plus both Chrome E2Es.

## Decision Log

- 2026-08-13: Call the next product line v0.2 while preserving `0.1.0` as the actual package baseline; alternative was silently extending v0.1; rationale: identity/lifecycle/export contracts are material product changes and need migration boundaries.
- 2026-08-13: Separate system role, Project role and visibility; alternative was one role enum; rationale: administrator governance, editorial duties and discoverability answer different authorization questions.
- 2026-08-13: Use local opaque sessions plus optional PATs; alternative was continuing shared environment tokens or adding external OAuth; rationale: administrators need revocation and user lifecycle while the local product must remain self-contained.
- 2026-08-13: Separate business lifecycle from Pipeline status; alternative was expanding the derived Project status string; rationale: processing facts cannot represent assignment, approval, publish and archive intent.
- 2026-08-13: Add EditPackage and ReleaseItem rather than overloading Delivery; rationale: clean editor handoff, approved final delivery and platform publication have different eligibility and evidence.
- 2026-08-13: Treat successful Delivery as `ready_to_publish` only for legacy backfill and never as `published`; rationale: file creation is not evidence that a human published to a platform.
- 2026-08-13: Reject removal of the current assignee until reassignment; alternative was leaving a dangling assignment or silently clearing it; rationale: explicit workflow ownership is safer and auditable.

## Risks and Mitigations

- Password implementation error: use a reviewed library/primitive, strict parameters, constant-time verification, neutral errors and dedicated tests; never implement a novel hash.
- Cookie/CSRF confusion with PAT auth: explicit credential kind in the principal; unsafe cookie requests require CSRF while Authorization-header requests do not rely on ambient cookies.
- Administrator overreach: explicit audited override; never silently add membership or transfer ownership.
- Legacy lockout: one-time bootstrap/migration path and v0.1 token bridge remain until admin login is proven.
- Permission TOCTOU during export: transactionally capture and recheck membership, selection, revision and Asset identity around publication.
- Undocumented Jianying format churn: ship standards-based MP4/SRT and verify real import; native draft remains excluded.
- Platform policy drift: presets are versioned and linked to check date; UI labels account-specific checks as required rather than universally “passed”.

## Recovery Notes

V2-M1 is committed through `d513abf`. The current V2-M2 worktree advances Alembic to `a84e2d7c9f10`, implements the professional lifecycle/operations UI and passes all full gates; commit/push it before beginning V2-M3. The real database is already backed up and migrated, services are running on `127.0.0.1:8765` and `127.0.0.1:5173`, and `7.28` must not be reprocessed. Next implement the distinct immutable selective `EditPackage` from exact current revisions/assets, then add individual MP4/SRT downloads and the editor package UI. Do not apply a bootstrap password to the real database without an explicit local secret configured outside Git.

## Outcomes and Retrospective

V2-M0 is complete at checkpoint `dfc1639`; V2-M1 is complete through `d513abf`. V2-M2 core now delivers separate professional lifecycle, private/workspace visibility, assignment, priority, due dates, archive/restore and activity history without changing v0.1 media facts or making a paid Provider call. Comments, saved views and bulk assignment remain explicitly staged enhancements. Primary documentation supports the next MP4/SRT export decision and exposes mobile/native-draft limitations, preventing an unverified “Jianying project” claim.
