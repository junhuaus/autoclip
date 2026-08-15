# LiveClip status snapshot

Updated: 2026-08-15 23:40 CST

Current package baseline: `0.1.0`

Current milestone: v0.2 V2-M5 reviewed checkpoint, then staged V2-M6 collaboration work

Branch: `main` tracking `origin/main`; reviewed V2-M5 implementation commit is
`4b51f29`. The last observed origin was `f4d378c` before pushing local checkpoints.

## Current user-visible result

V2-M0 through V2-M4 are checkpointed. The authenticated editor workspace now
supports local administrator login and user CRUD/roles, default-private
Project membership, ownership transfer, a professional editorial lifecycle,
horizontal high-point review, selective clean MP4/SRT editor handoff, immutable
formal Delivery, and per-platform release planning/package evidence without
storing social credentials or claiming uploads.

V2-M5 adds explicit “项目治理” and “存储管理” administrator pages plus an
operational CLI. Ordinary Project/API/media routes remain membership-scoped,
even for administrators. The separate governance context can list all Projects,
show a disabled owner, transfer ownership to an active user and read sanitized
audit evidence; it never adds the administrator as a member or grants editorial
or media access. Inventory
separates Project data, SQLite/WAL, backups, tracked/stale/invalid/untracked
artifacts, unknown directories, unsafe entries and pending purge quarantine.
Routine cleanup only claims terminal attempt worktrees. Archive remains
reversible. Permanent purge requires an archived idle Project, a fresh scope
fingerprint, exact Project-name plus `PURGE PROJECT_ID` confirmations, and a
validated no-clobber recovery point; external SourceMedia is never deleted.
`liveclip db-backup` captures committed WAL state and `db-restore` validates a
closed backup into a new non-live path.

The three existing real Projects remain intact and were not reprocessed:

- `8.15-1`: Project `67e827b4c0c8493b9804241e517cc5fe`, current run
  `f0187e64fdbe44cdad62e4ae7afd9bd7`, 15 validated clean proxies.
- `8.15-2`: Project `4e3bf22ebf2f4b6a81f5ae5a0e552a46`, current run
  `a4228d3ca597476685c11b52a1202309`, 15 validated clean proxies.
- `7.28`: Project `f91cb996f7534a6682aa5e5f01374b7b`; unchanged.

## Completed v0.2 work

- V2-M0: product/research contract, ADR-014 and phased Living ExecPlan.
- V2-M1: Argon2id accounts, opaque sessions, CSRF, administrator user
  management, private Projects, role/capability policy and ownership transfer.
- V2-M2: business lifecycle separate from Pipeline state, assignment,
  priority, due date, archive/restore, activity and dashboard filters.
- V2-M3: signed exact MP4/SRT downloads and immutable selective editor package
  with clean media, captions, metadata, thumbnails, checksums, guide and ZIP.
- V2-M4: versioned platform presets; ReleaseItem approval/status/audit/metrics/
  publication evidence; leased immutable platform ZIP; queue/calendar Web UI.
- V2-M5 implementation: bounded publication/metric evidence; pinned-byte
  publication re-hash; safe storage inventory/cleanup/purge; WAL-consistent
  backup/new-path restore; source/data-root separation; short-transaction
  inode quarantine; interrupted purge recovery; package lease-handoff safety;
  explicit administrator Project recovery; and live-authority revocation fences.

## M5 correctness decisions

- New API, CLI and shared PipelineService imports reject SourceMedia anywhere
  below `LIVECLIP_DATA_DIR`; purge still checks all legacy Project/SourceMedia
  references and never opens the external source for deletion.
- Recursive verification and deletion occur outside SQLite writer
  transactions. Short transactions contain only authority/state/source/inode
  fences and an exact no-replace quarantine rename, preserving Worker
  heartbeat availability.
- A retry may adopt exact matching committed package Assets only after moving
  `producer_attempt_id` to the current attempt. A lost runner never withdraws.
  Current compensation atomically couples active lease/Asset ownership with an
  exact directory-inode quarantine and Asset invalidation; recursive cleanup
  follows commit and is recoverable by the attempt janitor.
- Deterministically corrupt adopted Edit/Release directories are withdrawn and
  can be rebuilt. A transient local validation outage preserves the directory
  for bounded retry.
- Backup is created and inspected from a system-owned private stable snapshot;
  restore rejects nonempty WAL/hot-journal sidecars and the configured live
  database endpoint, and never overwrites a destination.
- Administrator identity mutations and their post-mutation user lists share one
  short `BEGIN IMMEDIATE`; a disable/demotion is ordered against every later
  admin read or write. Long storage scans recheck the current account after
  filesystem traversal and refuse to return private inventory if authority was
  revoked mid-scan.
- Recursive deletion first moves the exact recorded inode to deterministic
  `.NAME.cleanup`. Process termination may leave that private endpoint, but the
  next pass resumes only with matching persisted identity. Original+hidden,
  wrong-inode and SourceMedia-in-hidden-alias cases all fail closed.

## Real database evidence

- `data/projects/liveclip.sqlite3` remains at Alembic `d8f3a6b1c420 (head)`.
- WAL-safe pre-d8 recovery point remains
  `data/projects/migration-backups/liveclip-pre-d8f3a6b1c420-20260815T194643+0800.sqlite3`,
  SHA-256 `af49cc9219a1444ed6de0b2f83fb179cc6d012e4bf62056167c4723dbec24ace`.
- Last controlled verification reported `quick_check=ok`, no foreign-key
  violations and unchanged protected counts: 3 Projects, 3 SourceMedia, 5
  PipelineRuns, 131 candidates, 55 EditPlan revisions, 60 renders, 365 Assets,
  353 API usage rows, 1 workspace user and 3 memberships. Release tables were
  empty. M5 tests and Demo used isolated roots and did not mutate this database.

## Latest actual validation

- `make lint`: passed Ruff/format over 215 files, mypy over 132 source files,
  EditPlan schema verification and TypeScript.
- `make test`: passed 698 Python tests, 47 Web component tests across 10 files,
  Mock Google Chrome E2E 1/1, and isolated real Google Chrome + FastAPI + leased
  Worker + SQLite + FFmpeg E2E 1/1. The real E2E opened “项目治理” and “存储管理”.
- `make doctor`: READY. Required tools and OpenRouter/Codex readiness passed.
  Expected warnings: FFmpeg lacks drawtext/subtitles so the tested Pillow
  overlay fallback is used; VideoToolbox probe failed and actual libx264
  fallback encoding succeeded.
- `make demo`: Project `demo_20260815T153549_c87bdfeb` reached `delivered` with
  3 candidates, valid 1080×1920 H.264/AAC final media, full decode, contact
  sheet, manifest and an integrity-tested v001 Delivery ZIP.
- Main Agent viewed the Demo contact sheet and recorded visual inspection: all
  three frames are clear with no blur background, black/blank frame, aspect
  error or severe crop; title and Chinese captions are inside the safe area.
- Main Agent viewed the fresh real-Chrome Project-governance, storage and full
  delivery screenshots: hierarchy, contrast, tables, audit timeline, retention
  explanation and controls are readable without clipping.
- Independent final v0.2 implementation review: PASS, P0=0/P1=0 after the
  stale-administrator and cleanup-recovery fixes. It independently reproduced
  the old stale-actor exploit, then confirmed it returns `DENIED`; the full
  repository gates above contain the final code and added fault tests.

Demo evidence:

- Video: `data/demo/projects/demo_20260815T153549_c87bdfeb/renders/final/clip_01_bdc52e84/r002/final.mp4`
- Contact sheet: `data/demo/projects/demo_20260815T153549_c87bdfeb/renders/final/clip_01_bdc52e84/r002/final-quality/contact-sheet.png`
- Quality report: `data/demo/projects/demo_20260815T153549_c87bdfeb/renders/final/clip_01_bdc52e84/r002/final-quality/quality-report.json`
- Delivery ZIP: `data/demo/projects/demo_20260815T153549_c87bdfeb/deliveries/v001/delivery.zip`

## Unverified and known limits

- The current session exposes the in-app Browser skill but not the Chrome
  extension skill; MCP Chrome success is not claimed and no extension was
  installed. The separate actual-host Google Chrome Playwright E2E passed and
  its fresh screenshot was inspected.
- External Jianying/CapCut Desktop import remains unverified. LiveClip truthfully
  provides standards-based clean H.264/AAC MP4 + matching UTF-8 SRT and does
  not claim an undocumented native draft format.
- Final legacy source defenses inside short cleanup/purge transactions still
  scan all source rows and resolve paths. Recursive work is outside the lock,
  but a future canonical-path index is desirable for very large workspaces.
- Threaded timecode comments, reusable saved views and cross-Project bulk
  assignment/review/export plus full Project/clip/release search remain staged
  V2-M6 enhancements, not claimed completed capability.
- Scoped hashed PAT lifecycle is not implemented or tested. CLI/API migration
  compatibility still uses the bounded v0.1 Bearer-token bridge; documentation
  does not claim PAT expiry was exercised.
- Immediate stage/render handler cleanup does not yet carry persisted
  `TaskAttempt.temp_identity` through every synchronous cleanup call. Janitor
  and package-withdrawal paths are inode-fenced; full propagation is a P2 local
  same-account filesystem hardening item.

## Security and worktree

- Never stage `.env`, `.env.local`, `OPENROUTER_SETUP.md`, `input/`, `data/`,
  SQLite/WAL, media, caches, deliveries, E2E results or migration backups.
- No credential was printed, persisted or staged. M5 validation used Mock/
  isolated fixtures and made no paid ASR/LLM call.
- Reviewed V2-M5 source/tests/docs are committed at `4b51f29`; generated/private
  paths remain ignored and unstaged. `git diff --check` passes. Push only the
  reviewed local commits after recording this recovery snapshot.

## Current work and next concrete task

The independent verifier, all final gates and exact staged-set audit are
complete; V2-M5 implementation is committed at `4b51f29`. Commit this recovery
snapshot, push the reviewed local commits, then begin V2-M6 with revision/
timecode comments before saved views, bulk operations, search or optional PAT
work.

## Resume instructions

Read `AGENTS.md`, both Product Specs, `docs/SOLUTION.md`, `.agent/PLANS.md`,
`docs/exec-plans/liveclip-v0.2.md` and this file. Run `git status --short
--branch`, `git diff --check`, `git log -5 --oneline`, `.venv/bin/alembic
current` and `.venv/bin/alembic check`. Preserve the three real Projects, Demo
evidence and pre-d8 backup. Do not reprocess real inputs or invoke paid
Providers. Verify commit `4b51f29` and the following STATUS checkpoint are
present/pushed, then begin the first unfinished V2-M6 task.
