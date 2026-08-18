# LiveClip status snapshot

Updated: 2026-08-17 18:27 PDT

Package compatibility baseline: `0.1.0`

Current activity: product development remains paused at the user's direction.
The expanded free-discovery benchmark is complete under
`docs/research/model-benchmark-2026-08-17/`: three generator configurations,
three unique source hashes, nine primary order-perturbed runs, one zero-weight
evidence diagnostic and two independent blind Judges. No Pipeline, database,
source media, render or Delivery state changed. Scoped research checkpoint
`d9f9836` is committed and pushed to `origin/main`.

## Current user-visible result

LiveClip still provides the complete local long-video pipeline, clean review
proxies, exact EditPlan revisions, multi-user Project governance, collaboration
comments, editor handoff, release planning and immutable Delivery.

The editor dashboard now adds server-authorized Project search, filters, stable
keyset pagination, counts/facets and private per-user saved views. Search cannot
leak a private Project through counts, evidence or stale cursors; saved-view
create/retry and update/delete use idempotency/CAS fences.

Real Project `8-16-1` (`953ae56cf15f486cb61ab5b53046ebb5`)
processed `input/8-16-1.ts` through the existing production path:

- source: 2.2 GiB MPEG-TS, 5042.717 seconds, HEVC 1088×1920 plus AAC;
- 60/60 OpenRouter `openai/whisper-large-v3` chunks succeeded;
- 45/45 local Codex `gpt-5.6-terra` editorial analyses succeeded;
- 15 current candidates have titles, Hooks, reasons, captions and clean videos;
- the first render exposed an A/V sync defect caused by non-keyframe HEVC seek
  plus independent source-stream `STARTPTS` resets;
- renderer v4 now decodes a bounded ten-second preroll, performs an accurate
  output seek and preserves one shared source PTS timeline;
- all 15 proxies were regenerated as immutable v4 artifacts without repeating
  ASR or Codex. The Web/CLI now resolve those latest artifacts.

The existing `8.15-1`, `8.15-2` and `7.28` Projects remain visible and their
previous successful proxies remain available. Their prior immutable offline
review packages remain unchanged and ignored by Git.

The user confirmed the corrected A/V synchronization. Offline review package
`8-16-1/v001` was then created from the 15 latest v4 proxies at
`data/projects/953ae56cf15f486cb61ab5b53046ebb5/offline-review-packages/v001`;
its 159 MiB ZIP, all member hashes, all 15 H.264/AAC 540x960 probes and all 15
full decodes pass.

## Three-configuration free-discovery benchmark checkpoint

The authoritative benchmark adds `gpt-5.6-sol / high` to
`gpt-5.6-terra / medium` and `gpt-5.6-sol / medium`. Each isolated generator
received only the same versioned runtime highlighter Skill, strict Schema and
frozen untrusted candidate evidence; it was ephemeral, ignored development
rules/config, had a read-only sandbox and had no tools, browser, Web, plugins,
MCP, memory or multi-agent access. Topic discovery remained entirely free;
the user-rejected fixed-topic diagnostic is not present in this benchmark.

The five input names are only three unique source contents. `8-16-2.ts` is
byte-identical to `8.15-1.ts`; `8-16-1.ts` is byte-identical to `8.15-2.ts`.
Aliases have zero extra weight. The three canonical sources each ran original,
reverse and deterministic shuffled candidate order; a second evidence version
for the `8-16-1` source is reported only as a zero-weight full evidence-chain
sensitivity diagnostic. The experiment therefore contains 30 generator
artifacts and 20 anonymous Judge artifacts across ten groups.

`gpt-5.6-terra / max` and `gpt-5.6-sol / max` independently clustered every
selected highlight exactly once and scored anonymous systems. Source-first
dual-Judge macro totals are Sol High 95.0111, Sol Medium 94.1556 and Terra
Medium 76.6556. High minus Medium is only +0.8555 with two source wins and one
loss, below the 4.0741 Judge total MAE and subject to a saturated 0–4 rubric.
High is more stable under order/sampling perturbation (candidate Jaccard
0.5837, interval F1 0.7286) than Medium (0.5086/0.6647), but is about 34% slower,
uses about 3.5 times the reasoning tokens and has more quote-alignment failures.

The engineering recommendation is Sol Medium by default, Sol High only for
low-confidence Topic grouping, threshold/Top-N boundary cases, evidence/risk
anomalies and independent audit, and Terra Medium as the speed/budget baseline.
This is a next-evaluation routing recommendation, not a production default
change. The Skill proposal uses task stages rather than genre branches: Tier 0
deterministic evidence, Tier 1 candidate assessment, Tier 2 free Topic inventory
and dedup, Tier 3 portfolio selection, Tier 4 editorial copy and Tier 5 audit.

The primary offline report is
`docs/research/model-benchmark-2026-08-17/REPORT.html`; the exhaustive Skill
Creator viewer is `eval-review/REVIEW.html`, and the implementation proposal is
`SKILL-ARCHITECTURE-PROPOSAL.md`. `analysis.json` validates 30/30 generators,
20/20 Judges, 10/10 groups, three unique primary sources and a 343-file hash
manifest. The Browser runtime exposed no registered browser, so the HTML passed
generation/parser/link/content checks but has not been visually confirmed in
MCP Chrome during this session.

## Implementation checkpoints

- `e01820f`: revision-bound collaboration comments.
- `fa395f6`: authorized Project discovery and private saved views, migration
  `f3b6d9a2c841`, API/Web/tests and ADR-018.
- `0a266f3`: bounded accurate transport-stream seek, shared A/V timeline,
  renderer contract `ffmpeg-renderer-v4.av-sync-preroll`, regression tests and
  ADR-019.
- `d9f9836`: isolated three-configuration free-discovery benchmark, dual-Judge
  evidence, deterministic analysis, offline HTML reports and Tiered Skill v2
  research proposal.

The sync fix is in `src/liveclip/renderer/ffmpeg.py`. It uses an input-side seek
at `source_start - min(source_start, 10s)`, decodes the preroll, then uses an
output-side accurate seek. Video/audio source filters no longer independently
subtract `STARTPTS`; overlay/fade windows are shifted onto the preroll timeline.

## Real database and artifact evidence

- Live database: `data/projects/liveclip.sqlite3` at Alembic
  `f3b6d9a2c841 (head)`; `alembic check` reports no pending operation.
- Pre-search WAL-safe backup:
  `data/projects/database-backups/liveclip-pre-project-search-3b1e1c0ad7304d7689452e6ff920c3bd.sqlite3`
  with SHA-256
  `1ed77aca699800797f1a09d3b33004657f6ae1b6ccdb47e0c165913c46883460`.
- Current integrity: `quick_check=ok`, zero foreign-key rows, zero active
  PipelineRuns and zero active Tasks.
- Current protected counts: 4 Projects, 4 SourceMedia, 6 PipelineRuns,
  176 candidates, 90 RenderJobs and 458 ApiUsage rows.
- `8-16-1` latest proxy rows: 15/15 `succeeded`, exact renderer contract v4.
- Each latest MP4 is 540×960 H.264/AAC; all 15 automatic reports, black-frame
  checks and full decodes pass.
- Measured latest MP4 stream-start deltas are either 0 ms or 40 ms (one 25-fps
  video frame), replacing the old content displacement of up to about 2.04 s.
- Timestamp evidence does not alone prove semantic lip sync; the user should
  still play representative clips before formal approval/delivery.

## Latest actual validation

- `make lint`: passed Ruff/format over 223 files, mypy over 136 source files,
  EditPlan schema verification and TypeScript typecheck.
- `make test`: passed 726 Python tests with 13 existing warnings, 57 Web tests,
  Mock Google Chrome E2E 1/1 and isolated real
  FastAPI/leased-Worker/SQLite/FFmpeg Google Chrome E2E 1/1.
- Post-compatibility adjustment: 44 renderer/contract/settings/Pipeline tests
  and `make lint` passed again.
- Real source spike at 1368 seconds: the old direct seek did not decode video
  until about 2.04 seconds after audio; the v4 path starts video at 40 ms and
  audio at 0 ms while preserving the shared source timeline.
- Approval investigation: isolated real Google Chrome/FastAPI/Worker/SQLite/
  FFmpeg E2E passed one content decision, final render, Delivery, release
  submission and release approval. Fifteen focused Web review tests and 14
  atomic-review/authorization tests also pass; append-only evidence is under
  `qa/`.
- API and Web are running at `127.0.0.1:8765` and `127.0.0.1:5173`.
- Expanded benchmark validation passed: 30/30 generator artifacts, 20/20 blind
  Judge artifacts, 10/10 groups, three unique weighted sources, all anonymous
  mappings and cluster coverage, source-first aggregation and 343 artifact
  hashes. Analyzer tests are 7/7; its scripts pass Ruff and `py_compile`.
  `REPORT.html` contains 12 sections, 20 Judge groups and 264 Topic cards;
  `REVIEW.html` contains 30 review runs and 60 Judge evidence views.
- Current-session commands pass: `make lint`; the seven analyzer unit tests;
  benchmark JSON parsing; credential-pattern scan; viewer completeness/build;
  report generation; report relative-link/content checks; and `git diff --check`.
  Browser runtime setup succeeded but `agent.browsers.list()` returned `[]`, so
  no MCP Chrome visual-pass claim is made.
- A final independent read-only verifier returned `PASS` with P0=0 and no
  delivery-blocking P1. It independently recomputed the three macro scores,
  checked all 343 artifact hashes, all 586 Judge cluster memberships, anonymous
  mappings, report reconstruction and the proposed Skill's non-production
  status. Remaining harness-method debts are disclosed in the report.

## Known observations and remaining scope

- Candidate ranks 2/4 overlap 34.4 seconds; ranks 6/12 overlap 8.3 seconds.
  This was observed but not changed during the synchronization repair.
- Real ASR contains some obvious lexical errors such as “强魂” and “甲瘤”;
  captions remain editable and no text was silently rewritten.
- The expanded benchmark measures relative discovery over the three selected
  output unions, not absolute Topic recall: no independent exhaustive truth
  inventory was sealed before generation and Judges did not see every rough
  candidate.
- Replicates combine candidate-order perturbation with model sampling, so their
  stability metrics do not identify a pure causal order effect. A future v1-v2
  evaluation must repeat each order at least twice and hold model config fixed.
- The v1 `highlight_sentence` mixes evidence and edited copy. Confirmed
  cross-candidate/context drift plus heuristic failure rates require separate
  exact `evidence_quote` and editable `edited_sentence` fields with a hard
  deterministic Gate; raw rates alone are not semantic error rates.
- All three unique sources are singing-instruction livestreams. Current evidence
  supports task-tier Skill architecture, not interview/commerce/performance
  genre-specific Skills.
- Semantic lip-sync review of all 15 videos is still a human observation; no
  unsupported automatic mouth-motion claim is made.
- Existing older Projects were not rerendered under v4 because the user scoped
  the operational repair to `8-16-1`; their videos were not hidden or changed.
- Cross-Project optimistic bulk assignment is the next v0.2 collaboration
  slice. Native Jianying/CapCut draft import remains unverified; current editor
  handoff truthfully provides standards-based MP4/SRT metadata packages.
- Persisted `TaskAttempt.temp_identity` propagation through every synchronous
  cleanup call remains the documented cleanup P2.
- The approval audit found a real workflow gap despite green state-transition
  tests: content `ReviewDecision` stores status/reason/time but no actor, the
  API response/UI also has no reviewer identity, and no content-review audit
  event is written. Real `8-16-1` has only `local-admin` as owner/member, yet
  rank 1 became approved at `2026-08-17T05:47:10Z`; current persisted evidence
  cannot identify who performed that action.
- The real Chrome E2E uses one `local-admin` owner for edit, content approval,
  release submission and release approval. It does not prove editor-to-reviewer
  handoff, account switching, decision attribution or transaction-time
  membership revocation. It also deliberately creates Delivery and approves a
  release while the Project lifecycle is still `editorial_review`, then moves
  the lifecycle to `approval` afterward. Therefore the current Project
  `approval` stage is informational/manual rather than an enforced workflow
  gate. No approval code or real Project data was changed pending user review.

## Security and worktree

- Never stage `.env`, `.env.local`, `OPENROUTER_SETUP.md`, `input/`, `data/`,
  SQLite/WAL, media, browser artifacts or offline packages.
- No source video was overwritten. Corrected proxies use fingerprinted new
  paths; historical proxy bytes remain immutable.
- No OpenRouter call was made and no Codex result was written into the product
  database. The expanded benchmark made 28 new tool-disabled generator calls,
  reused two byte/input/Prompt/Schema-identical pilot results, and made 20 new
  blind Judge calls. They wrote only research artifacts; no render was repeated.
- Source/test/docs checkpoints include `fa395f6`, `0a266f3` and `d9f9836`;
  generated/private paths remain ignored and unstaged.

## Next concrete task

Keep product development paused. The next concrete task is human review of
`REPORT.html` and, where needed, the exhaustive `eval-review/REVIEW.html`, then
the user's decision whether to implement and evaluate the Tiered Skill v2.
Do not rerun the 50 generator/Judge artifacts: their raw results and hashes are
complete. If v2 is approved, fix Sol Medium as the first A/B model and compare
v1/v2 before changing any production default.

The previously requested Web quantity range/minimum-score/manual-score slice
has not been implemented. The approval-workflow audit and cross-Project bulk
assignment also remain pending separate user decisions.

## Resume instructions

Read `AGENTS.md`, both Product Specs, `docs/SOLUTION.md`, `.agent/PLANS.md`,
both Living ExecPlans and this file. Run `git status --short --branch`,
`git log -5 --oneline`, `.venv/bin/alembic current`, `.venv/bin/alembic check`
and confirm API/Web health. Preserve all four real Projects, both database
backups and existing offline-review packages. Verify `fa395f6` and `0a266f3`
are present/pushed. Open `8-16-1`, confirm the latest proxy path contains an
`s-.../t-.../review.mp4` segment and preserve offline-review `v001`. Read the
latest `qa/pipeline.jsonl`, `qa/test-report.md`, the new benchmark
`REPORT.html`, `analysis.json` and `SKILL-ARCHITECTURE-PROPOSAL.md`. Confirm
`analysis.json` still hashes to
`fa7029c10b593a987b285132d241fcda7fb102ec26f45da4899c64d46575e2de`
and do not rerun the remote experiment. Resume implementation only after the
user accepts a named next slice.
