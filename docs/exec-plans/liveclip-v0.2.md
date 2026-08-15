# LiveClip v0.2 Living ExecPlan

This plan follows `.agent/PLANS.md`. It is the durable implementation contract for `docs/PRODUCT_SPEC_V0.2.md`. The v0.1 baseline and historical evidence remain in `docs/exec-plans/liveclip-v1.md` and must not be rewritten as if new v0.2 work had already existed.

## Purpose / Big Picture

A small video-production team can sign in to one local LiveClip installation, work only on authorized Projects, move each Project through an auditable editorial/release lifecycle, select exact current clips and download an immutable package that imports clean video and editable subtitles into Jianying/CapCut Desktop/Web. An administrator can safely manage accounts, authority and ownership without handling plaintext credentials or reprocessing media.

## Context and Orientation

The frozen v0.1 baseline is `0f34e2b`; package version remains `0.1.0`. V2-M4 is checkpointed at `06b7054` on `main`. v0.1 already provides real OpenRouter ASR, Codex editing, durable SQLite Tasks, clean no-blur proxies, Project memberships, exact revision/render fences, formal Delivery, offline review packages and the editor-facing “我的项目” dashboard. Existing real Project `f91cb996f7534a6682aa5e5f01374b7b` must remain intact and must not trigger paid ASR/LLM during identity, lifecycle or export implementation.

Relevant current locations:

- Identity bridge: `src/liveclip/application/workspace.py`, `src/liveclip/db/workspace_repository.py`, `src/liveclip/api/security.py`.
- Persistence: `src/liveclip/db/models.py`, code and real-database migration head `d8f3a6b1c420`; the controlled V2-M4 migration preserved every protected row count.
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
- [x] 2026-08-13 Add central authorization policy for system and Project roles, route enforcement and client capability DTOs. Ordinary administrator requests remain Project-member scoped; V2-M5 later added a separate audited governance context for workspace-wide inventory and owner recovery. Optional PATs remain deferred.
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

- [x] 2026-08-15 Define versioned `EditPackage` schema, exact selected-revision snapshot, immutable DB status and durable leased Task execution with idempotency, failure and retry synchronization.
- [x] 2026-08-15 Add signed individual current MP4/SRT downloads with Project authorization, revision-bound signatures and stable filenames.
- [x] 2026-08-15 Generate selected-package clean MP4/SRT, CSV/JSON metadata, thumbnails, Chinese Jianying guide, checksums and ZIP from pinned successful render Assets.
- [x] 2026-08-15 Validate H.264/AAC/progressive/yuv420p/fast-start/full decode and plain UTF-8 no-BOM SRT with matching basenames; reject stale revisions, untrusted producers, tampered Assets and unsafe ZIP recovery.
- [x] 2026-08-15 Add independent Web review/export selection, export history and download states. Component, Mock Chrome and real FastAPI/Worker/SQLite/FFmpeg Chrome flows pass.
- [x] 2026-08-15 Create `input/8.15-1.ts` and `input/8.15-2.ts` as two distinct real Projects/runs and complete both long-input E2E tasks. Each reached `pending_review` with 45 rough candidates, 15 non-degraded selected plans and 15 validated clean proxies; Provider evidence contains 115 successful OpenRouter ASR calls, 91 Codex calls including one successful repair, and zero Mock rows.
- [ ] Import a generated package into installed CapCut/Jianying Desktop if available; otherwise record that external UI acceptance as pending without overclaim.

### V2-M4 — Release planning and platform packages

- [x] 2026-08-15 Add ADR-015, strict append-only platform presets/current-version registry, checklist/preflight values and centralized item/approval/package transitions.
- [x] 2026-08-15 Add `c7e5d1a4b920` ReleaseItem/metric/package persistence and `d8f3a6b1c420` immutable publication evidence plus package manifest/ZIP hashes; fresh and round-trip migration tests pass. The real database was WAL-checkpointed, backed up, migrated to d8 and verified without changing protected row counts.
- [x] 2026-08-15 Add optimistic metadata/assignment/planned time, submit/approve/return/revoke approval, queue/status transitions, actual publication URL/ID/time, immutable package evidence and manual metric snapshots.
- [x] 2026-08-15 Add exact clean/final preview selection, cover time and historical-preset safe-zone preview, nine-item Hook/first-frame/subtitle/rights/privacy checklist and non-blocking duplicate-content advisory.
- [x] 2026-08-15 Add leased immutable platform ZIP generation with selected caption mode, MP4/SRT/cover/editable copy/checklist/preflight/manifest/checksums, actual-byte validation, no-replace publication and deterministic crash recovery.
- [x] 2026-08-15 Add authorized REST API, signed ZIP download, Web queue/calendar/package history/failure retry/stale sync and manually entered outcome/metrics.
- [x] 2026-08-15 Pass `make doctor`, full lint/test, Mock and real Chrome E2E, screenshot inspection and independent read-only review with P0=0/P1=0. MCP Browser exposed no controllable instance, so only the distinct actual-host-Chrome result is claimed.
- [x] 2026-08-15 Audit the exact staged set, exclude credentials/input/data/E2E artifacts, and create reviewed implementation checkpoint `06b7054`.

### V2-M5 — Hardening and acceptance

- [x] 2026-08-15 Exercise WAL-consistent backup/new-path restore, hot-sidecar rejection, real Alembic upgrade/recovery/rollback, expired sessions, concurrent revocation and permission changes during long exports. PAT remains deferred and is not claimed as tested.
- [x] 2026-08-15 Add administrator storage inventory, conservative safe cleanup, reversible archive, two-confirmation permanent Project purge, pre-purge recovery point, exact-inode quarantine/recovery and operator runbook.
- [x] 2026-08-15 Add explicit administrator Project governance: workspace-wide read-only inventory, disabled-owner recovery, atomic owner transfer and sanitized audit timeline without implicit Project membership or editorial/media access.
- [x] 2026-08-15 Linearize every administrator identity/governance read or mutation against concurrent disable/demotion. Identity mutations return their post-mutation user snapshot in the same `BEGIN IMMEDIATE`; long storage scans recheck current authority before returning.
- [x] 2026-08-15 Reject all new SourceMedia below `LIVECLIP_DATA_DIR` at API, CLI and shared service boundaries; keep long scans/deletes outside SQLite writer transactions and prove Worker heartbeat remains available.
- [x] 2026-08-15 Fence immutable package compensation across lease handoff: successor attempts adopt exact committed Asset ownership, lost runners never withdraw, and current withdrawal atomically quarantines the exact directory with Asset invalidation.
- [x] 2026-08-15 Make recursive cleanup process-termination recoverable through deterministic `.NAME.cleanup` endpoints bound to the persisted directory inode; competing endpoints, wrong inodes and source references inside either alias fail closed.
- [x] 2026-08-15 Rerun final M5 gates: `make doctor` READY; `make lint` passes 215 formatted files/132 typed source files/schema/TypeScript; `make test` passes 698 Python + 47 Web + Mock Chrome + real FastAPI/Worker/SQLite/FFmpeg Chrome E2E; and `make demo` produces delivered Demo `demo_20260815T153549_c87bdfeb` with a validated v001 ZIP. No paid Provider call was made.
- [x] 2026-08-15 Complete independent Product Spec verification after fixing administrator-revocation and cleanup-recovery findings; final implementation review reports P0=0/P1=0. Main Agent viewed the fresh governance/storage/full-flow Chrome screenshots and Demo contact sheet.
- [ ] Audit the exact staged set and publish the reviewed V2-M5 checkpoint without secrets, real inputs, database/media or generated browser artifacts.

### V2-M6 — Staged professional collaboration extensions

- [ ] Add revision/timecode-threaded comments with resolution state and mention-ready identities.
- [ ] Add reusable saved views plus optimistic bulk assignment/review/export.
- [ ] Add server-authorized search across Project/source/title/Hook/keyword/assignee/lifecycle/platform.
- [ ] Decide and implement scoped hashed PAT lifecycle only if CLI/API automation needs more than the retained v0.1 migration token bridge.
- [ ] Perform a real Jianying/CapCut Desktop import when that external application is available; do not claim native-draft compatibility.

## Work breakdown and file ownership

The main Agent exclusively owns migrations, shared schemas, dependency/lock changes, Product Spec/Solution/ADR, this ExecPlan and STATUS. If parallel writers are later used, authentication/admin, lifecycle and export work must receive disjoint modules and tests; no two writers modify `models.py`, Alembic head, `api/app.py`, Web `App.tsx` or shared TypeScript/Pydantic DTOs concurrently.

V2-M1 implementation order:

1. Write authorization matrix tests and credential/session model.
2. Add migration and repository/application services.
3. Integrate request principal, cookie authentication, CSRF and the bounded v0.1 Bearer-token migration bridge; keep PAT lifecycle staged.
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

V2-M4 implementation order:

1. Define ADR-015, strict platform preset/preflight/checklist values and centralized ReleaseItem/ReleasePackage transitions.
2. Add an additive migration for ReleaseItem, manual metric snapshots and immutable ReleasePackage versions; do not rebuild existing parent tables.
3. Implement optimistic release metadata/approval/status services, exact current-revision/render evidence, audit events and Project-publication reconciliation.
4. Add durable delivery-class package execution with requester/revision/item/preset/Asset fencing, actual-byte validation, selected cover extraction and atomic ZIP publication.
5. Expose authorized preset, queue/calendar, item, approval, result, metrics and package APIs; signed download remains Asset-ID backed.
6. Add the editor-facing release workspace, safe-zone/cover preview, checklists, queue/calendar and package history, then run migration/unit/integration/component/browser gates and an independent read-only review.

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
- Release: current/historical preset resolution, draft-to-approval workflow, exact render mode, duplicate advisory, immutable publication evidence, active-package invalidation, actual-byte ZIP validation and lease/crash recovery are verified independently.
- UI: login, administrator users, explicit Project governance, storage retention, private Project lists, lifecycle actions, selective export and all empty/loading/error/disabled states have observable component plus browser coverage.

## Idempotency, retry and recovery

User create/update/reset and ownership/role/visibility/lifecycle changes use explicit transaction boundaries, compare-and-swap/invariant checks and atomic audit/session effects. Idempotency-Key applies to task/package allocation endpoints where a retry could allocate another durable resource; administrator user routes do not claim an unimplemented idempotency-key contract. Password reset/session revocation commit atomically. A failed/expired login attempt never creates a partial session. Edit-package and ReleasePackage allocation use immutable versions; a crash leaves only a strictly named private attempt, recoverable by exact snapshot validation. ReleasePackage artifact-facing names and enqueue-time advisory preflight are frozen, while dynamic duplicate evidence is excluded from the material current fingerprint. Permission and selected-revision fences are rechecked immediately before and after publication. A current owner can compensate through an exact lease/Asset/inode quarantine fence; a lost owner leaves the endpoint untouched after committed Asset ownership transfers to the successor attempt. Item/review/revision/run changes atomically fail active release packages and cancel or fence their Tasks.

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
- 2026-08-15: The user supplied two real MPEG-TS long inputs for separate E2E tasks. `8.15-1.ts` is 2,229,033,280 bytes / 4,660.205 seconds and `8.15-2.ts` is 2,398,135,896 bytes / 5,042.717 seconds; both are portrait HEVC 1088×1920 plus AAC. The second reports `avg_frame_rate=0/0` but a valid `r_frame_rate=25/1`, which the existing ingest fallback accepts.
- 2026-08-15: The first EditPackage FFmpeg/API integration exposed two persistence-boundary defects: strict Pydantic tuples/enums must be restored using JSON-mode validation, and SQLAlchemy Core `Connection` model selects return rows rather than ORM entities. Both were reproduced from the failed SQLite attempt and corrected before any long cloud task was started.
- 2026-08-15: Package integration additionally exposed that pipeline proxies and manual proxies have intentionally different fingerprints, SQLite revision epoch zero is valid, empty metadata-only directories violate the pinned publication set, and ZIP member order is not an integrity property. The final verifier checks exact producer Task/Attempt lineage, explicit `None`, set equality plus hashes, and no unexplained files.
- 2026-08-15: V2-M3 local gates pass: Ruff/format, mypy over 121 source files, EditPlan schema, TypeScript, 583 Python tests, 29 Web tests, Mock Chrome E2E and real FastAPI/leased-Worker/SQLite/FFmpeg Chrome E2E. The real database was backed up as `liveclip-pre-b95f3e6a1c27-20260815T144143+0800.sqlite3` (SHA-256 `0b6701d00aaa3da45e46bbd93e2816505acb479a849eac19977fdaaf940c7024`) and migrated from `a84e2d7c9f10` to `b95f3e6a1c27`; quick check is `ok`, foreign keys are clean and all pre-existing row counts remain unchanged.
- 2026-08-15: The two real generation-1 preprocess attempts correctly failed instead of publishing invalid manifests when MPEG-TS silence timestamps overlapped by 1–2 ms. The parser now takes the ordered interval union; 16 preprocess tests and full-source scans pass. Deterministic retry policy correctly rejected an unchanged blind retry, so generation-2 runs were created in the same Projects while failed evidence remained auditable.
- 2026-08-15: Both long generation-2 runs completed all six stages with real OpenRouter `whisper-large-v3` and Codex CLI `gpt-5.6-terra`. Projects `67e827b4c0c8493b9804241e517cc5fe` and `4e3bf22ebf2f4b6a81f5ae5a0e552a46` each have 15 successful no-blur review proxies and computed state `pending_review`. Full evidence is in `docs/verification/long-input-e2e-2026-08-15.md`.
- 2026-08-15: V2-M4 review exposed that revision epoch is Project-wide, so revising clip A must invalidate active package work for clip B as well. The shared invalidator now fails queued/creating package resources and cancels queued or fences leased Tasks in the same transaction; an A/B-clip regression passes.
- 2026-08-15: Duplicate-content evidence is useful to editors but changes when another package completes. It is therefore a non-blocking live advisory, removed from the material current fingerprint and frozen at enqueue for artifact bytes. A crash-point regression proves re-claim after a new duplicate export and display-name changes reproduces the identical snapshot/preflight context.
- 2026-08-15: Final V2-M4 gates pass `make doctor`, Ruff/format over 207 files, mypy over 127 source files, EditPlan schema, TypeScript, 641 Python tests, 45 Web tests, Mock Chrome E2E and real FastAPI/leased-Worker/SQLite/FFmpeg/ReleasePackage Chrome E2E. A privileged final real-Chrome rerun passed in 19.5 seconds and its full-page screenshot was viewed; the in-app MCP Browser reported no controllable instance and is not claimed as successful.
- 2026-08-15: Before d8, the real database was WAL-checkpointed and copied to `liveclip-pre-d8f3a6b1c420-20260815T194643+0800.sqlite3` (SHA-256 `af49cc9219a1444ed6de0b2f83fb179cc6d012e4bf62056167c4723dbec24ace`). It now reports d8 head, `quick_check=ok`, no foreign-key violations and unchanged protected counts; all release tables remain empty.
- 2026-08-15: Independent V2-M4 review passed with P0=0/P1=0 after closing exact-preview, historical-preset, stale-package, crash-context and approval-revocation findings. It left two P2 hardening items for M5: reasonable publication/metric time bounds and a publication-time physical re-hash of pinned manifest/ZIP bytes.
- 2026-08-15: M5 storage review exposed destructive-path risks around WAL restore, path rebinding, cross-filesystem trees, interrupted purge and long recursive work under SQLite's writer lock. Backup now operates on private stable snapshots, restore rejects live sidecars and the configured live endpoint, purge/attempt cleanup uses persisted inode-bound quarantine with startup recovery, and recursive scans/deletes occur outside the writer transaction.
- 2026-08-15: Final package review found an old runner could lose its lease after publication, then delete the same directory after a successor adopted and completed it. Exact committed Assets now transfer producer-attempt ownership; stale runners never withdraw; current compensation couples an O(1) inode rename with Asset invalidation under one lease-fenced transaction. Deterministic old→new→old interleaving and current-withdrawal tests pass.
- 2026-08-15: Package compensation fault injection now proves a failed Asset update restores the exact original directory inode. A simulated recursive cleanup failure leaves the package under its recorded attempt inode, and the terminal-attempt janitor removes it on the next pass. Corrupt adopted Edit/Release directories are quarantined on deterministic validation failure and can be rebuilt; transient validation preserves bytes for bounded retry.
- 2026-08-15: The final governance audit reproduced a stale-actor race: an administrator snapshot captured before demotion could still create users and read the private storage inventory. All identity mutations and reads now recheck the live account row under one short SQLite transaction; governance already used the same fence, while filesystem-backed storage reports check authority on both sides of the long scan. Direct stale-actor and revoke-during-scan tests prove denial with no user/audit side effect.
- 2026-08-15: Process termination can bypass Python exception rollback after a cleanup rename. Recursive tree deletion now uses one deterministic hidden endpoint and persisted inode evidence, so the next janitor/purge pass resumes only the exact tree. Dual endpoint, wrong-inode and hidden-alias SourceMedia tests all fail closed.
- 2026-08-15: Final M5 gates pass with 698 Python tests, 47 Web tests and both Chrome E2Es. Demo `demo_20260815T153549_c87bdfeb` reached `delivered`; full decode and ZIP integrity passed. The main Agent viewed its three-frame contact sheet and recorded `viewed_passed`: clear 1080×1920 single-layer frames have no blur background, black/blank frame, aspect error or severe crop, and title/captions remain inside the safe area.

## Decision Log

- 2026-08-13: Call the next product line v0.2 while preserving `0.1.0` as the actual package baseline; alternative was silently extending v0.1; rationale: identity/lifecycle/export contracts are material product changes and need migration boundaries.
- 2026-08-13: Separate system role, Project role and visibility; alternative was one role enum; rationale: administrator governance, editorial duties and discoverability answer different authorization questions.
- 2026-08-13: Use local opaque sessions and retain the v0.1 Bearer token only as a migration bridge; optional scoped PAT lifecycle is deferred until an automation consumer requires it. Alternative was continuing shared environment tokens or adding external OAuth; rationale: administrators need revocation and user lifecycle while the local product must remain self-contained.
- 2026-08-13: Separate business lifecycle from Pipeline status; alternative was expanding the derived Project status string; rationale: processing facts cannot represent assignment, approval, publish and archive intent.
- 2026-08-13: Add EditPackage and ReleaseItem rather than overloading Delivery; rationale: clean editor handoff, approved final delivery and platform publication have different eligibility and evidence.
- 2026-08-13: Treat successful Delivery as `ready_to_publish` only for legacy backfill and never as `published`; rationale: file creation is not evidence that a human published to a platform.
- 2026-08-13: Reject removal of the current assignee until reassignment; alternative was leaving a dangling assignment or silently clearing it; rationale: explicit workflow ownership is safer and auditable.
- 2026-08-15: Treat the two `8.15-*.ts` files as two independent Projects and PipelineRuns, not one fixture split or one merged Project; rationale: the user explicitly called them two tasks and duplicate/media reuse must never collapse explicit Project intent.
- 2026-08-15: Adopt ADR-015 and keep ReleaseItem/ReleasePackage separate from EditPackage and formal Delivery; only primary-source-backed limits are hard blockers, while account-dependent platform policy is an explicit human confirmation. `scheduled_external` is a planning fact and never claims LiveClip scheduled or uploaded to a social platform.
- 2026-08-15: Permit a ReleaseItem draft from any current non-rejected clip, but keep content approval and exact trusted media as preflight blockers. This lets release copy/assignment work begin in parallel without claiming readiness.
- 2026-08-15: Treat prior-content similarity as warning-only and preserve intentional cross-platform reuse; only immutable successful export/delivery snapshots may provide duplicate evidence.
- 2026-08-15: Bind `published` to one exact current successful package and persist immutable publication hashes; mutable ReleaseItem fields and current Asset rows are not sufficient publication evidence.
- 2026-08-15: Keep generated Project storage categorically separate from SourceMedia and reject a source below the data root at every invocation boundary; alternative was relying only on purge-time checks, which leaves a prevalidation/write-lock race.
- 2026-08-15: Couple package directory withdrawal to Asset producer ownership in one short transaction; alternative was a runner-side lease observation followed by filesystem deletion, which retains a TOCTOU window across attempt handoff.
- 2026-08-15: Keep ordinary Project routes membership-scoped even for system administrators. Workspace-wide Project recovery lives only under explicit `/admin/projects` governance DTOs/actions; it never silently grants membership, media access or editorial capability.
- 2026-08-15: Treat administrator authorization as live database state, not a trusted request-start snapshot. Short DB-only operations linearize authority with `BEGIN IMMEDIATE`; long filesystem reads recheck after scanning before returning private inventory.

## Risks and Mitigations

- Password implementation error: use a reviewed library/primitive, strict parameters, constant-time verification, neutral errors and dedicated tests; never implement a novel hash.
- Cookie/CSRF confusion with header auth: explicit credential kind in the principal; unsafe cookie requests require CSRF while the bounded legacy Authorization-header bridge does not rely on ambient cookies. A future PAT design must preserve this separation.
- Administrator overreach: only explicit governance routes can enumerate all Projects or perform a confirmed/audited owner transfer; they never silently add the administrator as a member or grant media/editorial actions.
- Legacy lockout: one-time bootstrap/migration path and v0.1 token bridge remain until admin login is proven.
- Permission TOCTOU during export: transactionally capture and recheck membership, selection, revision and Asset identity around publication.
- Undocumented Jianying format churn: ship standards-based MP4/SRT and verify real import; native draft remains excluded.
- Platform policy drift: presets are versioned and linked to check date; UI labels account-specific checks as required rather than universally “passed”.
- Locally tampered publication evidence: publication re-hashes pinned manifest/ZIP bytes immediately before accepting evidence, and downloads independently re-hash and refuse altered files.
- Implausible publication metrics: bounded timestamps, `captured_at >= published_at` and SQLite-safe metric limits are enforced without changing the V2-M4 workflow.
- Source-reference scale: purge/janitor write transactions no longer perform recursive work, but their final legacy-source defense still scans all stored source rows and resolves paths. This is a documented P2 scaling cost for very large workspaces; the application rejects new data-root sources, and a future canonical-path index can make the final fence constant-time without weakening legacy safety.
- Immediate stage/render cleanup currently observes the attempt inode at deletion time rather than carrying the persisted `TaskAttempt.temp_identity` through every handler cleanup call. Janitor and package-withdrawal paths are identity-fenced; propagating the persisted identity to all immediate cleanup calls is a P2 local same-account filesystem hardening task.

## Recovery Notes

V2-M1/V2-M2/V2-M3, both requested long-input E2Es and V2-M4 are checkpointed through `06b7054`; release-evidence hardening is checkpointed at `be6d110`. Project `7.28` remains unchanged; Projects `8.15-1` and `8.15-2` remain ready for human review. The real database is at d8 after WAL-safe backup `liveclip-pre-d8f3a6b1c420-20260815T194643+0800.sqlite3` (SHA-256 `af49cc9219a1444ed6de0b2f83fb179cc6d012e4bf62056167c4723dbec24ace`), and current `alembic current/check` report head/no pending operations. V2-M5 implementation, final independent review and full gates pass; only the exact staged-set audit and Git checkpoint remain. Do not reprocess the three real Projects or invoke paid Providers.

## Outcomes and Retrospective

V2-M0 through V2-M4 are checkpointed and V2-M5 implementation/gates plus independent review are complete pending the Git checkpoint. V2-M4 provides a separate, auditable release-planning and platform-package path without social credentials or false upload claims. M5 adds bounded publication evidence, explicit administrator Project recovery, live-authority fencing, storage/retention visibility, process-crash-resumable cleanup, WAL-correct backup/new-path recovery and lease-safe package compensation. Both supplied long MPEG-TS inputs remain at `pending_review` with completed real ASR, Codex editing and no-blur proxy rendering. V2-M6 retains external Jianying/CapCut import, threaded timecode comments, saved views, bulk operations, full search and optional PATs as explicit staged work rather than hidden completion claims.
