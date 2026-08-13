# LiveClip status snapshot

Updated: 2026-08-13 22:15 CST

Current product baseline: `0.1.0`

Current milestone: v0.2 V2-M1 accounts/administration in progress

Branch: `main` tracking `origin/main`

Latest v0.2 checkpoint: `06c10df` (`docs: checkpoint v0.2 account management`); an ownership/capability checkpoint is ready to commit.

Latest committed v0.1 checkpoint: `0f34e2b` (`docs: record M14 project workspace checkpoint`)

## v0.1 frozen baseline

v0.1 is the currently working release line. It includes the real recoverable media Pipeline, OpenRouter Whisper ASR, Codex editing, clean direct center-crop review proxies, `高光时刻` review UI, immutable revisions/renders/Delivery, offline review package and server-side Project membership isolation. Package metadata and `liveclip.__version__` are already `0.1.0`.

Open `http://127.0.0.1:5173`. Current real Project `7.28` is `f91cb996f7534a6682aa5e5f01374b7b`, generation-3 run `634c68f9d0b24c99b16ddac8d14ddfd7`, `pending_review`, with 15 non-degraded clean no-blur proxies. It must not be reprocessed for v0.2 account/lifecycle/export work.

The latest v0.1 full gate passed 559 Python tests, 23 Web tests, Mock Chrome E2E and real FastAPI/leased-Worker/SQLite/FFmpeg Chrome E2E. `make lint` passed Ruff/format/mypy/schema/TypeScript. Exact historical media/provider/export evidence remains in `docs/exec-plans/liveclip-v1.md` and Git; it is not duplicated here.

## v0.2 requested outcome

- Real administrator login and local user management: create, edit, disable/reactivate, password reset and system-role authorization.
- Clear system administrator versus Project owner/editor/reviewer/viewer responsibilities.
- New Projects private by default; only creator/owner initially sees them. Optional workspace-visible mode remains authenticated, never public.
- Professional lifecycle separate from technical processing: draft, processing, attention, editorial review, changes requested, approval, ready to publish, published and archived.
- Assignment, due date, priority, comments, activity/audit history and archive/restore.
- Select one or more current clips for individual MP4/SRT download or immutable editor handoff ZIP.
- Jianying/CapCut Desktop/Web compatibility through clean H.264/AAC MP4 plus basename-matched plain UTF-8 relative-time SRT; no unverified native Jianying draft claim and no direct-mobile SRT claim.
- Versioned platform release presets, preflight, cover/copy/hashtags/rights checklist and manually recorded publication outcome; no automatic social credential storage/posting in the initial release.

Authoritative new documents:

- `docs/PRODUCT_SPEC_V0.2.md`
- `docs/exec-plans/liveclip-v0.2.md`
- `docs/adr/014-v02-identity-lifecycle-and-editor-handoff.md`
- `docs/research/editor-handoff-platforms.md`

## Phased plan

- V2-M0: freeze v0.1, research and v0.2 contracts.
- V2-M1: accounts, administrator console, sessions/PATs, central authorization and audit.
- V2-M2: Project visibility/lifecycle/assignment/comments/activity/archive.
- V2-M3: selective individual download and immutable Jianying-friendly edit package.
- V2-M4: platform-ready presets and release planning/outcome records.
- V2-M5: migration/security/recovery/storage hardening and full acceptance.

## Evidence and decisions recorded this session

- Repository was clean on `main` at `0f34e2b`; package is already `0.1.0`.
- Current CapCut primary help confirms SRT/TXT import on Desktop and SRT on Web, with editable timed text layers and UTF-8 guidance; mobile has no direct external subtitle import.
- YouTube primary help supports MP4/H.264/AAC, Fast Start, progressive/yuv420p-style upload masters, plain UTF-8 SRT and vertical/square Shorts up to three minutes under current rules.
- TikTok's official developer transfer guide recommends MP4/H.264 and documents 23–60 fps, minimum 360-pixel dimensions, up to 4 GB and account-dependent duration entitlement.
- Apple documents FCPXML as a professional interchange target, but it is later scope and not a Jianying substitute.
- ADR-014 chooses local opaque Web sessions, optional hashed PATs, separate authority dimensions, business lifecycle and immutable editor packages.
- V2-M1 now has Alembic head `f42b7c1d9e63`, Argon2id credentials, server-side hashed/revocable sessions, CSRF, login throttling and append-only audit events.
- Administrator APIs and Web UI can list/create/edit/disable/reactivate/reset-password and grant/revoke the system administrator role while retaining at least one active administrator.
- New Projects persist `visibility=private`; Project roles now include viewer and central owner/editor/reviewer/viewer action policy guards unsafe routes.
- `570` Python tests and `27` Web tests passed; `make lint`, Mock Chrome E2E and real FastAPI/leased-Worker/SQLite/FFmpeg Chrome E2E passed after the ownership/capability work.
- V2-M1 checkpoint `a5e52a3` was pushed to `origin/main`.
- Isolated Chrome at `http://127.0.0.1:5273` equivalent port exercised signed-out login → administrator dashboard → members page. Viewed screenshots were `/tmp/liveclip-v02-login.png` and `/tmp/liveclip-v02-admin.png`; `/tmp` evidence is not durable.
- Browser plugin discovery returned no available browser (`[]`), so MCP Browser success is not claimed; host Chrome was the verified fallback.
- Project DTOs now expose server-derived `allowed_actions`; the Web uses them to gate member, Pipeline, edit, review, render and Delivery actions instead of copying the role matrix.
- Owners can explicitly confirm an atomic transfer to an active Project member; the former owner becomes editor, the Project owner pointer changes and audit history records the change.
- Member add/change/remove are audited. A two-session integration test proves a non-member receives 404 even with a private Project, committed media or Delivery ZIP ID.
- Real browser E2E now tests the v0.2 password-login path rather than the superseded v0.1 shared-token settings flow.

## Security and local state

- Never stage `.env`, `.env.local`, `OPENROUTER_SETUP.md`, `input/`, SQLite, media, caches, E2E output, deliveries or migration backups.
- No credential value was read or printed during v0.2 planning.
- No source video, Project, database, render, Delivery or Provider usage was changed.
- Existing local services may continue serving v0.1 at `127.0.0.1:8765` and `127.0.0.1:5173`.
- V2-M0 checkpoint `dfc1639` contains only tracked planning/recovery documents; no ignored local data or credential entered Git.

## Still pending in V2-M1

- Optional scoped PATs and explicit audited administrator Project override.
- Full two-account browser denial remains later hardening; API integration already covers private Project/media/download denial and component tests cover viewer read-only capability UX.
- Real database login opt-in: no bootstrap password has been written to the real v0.1 data store, so existing local tokenless access is preserved.
- Jianying/CapCut import of a generated v0.2 package has not yet occurred because V2-M3 is pending.
- China-platform/Instagram numeric presets must be rechecked from primary documentation immediately before V2-M4; no unsupported numbers are frozen now.
- Representative 2–4 hour Apple M3 resource measurements remain outside this identity/planning phase.

## Next concrete task

Review/commit/push the ownership/capability checkpoint. Then either finish optional PAT/admin override or start V2-M2 with the lifecycle schema and central transition table.

## Resume instructions

Read `AGENTS.md`, `docs/PRODUCT_SPEC.md`, `docs/PRODUCT_SPEC_V0.2.md`, `docs/SOLUTION.md`, `.agent/PLANS.md`, both Living ExecPlans and this file. Run `git status --short --branch` and `git log -5 --oneline`. Continue with “Next concrete task”; preserve ignored real media/data and do not repeat paid `7.28` ASR/LLM work.
