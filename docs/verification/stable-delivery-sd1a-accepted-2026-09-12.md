# SD-1A engineering acceptance — 2026-09-12 PDT

Accepted and integrated. Formal `20260912T195929Z-8f0cbbe6` reached DONE with all gates
passing; trusted revalidation8885 and renewed original CAS ea10 preceded publication477b.
Twenty-seven exact code/config files and21 reviewed supporting documents were published,
with per-file before copies and immutable source evidence preserved. No commit or push.

This proves synthetic engineering acceptance for SD-1A. SD-1B through SD-7 and real
semantic/video/hardware acceptance remain open; historical deliveries were not regenerated.

## Accepted identity and role evidence

- HEAD: `6009b23859564b2bfdc193eee366afd990b9ef5d` on `liveclip-v2/loop-engineering`.
- Source: `eb507a42f08554ed1b900f1d321e855937dea6628ebdc3ddc1bb50ed96546aec`.
- Sealed toolchain: `759294999c09e75a2c9a0da924f29b89cd91e282962e4b9b139dfb3af8d019c2`.
- Immutable complete candidate and records: `.loop/development/sd1a-mini-artifacts-20260912/`.
- Exact assurance: `/Users/junhuaxu/Library/Caches/LiveClip/loop-toolchains/01f16d3fdc04d357/executions/20260912T195929Z-8f0cbbe6/assurance-1-1`.
- Publication receipt: `.loop/development/sd1a-mini-artifacts-20260912/original-publication-20260913T011427Z/receipt.json`.
- Original dirty baseline: `.loop/development/sd1a-20260912/baseline`; full changed-path/hash manifest is in the publication receipt.

| Role | Exact recorded session | Result |
| --- | --- | --- |
| planner | `01a09734-3666-7e10-b62d-9038eabe658d` | READY |
| coder | `01a09737-100d-7460-9ce6-0f1a42afab20` | IMPLEMENTED, no edits |
| reviewer | `01a09738-3c3d-7ba2-8c32-b7557c3d1942` | PASS, no findings/blockers |
| tester | `01a097d0-1dd6-77a3-a2b4-0c8a92e0fd78` | READY |
| gateway | `01a09851-a048-7341-bae2-691b54440a97` | PASS, no findings/blockers |

## Actual required Runner evidence

| Command | QA ID | Result | Complete log SHA-256 |
| --- | --- | --- | --- |
| lint | `20260912T234620Z-be37` | PASS,27.361 active seconds | `1054795aafa431a22bd6f6394366163a2fcc1b021991c3c7ade1819087c41a46` |
| test | `20260912T235027Z-eec6` | PASS,357.671 active seconds | `58fb9f9914b90d0a11b6e26643164a30ff15d9d8b3b14a1e861bc91b252a809f` |

1212 Python tests with13 deprecation warnings,58 Web tests,one mock browser flow and
one actual local API/leased Worker/SQLite/FFmpeg browser flow pass. Source,HEAD and
sealed toolchain identities match before and after both commands. Full logs are232
and15390bytes, below the unchanged1MB limit. Historical diagnostics do not substitute.

Q01–Q10 cover structured quality facts, direct retained duplicate representatives before
Top-N, strict scores/duration/auto-only publication, v8/current versus historical contract
and cache identities, complete Schema/domain errors, one semantic repair, current response
failure precedence, indexed multipart errors, exact task/lease-owned immutable redacted
audit, terminal persistence and successful sibling-cache recovery. Independent current
inspection15cb reopened22 SQLite databases,66audit JSON,90indexed part errors and2synthetic
browser ZIPs; ZIP checksums,full decode and subtitles pass. Actual delivered UI was viewed.

## Current retained mini-lesson artifacts

Product run `2585e5c625c146a99547cbd1ea88a24e` belongs to exact Runner test execution `20260912T235027Z-eec6`.
The125-second generated input yields a120-second continuous H264/AAC clip with12valid
clip-relative SRT cues. v8/semantic-v4-quality-v2, persisted config fingerprint and
semantic run/source identity match; the input hash is unchanged.

Manifest: `/Users/junhuaxu/Library/Caches/LiveClip/loop-toolchains/01f16d3fdc04d357/executions/20260912T195929Z-8f0cbbe6/20260912T235027Z-eec6/apps/web/playwright-report/mini-lesson/2585e5c625c146a99547cbd1ea88a24e/manifest.json`

Manifest SHA-256: `92606d3d5e40ae33316e650e61fd6e419ac45121a608b64509d12eaa30805678`.
Seven referenced files comprise MP4,SRT,quality report,contact sheet,rough candidates,
edit plans and transcript. Independent inspection1d3a and Gateway both verified the
hashes and actual full decode. Both main and Gateway actually viewed the contact sheet;
main separately viewed the browser delivered screenshot. The immutable quality report's
visual status remains pending; external inspection records carry the engineering observation.
Synthetic color bars/mock ASR/LLM are not real semantic-content acceptance.

## Preserved failures and environment observations

Seven earlier formal runs remain terminal BLOCKED with their sessions,budgets and evidence:
160102 tool host;173817 snapshot attachment;180403 complete repair/audit;184158 multipart
audit/task routing;185855 response precedence;191908 multipart errors;193445 missing
retained mini artifacts. Each new bounded run followed a concrete verified correction.
ADR031–040 record these corrections; no terminal state or budget was reset.

Local new-test diagnostic0a37 failed on a mistaken fingerprint-property call; corrected
313-test72aa/full lint4d00/Doctor6694 pass. Outer observers393e/fcbb were terminated because
they matched a nonexistent QA run_id field; corrected observers use the actual context
and exact execution parent,f20e/1d3a pass. Formal Runner was never interrupted or modified.

Host pmset records initial Idle Sleep at13:04:11 PDT and repeated maintenance wakes.
Wall-clock gaps include sleep; reported command durations use the existing monotonic clock.
Temporary caffeinate5a83 was bound only to the Loop process; one30-second activity request
de10 was bounded. No global power settings were changed. Source and deterministic evidence
stayed intact. Dependency setup72ec restored the original project's locked toolchain;
its optional local-asr removal was explicitly repaired with the same locked extra.

## Recovery and next task

See [Loop recovery](../loop-engineering.md), ADR030–040 and the
[stable-delivery ExecPlan](../exec-plans/liveclip-stable-delivery.md). Use project Python/
SQLite and retained manifest/task/lease identities. Do not edit audit files or clear caches
to force success. No --last,permission expansion,paid-model run,global upgrade,data cleanup,
real-project migration or remote publication occurred. Old source/data/credential boundaries
remain in AGENTS.md. Root-only trusted dependency ignores still fingerprint nested names.

Next is separately bounded SD-1B: versioned complete Discovery→Chain→natural-unit→final
outcome mapping and source-risk provenance. Freeze new contracts first, then serially
integrate and test the actual flow. No new dispatch or lineage implementation exists yet.

Historical [STATUS](history/sd1a-status-before-acceptance-2026-09-12.md) and
[ExecPlan](history/sd1a-exec-plan-before-acceptance-2026-09-12.md) are preserved byte-for-byte;
current main-owned handoffs summarize them without deleting evidence.

Post-integration3989 PASS:exact27non-document deltas,unchanged accepted source/locks,
all18original optional packages restored by1531,archived history unchanged and current
doc links/format valid. Original root loop-doctor c4e9 is READY.
