# LiveClip status snapshot

Updated: 2026-08-04 16:55 CST
Current milestone: M6 — independent acceptance, real-backend browser E2E and final documentation
Branch: `master`
Recent relevant commit: `7c145ec` (`milestone: complete LiveClip M5 hardening`)

## Completed

- M0–M4 are locally committed and independently reviewed. Their architecture, persistent pipeline, CLI/API/Web review flow, OpenAI adapters and Mock/cloud boundaries remain recorded in the Living ExecPlan.
- M5 adds component-anchored no-follow file operations, immutable/no-replace publication, bounded/cancellable media subprocesses, lease monitoring, expired-attempt recovery, orphan cleanup and safe diagnostic persistence.
- Stage recovery now requires exact committed Assets from the expected producer Task, canonical project/run/generation paths, regular no-follow endpoints, size and SHA-256. Legacy source rows retain unknown stream indices until a real matching ingest verifies them.
- Ingest and rendering persist/select explicit video/audio streams, normalize display rotation, preserve VFR timing evidence and bind a long source once per stage rather than rehashing it for every candidate.
- Render validation, full decode, frame extraction, publication and Asset commit are bound to the same pinned bytes and expected SHA. Caption expansion has a shared domain/renderer maximum of 64 overlays with no silent truncation.
- Delivery streams videos/subtitles/manifest from pinned FDs into a pinned ZIP, verifies every member, publishes an exact regular-file tree with native no-replace rename, rebinds/rehashes every member after publication and commits manifest/ZIP Assets with expected SHA.
- Two M5 reviews are complete. The first findings were repaired; a fresh re-review found one remaining ZIP/member byte-binding P1, which was repaired. The final independent verdict is `PASS` with no P0/P1/P2.
- Scoped local M5 commit `7c145ec` contains the reviewed implementation, migration, tests, ADR and recovery documentation.

## In progress

- M6 starts with one browser-to-real-FastAPI/Worker composition flow, followed by documentation audit and Product Spec-wide verification.

## Not completed

- M6 browser-to-real-FastAPI/Worker composition E2E, documentation audit, final clean acceptance and Product Spec-wide independent Verification Agent.
- Real OpenAI cloud smoke because no `OPENAI_API_KEY` is configured.

## Verified

- `make lint` at 2026-08-04: PASS; Ruff check and format over 153 files, mypy over 97 source files, frontend TypeScript typecheck.
- `make test` at 2026-08-04: PASS; 428 Python tests in 135.02 seconds with one third-party Starlette deprecation warning, then 11 Vitest tests.
- Delivery-focused root gate: 44 tests plus Ruff/format/mypy/diff check PASS. Independent final re-review: 58 focused tests PASS; both prior endpoint-replacement reproductions fail closed with no `v001`, no attempt residue and no external-data inclusion.
- Read-only long input: `input/7.28.mp4`, 2,190,937,089 bytes, SHA-256 `595cc75a65fe8d9faa3b41ba9f5b58b307d1b0a41236f7fc6016c0c1ae8acd03`, 2,780.437 seconds, 1920×1200 H.264/stereo AAC. Source stat/hash was unchanged after the run.
- Long Mock run: project `bf1bd9d6ff66424780fc1b11781069f1`, run `c9be88878366432385cdf58d190a1d34`; all six stages and attempts succeeded in 28.83 seconds, five 600-second/5-second-overlap chunks, 14 committed Assets, about 18 MB project data. Output lives only under `/private/tmp/liveclip-m5-postfix.bc3Ao9/projects`.
- Real generated media tests cover VFR (`30/1` nominal, `750/59` average), 90°/270° display rotation, explicit video/audio selection, non-first/default audio, proxy H.264/AAC, full decode and contact sheets.
- Fresh `make demo`: PASS, project `demo_20260804T085309_96fb7a31`, state `delivered`, three candidates and immutable v001.
- Demo final: `/Users/junhuaxu/Workspace/AGI/liveclip-ai/data/demo/projects/demo_20260804T085309_96fb7a31/renders/final/clip_01_bdc52e84/r002/final.mp4`; H.264/AAC, 1080×1920, 12.000 seconds, 3,385,827 bytes, full decode PASS, SHA-256 `7286b956031c1132e7d3caaa366a074cee5ef5caa8f931eb8bd325e566b867c4`.
- Demo contact sheet: `/Users/junhuaxu/Workspace/AGI/liveclip-ai/data/demo/projects/demo_20260804T085309_96fb7a31/renders/final/clip_01_bdc52e84/r002/final-quality/contact-sheet.png`; actually viewed. Dynamic portrait frames, safe Chinese title/captions, no black/blank/orientation/aspect/severe-crop issue. Report records `viewed_passed` at `2026-08-04T08:54:20.932433+00:00`.
- Demo delivery ZIP: `/Users/junhuaxu/Workspace/AGI/liveclip-ai/data/demo/projects/demo_20260804T085309_96fb7a31/deliveries/v001/delivery.zip`; `unzip -t` PASS. Manifest revision 2 and delivered video hash match disk; ZIP SHA-256 `efd5e3d59474e6b24e6e3f1aa07dd98d697dff9b1bd6f58ca13ed6595824ff2a`.
- Most recent `make doctor`: READY on macOS arm64, Python 3.12.13 arm64, Node 22.11 LTS, SQLite 3.53.1 and FFmpeg 8.1.2; raster text fallback and actual libx264 encode pass. Expected warnings remain for absent OpenAI key/allowed roots and sandbox VideoToolbox OSStatus -12903.

## Not yet verified

- Real OpenAI account/model entitlement, Chinese cloud output/usage/rate-limit behavior: credentials are absent, so cloud smoke is truthfully `not_run`, never Mock success.
- Representative 2–4 hour peak RSS/runtime/disk and Apple M3 throughput. The available repository sample is 46:20 on Apple M2; runtime/disk were measured, but sandbox `/usr/bin/time -l` could not expose peak RSS because its post-child `sysctl kern.clockrate` call was denied.
- Linux `renameat2(RENAME_NOREPLACE)` execution on this macOS host; unsupported platforms fail closed.
- Browser-to-real-backend composition (M6). M3 Playwright uses a controlled API mock while Python integration covers the real backend chain separately.

## Current blockers

- No product or implementation blocker.
- Missing cloud credentials block only paid cloud verification.

## Worktree state

- Branch `master`; HEAD `7c145ec` before this documentation-only checkpoint.
- M5 implementation is committed and the worktree was clean immediately after commit. Generated data, user `input/` media, SQLite databases and deliveries remain ignored.
- No remote exists and nothing has been pushed.

## Recent actual commands

- Focused secure Delivery gate → 44 passed in 22.73 seconds; Ruff/format/mypy/diff check PASS.
- Independent Delivery re-review → PASS; 58 focused tests, Ruff, mypy and both isolated race reproductions PASS/fail closed.
- `make lint` → exit 0.
- `make test` → exit 0; 428 Python + 11 Web tests.
- `make demo` → exit 0; project `demo_20260804T085309_96fb7a31` delivered.
- ffprobe + complete FFmpeg null decode + `unzip -t` + manifest/hash inspection → PASS.
- Actual contact-sheet view plus `record_visual_inspection` → `viewed_passed`.

## Next concrete task

Read the browser-control skill, inspect the existing Playwright mock E2E and dev-process scripts, then implement one isolated browser-to-real-FastAPI/Worker E2E without duplicating backend state logic in the frontend.

## Resume instructions

Read `AGENTS.md`, `docs/PRODUCT_SPEC.md`, `docs/SOLUTION.md`, `.agent/PLANS.md`, `docs/exec-plans/liveclip-v1.md` and this file. Run `git status --short --branch` and `git log -5 --oneline`, verify `7c145ec`, then execute the M6 browser-composition task above. Do not rerun the long source test unless media/pipeline code changed. Do not call OpenAI unless explicitly running `make smoke-cloud`; never substitute Mock for a claimed cloud success.
