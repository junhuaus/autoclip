# LiveClip status

## Operator authorizations (2026-10-21)

- Real pipeline runs are allowed without per-run consent. ASR uses local
  models. Since the 2026-10-21 operator directive (Stage 7), the
  understanding engine for dual-profile runs is the local Claude Code CLI
  (`LIVECLIP_STRUCTURED_PROVIDER=claude-cli`); Codex remains selectable.
  Claude CLI runs are authorized only through the claude.ai subscription
  login, never an API key. Subscription runs incur no per-call charge, but
  if the account's paid "extra usage" is enabled, usage beyond the
  subscription allowance could incur charges. (History: this bullet
  originally said the LLM engine is the Codex CLI, so runs incur no paid
  usage.)
- Copying local assets from `/Users/junhuaxu/autoclip` into this worktree's
  ignored paths is allowed. The Controller has already cloned
  `input/8-30.ts` (its sha256 matches the ExecPlan) and `data/evaluations/`.
  Those paths stay ignored and local-only.
- Push and merge still require explicit operator consent.

## Stage 19: customer delivery of dual-profile results (2026-11-07) — Stage 19a ACCEPTED at ba1e8b0; Stage 19b IMPLEMENTED, pending independent verification

- **Stage 19a accepted** at `ba1e8b0` (tester: lint rc 0, backend 3353,
  vitest 80, e2e 4; reviewer ACCEPT-WITH-NITS, five freeze-evidence items
  reproduced, five deviations accepted). Reviewer nits fixed in
  `29dd574cdaa8587173fb555daa2d26fe81b7819c`: strict customer-link shapes (P2-3), a select counts only
  after the latest review decision and select on a non-deliverable clip is
  refused (P2-4), BEFORE DELETE guards via migration `e4b2c7d9a1f3` with the
  project-purge cascade still working (P2-5), absolute-path tamper case
  (P2-7), docs P2-1/P2-2/P2-8/P2-9; P2-6 recorded as a pre-existing residual.
- **Stage 19b implemented** at `cf11aefd513f9b26a87a8e7ceae7ecd9fec8fa56` (pending independent tester and
  reviewer): import API, internal review API (authz: approve/reject
  `review_clip`, select/deselect `deliver`, viewer read-only, non-member
  404, select on non-deliverable 409), imported projects listed and
  searchable (`source_kind` `dual_profile_import`, `current_run_id` "",
  `generation` 0), web "导入双轨结果" dialog and `DualProfileReviewSection`
  (短片/小课 groups, prefilled approval form, gated 选入交付). Details and
  deviations in `docs/exec-plans/liveclip-customer-delivery.md` ("Stage 19b
  results", Decision Log).
- Freeze evidence at `cf11aef`: closure diff rc 0; pins and 17/17
  recompute; Settings fingerprint unchanged; evaluator re-run on
  cold-35/cold-36 byte-identical; `dual_profile_delivery.py` unchanged since
  `cb13bb6`; `python -m liveclip dual-profile-eval --help` rc 0.
- Validation: `make lint` rc 0; targeted API/import/migration/settings pytest and vitest green; full `make test` at `cf11aefd513f9b26a87a8e7ceae7ecd9fec8fa56` rc 0: backend pytest 3424 passed (15 deprecation warnings), vitest 15 files / 87 tests passed, e2e 5 passed (mock: `review-delivery.spec.ts` and the new `dual-profile-review.spec.ts`; real-browser: 3 scenario runs). Unrelated pytest processes from other host repositories were running during the suite; they were not touched.
- (Historical next step; reviewed below.) Next: independent tester and reviewer for Stage 19b, then 19c. Push, PR
  and merge need explicit user consent.
- **Stage 19b review (68e6edb): tester green, reviewer REJECT on P1** —
  pipeline actions were possible on imported projects (`POST
  /projects/{id}/runs` queued a run and turned the project into a pipeline
  project). **Fixed in `248082c7fbb4a9b2a5a3dbc903acb4263eb13179`**: `create_run` refuses imported projects in
  its transaction; imported projects expose only read, manage_members,
  manage_project, review_clip, comment, deliver, and every other mutation
  returns 409 server-side (runs, batch review, legacy deliveries, edit
  packages, releases tested with valid bodies); `ProjectSnapshot`
  validator; P2s (managed data dir excluded like `/jobs`, no existence
  oracle, root parsing, profile-matched links, archived/purge tests,
  不通过 wording, e2e request log). The Stage 19a reviewer P2-6 residual is
  recorded verbatim in the ExecPlan. Freeze evidence at `248082c`: closure
  diff rc 0, single alembic head `e4b2c7d9a1f3`, `dual-profile-eval --help`
  rc 0, pins in the full run. Validation: `make lint` rc 0; full `make test` at `248082c7fbb4a9b2a5a3dbc903acb4263eb13179` rc 0: backend pytest 3447 passed (15 deprecation warnings), vitest 15 files / 87 tests passed, e2e 5 passed (2 mock specs, 3 real-browser scenario runs).
- (Historical next step; done.) Next: re-review of Stage 19b, then 19c. Push, PR and merge need explicit
  user consent.
- **Stage 19b ACCEPTED at `7fc669b`** (tester: lint rc 0, make test
  3447/87/5, focused 211, freeze rc 0, single head; reviewer
  ACCEPT-WITH-NITS after auditing all 84 routes).
- Stage 19b reviewer nits (2026-11-07, after acceptance at `7fc669b`): (P2-a)
  for an imported project, a role-denied call (for example a viewer) or any
  mutation on an archived project returns 403 from `require_project_action`
  before the imported-project guard returns 409; (P2-b) `POST
  /releases/{id}/approval` keeps its read-level lookup, because the real
  action (`approve_release` vs `manage_release`) depends on the release's
  current state and differs by role — switching the lookup to
  `manage_release` would deny reviewers who may approve today; the second
  `_require_project_access` call already enforces the real action and the
  imported-project guard (and an imported project has no release items), so
  only an explanatory comment was added; (P2-c, Controller decision)
  `comment` is removed from the imported-project actions (no route accepts
  comments on imported clips): owner read/manage_members/manage_project/
  review_clip/deliver, editor read/deliver, reviewer read/review_clip.


- **Stage 18 is merged to `main`:** `origin/main` =
  `a79deaf0a62e4a506b8ea2c3221e9388d12dd286`, the merge commit of PR #2
  (`claude/liveclip-stage18-l05`); its tree equals `d386981`. Stage 18
  strict benchmark acceptance (2/2 on frozen `f525338`) is unchanged.
- Branch `claude/liveclip-stage19-customer-delivery` created from
  `origin/main` `a79deaf` (no upstream set; not pushed).
- Authoritative plan: `docs/exec-plans/liveclip-customer-delivery.md`
  (user decisions of 2026-11-07, design, stages 19a–19e, freeze closure).
  User decisions: end-customer audience (read-only watch, read and
  download; no internal fields); offline ZIP package and expiring
  read-only LAN share link; import existing dual-profile CLI results
  first; customer text overrides at approval (originals immutable); clean
  MP4 plus separate SRT; LAN-only share link, explicit opt-in, no TLS.
- **Freeze rule amended (user decision 2026-11-07):** the benchmark freeze
  now covers only the dual-profile benchmark closure; see the amendment
  bullet at the end of "Acceptance policy from Stage 17" below for the
  path list and the five-item reviewer evidence. Closure verified by an AST
  import walk at `a79deaf`; `git diff --exit-code f525338 -- <closure>`
  rc 0. Added to the Controller's draft list: `cli/app.py` and
  `__main__.py` (the `dual-profile-eval` command owns the `--short-top-n`
  and `--mini-lesson-top-n` defaults of 15 used by the counted runs),
  package `__init__` files, `domain/`, `media/` and `pipeline/` modules
  imported by the closure, `limits.py`, `prompts/`, `observability/`,
  `scripts/__init__.py`, `pyproject.toml`, `uv.lock`.
- Discovery: the existing `dual-profile-review-package` CLI rejects the
  stored cold-36 render manifest ("video path is not an absolute system
  path") because its video/subtitle paths are repo-relative; Stage 19a's
  import resolves relative paths against an allowed import root.
- (Historical next step; done below.) Next: Stage 19a (freeze pin test, verified render-set refactor, eligibility
  domain, migration and repository, import service, `CustomerClipView`).
  Human editorial/audio review of cold-27 r2 through cold-36 renders and
  the L07 listening check remain pending (separate evidence category).
  Push, PR and merge need explicit user consent.
- **Stage 19a implemented, pending independent tester and reviewer.**
  Commits `cb13bb69098f26cafd9f7ec752ccd2d4ebef64b6` (freeze pin test;
  `load_verified_dual_profile_render_set()` extracted from
  `export_dual_profile_review_package`), `096a7ca1884ce1ff6d5b1b8daa3010e37a61881b` (eligibility
  domain `src/liveclip/domain/customer_delivery.py`, migration
  `d5e8a1c3f907` with six tables and immutability triggers, models,
  `src/liveclip/db/dual_profile_repository.py`,
  `src/liveclip/application/dual_profile_imports.py`, `CustomerClipView`,
  tests), `437f5f015e2f0f43b51c4c42f9905834973733e8` (concurrent-import test),
  `49f8f661e5542eac593052a1d4d662c43b20f995` (schema inventory test). No API route or UI
  yet (19b). Details and deviations (stricter eligibility: a later reject
  also blocks an auto-`selected` clip; idempotency per importer and
  snapshot; relative render paths resolved against the repo base;
  separate transcript roots) in the Stage 19 ExecPlan.
- Freeze evidence at `096a7ca` (and unchanged at the docs HEAD): closure
  diff to `f525338` rc 0; pins 21 passed and independent recompute 17/17;
  Settings fingerprint `c81f0ece91debb4f1637ba5eecc3af64a91da256f586917408de458317d170d1`; evaluator
  re-run on stored cold-35/cold-36 byte-identical; cold-36 review package
  byte-identical before/after the refactor with a fixed clock (69 files,
  `manifest.json` `a7a5a6f13f3cb651b494a0ed9784c3048092161eee71c859215544c20b0e2590`), and identical except
  `created_at` via the CLI. The stored cold-36 render manifest has
  repo-relative video/subtitle paths that the existing export rejects, so
  the comparison used an APFS clone with absolutised paths in scratch.
- Real-data smoke (read-only on `data/evaluations`): cold-36 imports into
  a scratch data dir as 12 clips (7 short, 5 mini), all `manual_review`,
  0 deliverable before approval; re-import is idempotent.
- Validation: `make lint` rc 0; targeted pytest 364 passed; full `make test` at `49f8f661e5542eac593052a1d4d662c43b20f995` rc 0: backend pytest 3353 passed (15 deprecation warnings), vitest 14 files / 80 tests passed, e2e 4 passed. (A first full run at `437f5f0` had 2 failures: `tests/unit/test_db_models.py` schema inventory, fixed in `49f8f66` by listing the six new tables, and `tests/unit/test_b2_synthetic_worker.py::test_canonical_independent_worker_commits_two_real_pauses` (`needs_action` instead of `succeeded`), which passed 3/3 in isolation and in the second full run; the first run overlapped an unrelated pytest process on the host, so it is classified transient and timing-related, recorded, not hidden).
  Deterministic only; no real model call.
- Next: independent tester and reviewer for Stage 19a (re-check the five
  freeze-evidence items), then Stage 19b. Push, PR and merge need explicit
  user consent.
- Resume prompt: "Read CLAUDE.md, AGENTS.md, STATUS.md (Stage 19 section)
  and docs/exec-plans/liveclip-customer-delivery.md; on branch
  claude/liveclip-stage19-customer-delivery verify the five freeze-evidence
  items, then continue with the first unchecked Stage 19 milestone."

## cold-36 real run on frozen f525338 (2026-11-06) — strict PASS 92.5 (fresh cold; consecutive cold strict PASS 2/2 for f525338; Stage 18 strict acceptance satisfied)

- **Counted run 2 of 2** on the Stage 18 freeze
  `f525338ed9427b0fcac9925bac6075d60af13e69` under the unchanged acceptance policy. Fresh cold, real
  Claude CLI, single segment. HEAD at run time `f6b7882` (three docs-only
  commits `2812985`, `15c4ff8`, `f6b7882` on top of the freeze SHA);
  freeze-diff to `f525338` (including `.gitignore`) rc 0 with empty
  porcelain before and after the run. Eval rc 0, wall 7511 s (2026-11-06
  12:28:05 to 14:33:16 local; attempt start epoch 1793996885, 12:28:05
  −0800); 0 sleep/wake events in the window; AC power throughout.
- Roots
  `data/evaluations/dual-profile-{benchmark,cache,strict-eval}-20261106-claude-cold-36`
  (the strict-eval root holds `benchmark-result.json`,
  `benchmark-report.md` and `evidence/`).
- Strict **PASS 92.5**: both_profiles 15, short 17.5, mini 25, boundary 15,
  risk 10, audit 10; `qualified_boundary_hits` 12. No hard failure, PASS
  blocker, direct-fail condition, forbidden-composite, padding,
  negative-anchor, duration or regression finding (every finding list
  empty); `source_hash_matches` true. Short 7/8 (S03 missed; S06
  −2300/+2860 ms; S01, S02, S04, S05, S07, S08 0/0 ms). Mini 5/6 (L01–L04
  0/0 ms; L05 `audit_ml_0015_live_diagnosis_mix_voice_high_notes`
  0/−4060 ms, `manual_review`; L07 missed). R01 blocked and R02 blocked
  (R02 was `manual_review` in cold-33, cold-34 and cold-35), both routed
  correctly. 0 selected rows in either profile; N07, N08 and both
  composites clean.
- L07 miss (representative-choice variance; no quality flag involved):
  the in-tolerance row 2855–2974
  (`confirm_nasal_sample_to_rhinitis_qualification`, 0/+1980 ms) was
  rejected by Global Review as a duplicate of the retained 2854–2974
  representative `precision_yuge_nasal_correction_rhinitis_closure`
  (−30540/+1980 ms, `manual_review`), because the evaluated sung sample
  sits in an untranscribed gap before cue 2855. L07 also missed in cold-31.
  Recorded as known residual fragility, measured only; no patch under the
  freeze (`evidence/near-misses.txt`).
- Stage 18 watch items (`evidence/stage18-watch.txt`): (1) **L05**: 3
  in-tolerance mini rows, none with `material_interruption`; every
  Boundary Review reason applies the passing-pen carve-out to the pen
  remark at cues 2337–2340 (Chinese wording: a passing mention that the pen
  broke, then straight back to the same point, "不算中断/不算打断"). The
  out-of-tolerance 2287–2394 row is blocked with `material_interruption`
  from the farewell and mic invitation at cues 2374–2383, the same
  mechanism as cold-35. (2) **N07**: all 9 overlapping mini rows are
  `blocked` or rejected; the six rows that contain the pause carry
  `material_interruption` for the pen-testing pause at cues 1030–1035; the
  carve-out is invoked only to deny it; no padding or negative-anchor
  finding; no 998–1048 or 1028–1172 row this run. (3) **Composites**:
  562000–847000 has 11 blocked and 2 rejected mini rows, 1099200–1351000
  has 14 blocked and 2 rejected; none selected or `manual_review`. (4)
  **L04** representative: cues 1049–1130, exact. (5) **S01/S04**: both
  0/0 ms, unchanged. (6) **S03** (measured only): missed; 476–506 is
  `manual_review` at +12440/0 ms and the in-tolerance 472–506 row
  (+2400/0 ms) was rejected as a duplicate of that shorter row, the same
  mechanism as cold-33. (7) **Provenance** (below). (8) Discovery
  `material_interruption` flags mini 91 / short 44 (cold-35 86/39,
  cold-34 92/51, cold-33 102/59).
- Provenance (meets the fresh-cold definition): run-manifest `cache_hits`
  0; run and cache roots did not exist at attempt start; 268 cache files,
  every mtime after the attempt start; 0 cached `prompt_hash` mismatches;
  0 content-identical files in 31 other cache roots (informational only;
  81 same-key file names in the cold-35 root, none content-identical).
  The run manifest, and therefore the run fingerprint, carries the 14
  executed-stage prompt hashes (short_highlight `precision_audit`,
  `precision_confirmation` and `risk_discovery` are not executed); all 14
  equal the Stage 18b "after" column. Separately, all 17 prompt identities
  recomputed from the tree (`evidence/step0-tree-prompt-hashes.txt`) equal
  the Stage 18b table.
- Provider: 269 provider records (run-manifest calls: Discovery 160,
  Boundary Review 78, Global Review/Audit 29, variant link 1, plus 1
  repair record), all succeeded on the first attempt; 1 successful repair
  (Boundary Review), 0 retries, no usage-limit marker. Tokens in
  10,737,580 / out 1,980,892.
- **Run fingerprint identical to cold-35:** Claude CLI 2.1.308, sha256
  `ca923c86ac84b30574a82331a05b6e066c27477a926ceaffe46a845a33e4dd37` (pin unchanged); model `claude-opus-5-5`;
  algorithm `dual-profile-direct-v1`; routing `quality-gate-risk-routing-v9`;
  Settings fingerprint sha256
  `c81f0ece91debb4f1637ba5eecc3af64a91da256f586917408de458317d170d1` (unchanged); run fingerprint sha256
  `e8bef66db0a64159a4ba45be73ee85d501e8bb8200b96df4c8248aa48880e3f0` (fingerprint input dicts identical,
  `evidence/fp-compare.txt`). No `LIVECLIP_CLAUDE_*` override in `.env`
  (absent) or `.env.local` (key names only recorded).
- Evaluator (informational): `scripts/evaluate_benchmark.py` and the two
  root benchmark files (`liveclip_dual_profile_benchmark_v1.json`/`.md`)
  are unchanged since `2c4de9a`; `src/liveclip/pipeline/dual_profile.py`,
  whose schema classes the evaluator imports, is unchanged between
  `50232af` and `f525338` (Stage 18 changed only prompts and two test
  files). `scripts/benchmark_gates.py`, which the evaluator also imports,
  last changed in `8b14aa3` (Stage 4, comment-only) and has no diff over
  `8b14aa3..4bb17a8`; `8b14aa3` is an ancestor of `50232af`. The
  reviewer's re-evaluation of cold-35 and cold-36 is byte-identical to the
  stored results (a coder re-run of the stored argv into a scratch
  directory also reproduced `benchmark-result.json` and
  `benchmark-report.md` byte-identically). cold-35 and cold-36 are
  therefore scored by the same evaluator and benchmark as cold-33 and
  cold-34.
- Renders: 12 clips (7 short, 5 mini), rc 0, automatic checks pass. Visual
  and audio review pending (separate evidence category, not part of
  strict PASS). The evaluator's `human_required` check
  `title_hook_summary_must_be_source_faithful` lists 64 candidate IDs
  (verified read-only against the stored `benchmark-result.json`), exactly
  the `manual_review` rows (mini 23 + short 41); both cold-35 and cold-36
  auto-select 0 candidates in both profiles, so every short and mini match
  is `manual_review` (R01 and R02 are `blocked` in cold-36).
- **Consecutive cold strict PASS count for `f525338`: 2/2 (cold-35 PASS
  97.5, cold-36 PASS 92.5).** The acceptance policy (2 consecutive
  fresh-cold strict PASSes on the frozen tree) is satisfied for the
  Stage 18 freeze; **Stage 18 strict benchmark acceptance is complete on
  `f525338`.** The `50232af` acceptance (cold-33/cold-34) remains the
  historical baseline.
- Residuals (recorded, no patch under the freeze): S03 (structural,
  deferred; missed in every cold run since cold-30), L07
  representative-choice variance (above), and the accepted Stage 18
  reviewer prompt nits P2-1, P2-3, P2-4 and P2-6.
- Still pending, each a separate evidence category that strict PASS does
  not claim: (1) human editorial/audio review of the renders of cold-27
  r2, warm-28, warm-29b, cold-30, cold-31, cold-32b, cold-33, cold-34,
  cold-35 and cold-36; it also covers the `human_required` source
  faithfulness check (61 IDs for cold-35, 64 for cold-36); (2) the L07
  listening check of `input/8-30.ts` 1:40:07–1:40:35. Branch
  `claude/liveclip-stage18-l05` is not pushed; push, PR and merge need
  explicit user consent.
- Recovery: docs-only; reverting this commit removes only this record (the
  documented count returns to 1/2). No code, prompt, routing, algorithm,
  evaluator or benchmark change; the freeze is unaffected.
- **Next:** human editorial/audio review of the renders listed above, the
  source-faithfulness review and the L07 listening check (user);
  push/PR/merge only with explicit consent.

## cold-35 real run on frozen f525338 (2026-11-06) — strict PASS 97.5 (fresh cold; consecutive cold strict PASS 1/2 for f525338)

- **Counted run 1 of 2** on the Stage 18 freeze
  `f525338ed9427b0fcac9925bac6075d60af13e69` under the unchanged acceptance policy. Fresh cold, real
  Claude CLI, single segment. HEAD at run time `15c4ff8` (two docs-only
  commits `2812985`, `15c4ff8` on top of the freeze SHA); freeze-diff to
  `f525338` (including `.gitignore`) rc 0 with empty porcelain before and
  after the run. Eval rc 0, wall 6952 s (2026-11-06 10:20:35 to 12:16:27
  local; attempt start epoch 1793989235, 10:20:35 −0800); 0 sleep/wake
  events in the window; AC power throughout.
- Roots
  `data/evaluations/dual-profile-{benchmark,cache,strict-eval}-20261106-claude-cold-35`
  (the strict-eval root holds `benchmark-result.json`,
  `benchmark-report.md` and `evidence/`).
- Strict **PASS 97.5**: both_profiles 15, short 17.5, mini 30, boundary 15,
  risk 10, audit 10; `qualified_boundary_hits` 13. No hard failure, PASS
  blocker, direct-fail condition, forbidden-composite, padding,
  negative-anchor, duration or regression finding; `source_hash_matches`
  true. Short 7/8 (S03 missed; S06 −2300/+2860 ms; S01, S02, S04, S05,
  S07, S08 0/0 ms). Mini **6/6** (L01–L04 0/0 ms; **L05
  `audit_student_high_note_live_diagnosis` 0/−4060 ms, `manual_review`,
  a new hit**; L07 0/+1980 ms). R01 blocked and R02 `manual_review`, both
  routed correctly. Informational R02 diagnostic (gates nothing):
  `risk_findings.R02.misrouted` is not empty but lists
  `ml0014_regional_nasal` (cues 1990–2053, rejected by Global Review as a
  duplicate, with the blocked risk twin `risk_nasal_regional_attribution`;
  `required_routing` [`blocked`, `manual_review`]), while the evaluator
  hard-fails only when a required risk anchor has no matched candidate
  (`scripts/evaluate_benchmark.py:371-372`), R02 is matched by the
  `manual_review` row `ml0014_nasal_full_chain`, the risk component is
  10/10, and cold-31, cold-33, cold-34 and cold-36 have empty `misrouted`
  lists. 0 selected rows in either profile.
- Stage 18 watch items (`evidence/stage18-watch.txt`): (1) **L05**: no
  in-tolerance row carries `material_interruption`; Boundary Review
  explicitly applies the passing-pen carve-out to cues 2337–2340. The
  blocked 2287–2394 rows are out of tolerance; their
  `material_interruption` comes from the farewell and mic invitation at
  cues 2374–2389. (2) **N07**: all 9 overlapping mini rows are `blocked`
  or rejected; the rows containing the pause are blocked for
  `material_interruption` over the pen-testing pause at cues 1030–1035;
  the carve-out is invoked only to deny it ("about 13 s, not a passing pen
  fault"); no padding or negative-anchor finding; no 998–1048 or 1028–1172
  row appeared this run. (3) **Composites** 562000–847000 and
  1099200–1351000: no selected or `manual_review` mini row. (4) **L04**
  representative: cues 1049–1130, exact. (5) **S01/S04**: both 0/0 ms,
  unchanged from cold-33/cold-34. (6) **S03** (measured only): missed;
  Discovery proposed 475–506, which Boundary Review trimmed to 476–499
  (+12440/−11160 ms) because "500–506 is a new topic"; the 470–499 rows
  were rejected as duplicates. (7) **Provenance** (below). (8) Discovery
  `material_interruption` flags mini 86 / short 39 (cold-34 92/51, cold-33
  102/59, cold-32b 69/21).
- Provenance (meets the fresh-cold definition): run-manifest `cache_hits`
  0; run and cache roots did not exist at attempt start; 264 cache files,
  every mtime after the attempt start; 0 cached `prompt_hash` mismatches;
  0 content-identical files in 30 other cache roots (informational only).
  All 17 prompt identities recomputed from the tree
  (`evidence/step0-tree-prompt-hashes.txt`) and the 14 run-manifest
  executed-stage hashes equal the Stage 18b "after" column.
- Provider: 265 provider records (run-manifest calls: Discovery 160,
  Boundary Review 75, Global Review/Audit 28, variant link 1, plus 1
  repair record), all succeeded on the first attempt; 1 successful repair
  (Boundary Review), 0 retries, no usage-limit marker. Tokens in
  10,382,502 / out 1,857,884.
- **Run fingerprint (cold-36 must match):** Claude CLI 2.1.308, sha256
  `ca923c86ac84b30574a82331a05b6e066c27477a926ceaffe46a845a33e4dd37` (pin unchanged); model `claude-opus-5-5`;
  algorithm `dual-profile-direct-v1`; routing `quality-gate-risk-routing-v9`;
  Settings fingerprint sha256
  `c81f0ece91debb4f1637ba5eecc3af64a91da256f586917408de458317d170d1` (unchanged); run fingerprint sha256
  `e8bef66db0a64159a4ba45be73ee85d501e8bb8200b96df4c8248aa48880e3f0`. It differs from the cold-33/cold-34
  value `04f5de6e76150fd763c5669be38aed69a32376097e5c2f874c902f89052b9cc5` only through `prompt_hashes`
  (13 of the 14 executed-stage hashes change; variant link unchanged),
  verified by substituting the cold-35 `prompt_hashes` into the cold-34
  fingerprint input (`evidence/fp-compare.txt`), as the freeze expects. No
  `LIVECLIP_CLAUDE_*` override in `.env` (absent) or `.env.local` (key
  names only recorded).
- Renders: 13 clips (7 short, 6 mini, including the new L05 clip), rc 0,
  automatic checks pass. Visual and audio review pending (separate
  evidence category, not part of strict PASS). The evaluator's
  `human_required` check `title_hook_summary_must_be_source_faithful`
  lists 61 candidate IDs, exactly the `manual_review` rows (mini 21 +
  short 40).
- **Consecutive cold strict PASS count for `f525338`: 1/2.**
- Recovery: docs-only; reverting this commit removes only this record (the
  documented count returns to 0/2). No code, prompt, routing, algorithm or
  benchmark change; the freeze is unaffected.
- (Historical next step; done: cold-36 strict PASS 92.5, count 2/2 for
  `f525338`, see the cold-36 section above.) **Next: cold-36** (consecutive run 2 of 2) on the same frozen tree
  `f525338` with the same run fingerprint `e8bef66db0a64159a4ba45be73ee85d501e8bb8200b96df4c8248aa48880e3f0`; a
  cold-Nb continuation counts as one run. Pre-run checks and the eight
  watch items as for cold-35. Human editorial/audio review of the cold-27
  r2 through cold-35 renders and the L07 listening check stay pending
  (separate evidence category). Push and merge still need explicit
  consent.

## FREEZE ACCEPTED at f525338 (Stage 18) (2026-11-06) — consecutive cold strict PASS 0/2

- **Freeze SHA `f525338ed9427b0fcac9925bac6075d60af13e69`** (Stage 18 code commit, prompts and
  tests only). On `claude/liveclip-stage18-l05`; not pushed or merged to
  `main`. It replaces `50232af` as the frozen tree for new counted runs;
  the `50232af` acceptance (cold-33/cold-34, 2/2) stays the historical
  baseline for that tree.
- **Tester:** independent tester at `2812985` (freeze-diff to `f525338` empty):
  `make lint` rc 0; backend pytest 3241 passed; vitest 80 passed; e2e 4/4;
  concurrency 5/5; media-process 3/3; flag contract
  (`test_dual_profile_flag_contract.py`) 3/3 repeats, 119 passed each;
  no sleep during the suite. Deterministic validation only; no real model
  call, no render, no human review.
- **Reviewer:** independent reviewer at `2812985`: ACCEPT with nits; no P0
  or P1. Nits P2-1 to P2-6: P2-2 and P2-5 are docs wording and are fixed in
  this commit; P2-1, P2-3, P2-4 and P2-6 are prompt wording and are accepted
  residuals (below). No code or prompt change.
- **FROZEN (definition, as for `50232af`, now against `f525338`).**
  `git diff --quiet f525338 -- src tests scripts config tools apps
  migrations pyproject.toml uv.lock alembic.ini Makefile
  liveclip_dual_profile_benchmark_v1.json liveclip_dual_profile_benchmark_v1.md
  .gitignore` must exit 0, with empty porcelain, before and after each
  counted run. In addition: (a) all 17 prompt identities computed from the
  tree equal the "after (Stage 18)" column of the Stage 18b table in the
  Stage 18 section below; (b) routing policy `quality-gate-risk-routing-v9`;
  (c) algorithm version `dual-profile-direct-v1`. Docs-only commits on top
  of the freeze SHA are allowed.
- **Run environment (unchanged rules).** The same pinned Claude CLI binary
  (`.cache/claude-cli/2.1.308/claude`, `--version` 2.1.308, sha256
  `ca923c86ac84b30574a82331a05b6e066c27477a926ceaffe46a845a33e4dd37`); the same Settings fingerprint (sha256
  `c81f0ece91debb4f1637ba5eecc3af64a91da256f586917408de458317d170d1`); the same no-override rule (no `.env` or
  `.env.local` override of the `LIVECLIP_CLAUDE_*` model, timeout or attempt
  settings; each run records `ls -la .env .env.local` presence and, for a
  present file, only the names of its `LIVECLIP_` keys, never values). The
  two counted runs need equal run-manifest `provider`, `model`,
  `prompt_hashes`, final-validated routing policy and algorithm version.
  Check at this docs commit (2026-11-06): `.env` absent; `.env.local`
  present and ignored (`.gitignore` `.env.*`), with no `LIVECLIP_CLAUDE_*`
  and no `LIVECLIP_STRUCTURED_PROVIDER` key; the CLI binary's recomputed
  sha256 equals the pin and `--version` prints 2.1.308.
- **Run fingerprint.** The run fingerprint is expected to differ from the
  cold-33/cold-34 value `04f5de6e76150fd763c5669be38aed69a32376097e5c2f874c902f89052b9cc5` only through
  `prompt_hashes` (the 14 executed-stage hashes change to the Stage 18
  values); any other difference disqualifies the run. The second counted
  run must match the first run's fingerprint, as cold-34 matched cold-33.
- **Fresh cold and counting (unchanged).** The fresh-cold provenance
  criterion of the `50232af` FREEZE section applies unchanged (run-manifest
  `cache_hits == 0`, a new or empty cache root at start, every cache file's
  mtime at or after the attempt start; a cold-Nb continuation may copy only
  the immediately previous segment of the same run, with `cache_hits` equal
  to the copied entries; content identity against other roots is
  informational only). A cold-Nb continuation counts as one run. A warm or
  seeded run is a diagnostic, never acceptance evidence.
- **Per-run watch items (reviewer; each counted run records all eight).**
  (1) L05: status and `material_interruption` reasons of the in-tolerance
  L05 rows, and whether any reason still cites the pen remark (cues
  2337–2340). (2) N07-overlapping mini rows (the 1023–1130 / 1023–1172
  class, the 998–1048 risk row, the 1028–1172 row): they must stay
  `blocked` or rejected for the pen-testing pause, with no
  `irrelevant_padding` or negative-anchor finding; record whether any
  reason invokes the carve-out. (3) Composites 562000–847000 and
  1099200–1351000: no selected or `manual_review` mini output. (4) The L04
  representative. (5) The S01 and S04 start/end offsets. (6) The S03
  outcome (measured only). (7) Provenance and prompt hashes (fresh-cold
  criterion; every `prompt_hash` equals the Stage 18b "after" column).
  (8) Discovery `material_interruption` flag counts compared with cold-34
  (mini 92 / short 51).
- **Accepted residuals (reviewer P2, unchanged by decision; any prompt edit
  breaks this freeze).** (P2-1) The item list says "stopping to wait for,
  test, request or change a pen or colour" while the carve-out says "does
  not stop to wait for, test or replace it", so a passing request for
  another pen is ambiguous between the two. (P2-3) "The only exemption
  is…" sits next to the carve-out (`main.md:28`,
  `stages/risk_discovery.md:16`, `stages/coverage_audit.md:34`, under
  `src/liveclip/clipping_skills/dual_profile_v1/`), which can read as a
  conflict with "only". (P2-4) `stages/global_audit.md` lines 62–72: the
  rule is one long semicolon list with uneven punctuation. (P2-6) Pen
  remarks in an edge position (at a candidate's start or end) are not
  addressed by separate wording. All four are recorded for a future prompt
  revision.
- **Docs nits fixed here (reviewer P2-2, P2-5).** P2-2: the Stage 18
  amendment in `docs/PRODUCT_SPEC.md` no longer says "general, not tuned to
  any benchmark anchor"; it now says the wording is general and motivated
  by the L05 miss. P2-5: the Stage 18 recovery bullet below now says that
  reverting restores the `50232af` frozen-path and prompt tree (docs
  differ).
- **Consecutive cold strict PASS count for `f525338`: 0/2.**
- Recovery: docs-only; reverting this commit removes only this record and
  the two wording fixes. No code, prompt, routing, algorithm or benchmark
  change.
- (Historical next step; done: cold-35 strict PASS 97.5, count 1/2 for
  `f525338`, see the cold-35 section above.) **Next: cold-35**, the first counted fresh cold run on `f525338`.
  Pre-run: freeze-diff (including `.gitignore`) rc 0 with empty porcelain;
  new empty cache root; CLI sha256 and version; `.env`/`.env.local`
  presence and `LIVECLIP_` key names; record the eight watch items. Human
  editorial/audio review of the earlier renders and the L07 listening check
  stay pending (separate evidence category). Push and merge still need
  explicit consent.

## Stage 18: passing pen-remark carve-out from `material_interruption` ("L05 only") (2026-11-06) — ACCEPTED at f525338 (FREEZE SHA; was implemented, pending independent tester and reviewer; freeze of 50232af broken)

- **Status: ACCEPTED at `f525338` (new freeze SHA; see the FREEZE section
  above). Was: implemented, pending independent tester and reviewer.** Prompts
  and tests in `f525338ed9427b0fcac9925bac6075d60af13e69` on `claude/liveclip-stage18-l05` (branched from
  `origin/main` `701f540`, the merge of PR #1, whose tree equals `ef07143`);
  this docs commit follows. Not pushed. Routing policy
  `quality-gate-risk-routing-v9`, algorithm version `dual-profile-direct-v1`,
  cache-key schema, persisted schemas, Python behaviour, evaluator,
  thresholds, benchmark JSON/MD, short-profile file
  (`profiles/short_highlight.md`) and `tools/loop_engineering` are
  unchanged: `git diff --stat origin/main -- src ':!src/liveclip/clipping_skills'`
  is empty.
- **User decision (2026-11-06): "L05 only".** Narrow the Stage 17 rule so a
  brief, passing remark that a pen or marker has failed is not a
  `material_interruption`; genuine presentation troubleshooting stays
  `material_interruption` even when brief. This **partly re-widens the
  Stage 17 narrowed exemption** for presentation troubleshooting, by explicit
  user decision; the single-cue thanks, greeting or name exemption itself is
  unchanged. S03 is out of scope.
- **Root cause (independent read-only reviewer).** The Stage 17 clause
  (`2932b7c`) listed "presentation troubleshooting (waiting for a pen or
  colour, glare, asking whether viewers can see)" as `material_interruption`
  "even when brief", which overrode the threshold "only when it actually
  breaks the teaching or claim logic". In cold-33 and cold-34 every
  in-tolerance L05 row was blocked for `material_interruption` over a few
  seconds' pen-failure remark that the speaker passes over (cues 2337–2340).
  Reviewer analysis and offline replays (stored stage outputs with the flag
  released deterministically; an estimate, not real-model evidence):
  `/private/tmp/claude-501/-Users-junhuaxu-autoclip-claude/11442fc6-5e35-49d6-afb1-e25ebe8c47b5/scratchpad/stage18-analysis/` (`replay18*.txt`): releasing only the
  L05 rows would give cold-33 and cold-34 PASS 96.35 with mini 6/6, while also
  releasing the N07-overlapping mini rows (which contain a genuine
  pen-testing pause) would add `irrelevant_padding` and, in cold-34, a
  negative-anchor finding. Hence the carve-out is limited to a passing remark
  with no stop to wait for, test or replace the pen.
- **S03: deferred, measured only.** Reviewer root cause: the window-ownership
  edge, the shortest-complete prompts and Discovery variance (as recorded:
  cold-34 Discovery never proposed the full span and Global Review and Global
  Audit kept the shorter duplicate; cold-33 had an in-tolerance row rejected
  as a duplicate). No prompt or routing change for S03; each new run records
  the S03 outcome.
- (1) **Prompts (generic wording; no cue numbers, times, anchor IDs, digits
  or quoted transcript).** In every copy of the rule (`main.md`,
  `coverage_audit.md`, `risk_discovery.md`, `boundary_review.md`
  definition cross-reference and on-topic duration test, `global_review.md`,
  `global_audit.md`; `discovery.md`, `precision_audit.md`,
  `precision_confirmation.md`, `repair.md` and both Profile files carry no
  copy and are unchanged) the item list reads "presentation troubleshooting
  (stopping to wait for, test, request or change a pen or colour, fixing
  glare, or asking whether viewers can see)", followed by the identical
  carve-out: "A passing remark of a few seconds that a pen or marker has
  failed, when the speaker does not stop to wait for, test or replace it and
  goes straight on with the same point, is not a `material_interruption`;
  treat it as part of the lesson." `global_audit.md` previously named
  troubleshooting without the item list; it now carries the same list so
  every mirror is identical. Boundary Review's duration test still removes
  calls to action, platform prompts, chat reading and (genuine) presentation
  troubleshooting even when brief, and now keeps "such a passing pen or
  marker remark" in the lesson beside board-writing and the live-demo
  equipment remark. Unchanged: calls to action and platform prompts (fan
  badges, follows, likes, gifts, homepage plugs, microphone-join requests)
  and chat reading stay `material_interruption`; the single-cue thanks,
  greeting or name exemption; board-writing is part of the lesson.
- (2) **Stage 18b prompt-hash table** (all 17 identities from the repo's
  `load_dual_profile_prompt` / `load_dual_profile_variant_link_prompt` via
  `stage18-coder/prompt_hashes.py` on `origin/main` (= `50232af` prompts) and
  on the Stage 18 tree; the "before" column equals the Stage 17b table; JSON
  in `/private/tmp/claude-501/-Users-junhuaxu-autoclip-claude/11442fc6-5e35-49d6-afb1-e25ebe8c47b5/scratchpad/stage18-coder/`):

  | prompt identity | before (50232af, Stage 17b) | after (Stage 18) | changed |
  |---|---|---|---|
  | `short_highlight.discovery` | `2832239f9534ce78ed7dc19d99dae0d9044267dc20ad2e773372065cfbf3f802` | `c2d9dfc5d9602a6691a7dfdf249f4685ff84950968d6603061952570e70ca1e5` | yes |
  | `short_highlight.coverage_audit` | `834f4e170e3e99fe2f181d77f275915cb3e4839a3e65fd57a74be74e721dac31` | `b3237e3dcf88c17f85642127bb7711bbe6f376e1012d5e0d6eb5748df69c564a` | yes |
  | `short_highlight.precision_audit` | `80e8fc4c1c5705f9a8411ceb20dcd03cfe058dc7cef36260c4e0456d5a3be382` | `f955e61abaf482fd594cb875498524bf6ac4d078f3e13663a5378c2d1f47af78` | yes |
  | `short_highlight.precision_confirmation` | `be470cf717a5a815adcec65e3a9df5b6caf4af0464481a8eb930eb7c806218e2` | `0784d166170419526247b24427207457ce3b1903634f31482784dc6e7d2297fb` | yes |
  | `short_highlight.risk_discovery` | `8e03366fc65f11d93aa57c6c74eaddb815a1e81c4d5fec19e6a438a2ae6504ed` | `8315d03f096e04eae886cd73cf4d922cd886483e8d84e0d0d5b8450cd9797ccd` | yes |
  | `short_highlight.boundary_review` | `ec2f6175bd57e1eb252170c9168d78a8e55d06790e0443c2cc2404de0aca01c2` | `4c8621c0a77613b6070b3d2aabeaac11519dfbac0bb1e7d0a976eab370c9b939` | yes |
  | `short_highlight.global_review` | `a47b9e7124620763756b294cc3e05cbac3d85267a0e666b3ac1ab26eeb6aa646` | `89cd790f3860e8881fd6ded8c577979fb9698e8fc677c59e343a83b605961543` | yes |
  | `short_highlight.global_audit` | `5c35970f963583cb46ab3f8a5b52da9416ebc9c8d003a6a908a05e504b2400fc` | `070b605413e4caaa9ce1d74bd534eb61d36def4c7db9a453cd991a23c9243a54` | yes |
  | `mini_lesson.discovery` | `f29619ec3161e468cb5def022d568490a07cecba1ce774a3e3db849679af24ba` | `b93d1d564b1a675bc675f13859dd6a133288fae4bbba0c76434755cebd1c82f8` | yes |
  | `mini_lesson.coverage_audit` | `984cdbaf69b98630fbd88ec0c531f4cb19a62af0438877f51b9c4ba24d5153a1` | `80480fb064d1afe7dcc4ea9ade1b930e9c376d9b5d7f6b1057a9890827d07692` | yes |
  | `mini_lesson.precision_audit` | `941db84773ebc6a1bbd454e6d6c648de0fa66b0b28f83dccf4eab8da196a2870` | `0894b7d32611b30d4f344b1f435f2ec4021f27dd3859b1126036969bcaeaec11` | yes |
  | `mini_lesson.precision_confirmation` | `fd86951677ffa03a8e19fe2f2b16a2c3ea1051c2d4f6f4f971e3d4b390f3705b` | `e2350c1ec657bc1118e399bdf983c8cbe0e9e53d6e2384597daf5c15df58c642` | yes |
  | `mini_lesson.risk_discovery` | `76809629a4714f03ded6fda51d16b0f07db781256030fcc984a33585437ed7c4` | `dd5c1ef7bc839c613f5b5ccaca367a6eff3b9d4de5b7448fbfbf7f5d0cdf1182` | yes |
  | `mini_lesson.boundary_review` | `abb7f51674cdae7cdbc9f7471a7cdfefbe1c2c0a48099ccc80320368c8032d23` | `5907d96caaf97020891dddf9a017908caed3ec6eb2779f61ae8584bfcbef688c` | yes |
  | `mini_lesson.global_review` | `ea58c71b71b81d000f5df3ca31e718e1a5acef6a423ccbeeed780e6d456180e3` | `af68fc7c175ad07bd879fbc6576f0720c883c66e795229c958ff35f20c1097dd` | yes |
  | `mini_lesson.global_audit` | `092264576bfe411281b1d2f041e50ea0e0b758c9ca2acb71992dc875ab970d1f` | `bd7f9654717c8dcafc868f52767d8deebb765268153fd2b2fa7b9f120e522dc9` | yes |
  | `variant_link` | `def25b05bd987a293cf74d5f964ca00504d8d247cfd8b1d4af17299289152aef` | `def25b05bd987a293cf74d5f964ca00504d8d247cfd8b1d4af17299289152aef` | no |

  16 of 17 identities change (`main.md` is loaded by every stage except the
  variant link); the variant link is unchanged. The 13 pinned identities are
  re-pinned with a Stage 18 justification in
  `tests/integration/test_dual_profile_evaluation.py`
  (`FROZEN_DISCOVERY_PROMPT_HASHES`, `PINNED_REVIEW_PROMPT_HASHES`); the
  three short_highlight `precision_audit`, `precision_confirmation` and
  `risk_discovery` identities are not pinned (not executed), as before. The
  next real run has a cold cache for every stage except the variant link.
- (3) Tests (`test_dual_profile_flag_contract.py` 102 → 119, +17): the
  Stage 17/17b pins (`MI_THRESHOLD`, Boundary Review cross-reference and
  duration test, Global Review/Audit restatements) carry the new wording via
  shared constants `TROUBLESHOOTING_ITEMS` and `PEN_REMARK_CARVE_OUT`; new
  `test_a_passing_pen_remark_is_part_of_the_lesson_and_genuine_troubleshooting_stays_mi`
  (8 stages × 2 Profiles: per-stage own and inherited counts of the item list
  and the carve-out; the superseded "waiting for a pen or colour" wording
  absent; every "presentation troubleshooting" carries the item list except
  Boundary Review's one back-reference; genuine items, platform-prompt list,
  chat reading, single-cue and gift-thanks exemptions and board-writing
  present; Boundary Review's duration test still subtracts the genuine types;
  no digits or CJK in the rule text) and
  `test_every_mirror_of_the_troubleshooting_rule_is_identical` (reads every
  `*.md` of the `dual_profile_v1` tree, including Discovery, repair and the
  Profile files: every item list and carve-out is byte-identical after
  whitespace normalisation, the carrying file set is exactly the six files
  above, and neither Profile file mentions troubleshooting).
- (4) Mutation self-check (prompt files mutated in place, restored
  byte-for-byte, prompt hashes re-verified equal afterwards;
  `stage18-coder/mutate.py`, `mutation_results.txt`): 5 of 5 caught — M1
  `global_review` drops the carve-out (6 failures), M2 `coverage_audit`
  restores the old item list (8), M3 `risk_discovery` carve-out drifts to
  "several seconds" (8), M4 Boundary Review duration test drops the
  troubleshooting subtraction (7), M5 `main.md` drops the carve-out (31).
- (5) Replay sanity (deterministic; evaluator and routing untouched):
  `scripts/evaluate_benchmark.py` re-run on the stored cold-33 and cold-34
  `final-validated.json` and `run-manifest.json` into
  `stage18-coder/replay-cold-{33,34}/`: rc 0, PASS 92.5 each,
  `benchmark-result.json` and `benchmark-report.md` byte-identical to the
  stored strict-eval files. Nothing written under `data/`.
- Self-check: `make lint` rc 0; targeted pytest (`test_dual_profile.py`,
  flag contract, `test_dual_profile_evaluation.py`) 392 passed; every
  prompt-loading test file (20 files plus `test_dual_profile.py`) 1077
  passed; full backend pytest 3241 passed (3224 at Stage 17b plus 17 Stage 18 items). Deterministic validation only; no
  real model call, no render, no human review.
- **50232af acceptance stays the historical baseline.** cold-33 and cold-34
  (strict PASS 92.5 each, 2/2 on frozen `50232af`) remain valid evidence for
  that tree; they are not evidence for the Stage 18 tree.
- **Freeze broken.** Stage 18 changes prompt identities, so under the
  "Acceptance policy from Stage 17" the `50232af` freeze no longer covers
  HEAD and the consecutive count for the new tree is **0/2**. A new freeze SHA
  (candidate: the Stage 18 code commit `f525338ed9427b0fcac9925bac6075d60af13e69`, once the independent
  tester and reviewer accept it; accepted 2026-11-06, see the FREEZE
  section above) and **2 new consecutive fresh-cold strict
  PASSes** on it are required. The FROZEN definition, fresh-cold provenance,
  run environment and "what counts" rules are unchanged, except that (b)
  compares against the Stage 18b table above.
- **Per-run watch items (each new counted run records them; extended to
  the eight reviewer items in the FREEZE section above):** (1) the L05
  hit (status and `material_interruption` reasons of the in-tolerance L05
  rows); (2) the status and `material_interruption` reasons of the
  N07-overlapping mini rows, which contain a genuine pen-testing pause and
  must stay `blocked` or rejected (no `irrelevant_padding` or
  negative-anchor finding); (3) the composite rows (562000–847000 and
  1099200–1351000 must have no selected or `manual_review` mini output);
  (4) the L04 representative; (5) the S01 and S04 start/end offsets; plus the
  S03 outcome (measured only).
- Recovery: revert `f525338ed9427b0fcac9925bac6075d60af13e69` (and this docs commit); that restores the
  Stage 17b prompt hashes and the `50232af` frozen-path and prompt tree
  (every path in the freeze list, prompts included, equals `50232af`; docs
  differ), where the cold-33/34 acceptance applies. No routing, cache-key
  or schema impact. (Wording made precise at freeze acceptance, reviewer
  P2-5.)
- (Historical next step; done: tester and reviewer accepted, freeze SHA
  `f525338`, see the FREEZE section above.) **Next:** independent tester and reviewer on `f525338ed9427b0fcac9925bac6075d60af13e69`; on acceptance it
  becomes the new freeze SHA; then two consecutive fresh-cold strict PASS
  runs on it with the watch items above. Human editorial/audio review of
  earlier renders and the L07 listening check stay pending (separate
  evidence category). Push and merge still need explicit consent.

## cold-34 real run on frozen 50232af (2026-11-05) — strict PASS 92.5 (fresh cold; consecutive cold strict PASS 2/2; benchmark v1 strict acceptance satisfied)

- **Counted run 2 of 2** under the "Acceptance policy from Stage 17" (as
  corrected at freeze acceptance). Fresh cold, real Claude CLI, single
  segment. HEAD at run time `a8ab7cd` (three docs-only commits `c5e9f96`,
  `feef1e5`, `a8ab7cd` on top of the freeze SHA); freeze-diff to
  `50232af0cb0b0194fb663528b569998a8a2fd79b` (including `.gitignore`) rc 0 with empty
  porcelain before and after the run. Eval rc 0, wall 7170 s (2026-11-05
  07:25:56 to 09:25:26 local); 0 sleep/wake events in the window; AC power
  throughout.
- Roots
  `data/evaluations/dual-profile-{benchmark,cache,strict-eval}-20261105-claude-cold-34`
  (the strict-eval root holds `benchmark-result.json`,
  `benchmark-report.md` and `evidence/`).
- Strict **PASS 92.5**: both_profiles 15, short 17.5, mini 25, boundary 15,
  risk 10, audit 10. No hard failure, PASS blocker, direct-fail condition,
  forbidden-composite, padding, negative-anchor, duration or regression
  finding; `source_hash_matches` true. Short 7/8 (S03 missed). Mini 5/6
  (L01, L02, L03, L04 exact at 0/0 ms; L07 0/+1980 ms; L05 (P1) missed).
  R01 blocked and R02 `manual_review`, both routed correctly. N07, N08 and
  the composites 562000–847000 and 1099200–1351000 have no selected or
  `manual_review` mini output.
- Provenance (meets the fresh-cold definition): run-manifest `cache_hits`
  0; run and cache roots did not exist at attempt start; 268 cache files,
  every mtime after the attempt start; 0 content-identical files in 29
  other cache roots (informational only). Every cached `prompt_hash` equals
  the Stage 17b table (0 mismatches); stale-cache refresh off.
- Provider: 272 provider records (run-manifest calls: Discovery 161,
  Boundary Review 78, Global Review/Audit 28, variant link 1, plus 4
  repair records), all succeeded on the first attempt; 4 successful
  repairs (2 Discovery, 2 Boundary Review; cold-33 had 0), 0 retries, no
  usage-limit marker. Tokens in 10,475,368 / out 1,939,183.
- **Run fingerprint identical to cold-33:** Claude CLI 2.1.308, sha256
  `ca923c86ac84b30574a82331a05b6e066c27477a926ceaffe46a845a33e4dd37`; model `claude-opus-5-5`; algorithm
  `dual-profile-direct-v1`; routing `quality-gate-risk-routing-v9`;
  Settings fingerprint sha256
  `c81f0ece91debb4f1637ba5eecc3af64a91da256f586917408de458317d170d1`; run fingerprint
  sha256 `04f5de6e76150fd763c5669be38aed69a32376097e5c2f874c902f89052b9cc5`. The run manifest, and therefore the
  run fingerprint, carries the 14 executed-stage prompt hashes
  (short_highlight `precision_audit`, `precision_confirmation` and
  `risk_discovery` are not executed); all 14 equal Stage 17b. Separately,
  all 17 prompt identities recomputed from the tree equal the Stage 17b
  table (`evidence/step0-tree-prompt-hashes.txt`). No `LIVECLIP_CLAUDE_*`
  override in `.env` (absent) or `.env.local` (key names only recorded).
- Miss observations (no patch, per the acceptance policy; recorded as
  known residual fragility for future work, not as a defect requiring
  action now): (1) **S03**: Discovery never proposed the full 470–506 cue
  span, and Global Review and Global Audit kept the 476–499 duplicate; this
  differs from the cold-33 mechanism, where an in-tolerance row existed but
  was rejected as a duplicate. S03 has missed in every cold run since
  cold-30. (2) **L05**: all in-tolerance rows were blocked for
  `material_interruption` over the pen-failure remark at cues 2337–2340,
  the same as cold-33.
- Diagnostics: Discovery `material_interruption` flags mini 92 / short 51
  (cold-33: 102/59).
- Renders: 12 clips (7 short, 5 mini), rc 0, automatic checks pass. Visual
  and audio review pending.
- **Consecutive cold strict PASS count: 2/2 (cold-33, cold-34).** The
  dual-profile benchmark v1 acceptance policy (2 consecutive fresh-cold
  strict PASSes on the frozen tree `50232af`) is satisfied; **strict
  benchmark acceptance is complete.**
- Evaluator imports (informational): `scripts/evaluate_benchmark.py` and
  the benchmark JSON/MD are unchanged since `2c4de9a` and byte-identical at
  `194ba65..HEAD`; the evaluator imports schema classes from
  `src/liveclip/pipeline/dual_profile.py`, which changed between `194ba65`
  and `50232af` only additively (routing literals v5–v9, diagnostic fields,
  stricter manifest cross-checks; no threshold changed), and the reviewer's
  re-evaluation of cold-33 and cold-34 is byte-identical to the stored
  results.
- Still pending, each a separate evidence category that strict PASS does
  not claim: (1) human editorial/audio review of the renders of
  cold-27 r2, warm-28, warm-29b, cold-30, cold-31, cold-32b, cold-33 and cold-34; it also covers the
  evaluator's `human_required` check
  `title_hook_summary_must_be_source_faithful`, which lists 68 candidate
  IDs for cold-33 and 64 for cold-34 (exactly the `manual_review` rows of
  both profiles). Both runs auto-select 0 candidates in both profiles, so
  every short and mini match is `manual_review` (R01 is `blocked`);
  (2) the L07 listening check
  of `input/8-30.ts` 1:40:07–1:40:35. Nothing is pushed or merged to
  `main`; that requires explicit user consent.
- Recovery: docs-only; reverting this commit removes only this record (the
  documented count returns to 1/2). No code, prompt, routing, algorithm or
  benchmark change; the freeze is unaffected.
- (Historical next step for the `50232af` tree; L05 is addressed by Stage 18
  above by user decision, S03 stays measured only, and the human review and
  L07 check stay pending.) **Next:** human editorial/audio review of the renders listed above and
  the L07 listening check (user); push/merge only with explicit consent.
  The S03 and L05 residual fragility stays recorded for future work.

## cold-33 real run on frozen 50232af (2026-11-05) — strict PASS 92.5 (fresh cold; consecutive cold strict PASS 1/2)

- **Counted run 1 of 2** under the "Acceptance policy from Stage 17" (as
  corrected at freeze acceptance). Fresh cold, real Claude CLI, single
  segment. HEAD at run time `feef1e5` (docs-only on top of the freeze SHA);
  freeze-diff to `50232af0cb0b0194fb663528b569998a8a2fd79b` (including `.gitignore`) rc 0 with empty
  porcelain before and after the run. Eval rc 0, wall 7479 s (2026-11-05
  05:08:29 to 07:13:08 local; attempt start 05:08:25); 0 sleep/wake events
  in the window; AC power throughout.
- Roots
  `data/evaluations/dual-profile-{benchmark,cache,strict-eval}-20261105-claude-cold-33`
  (the strict-eval root holds `benchmark-result.json`,
  `benchmark-report.md` and `evidence/`).
- Strict **PASS 92.5**: both_profiles 15, short 17.5, mini 25, boundary 15,
  risk 10, audit 10. No hard failure, PASS blocker, forbidden-composite,
  padding or negative-anchor finding; `source_hash_matches` true. Short 7/8
  (S03 missed). Mini 5/6 (L01, L02, L03, L04, L07 hit; L05 (P1) missed).
  R01 blocked and R02 `manual_review`, both routed correctly. N07, N08 and
  the composites 562000–847000 and 1099200–1351000 have no selected or
  `manual_review` mini output; the composite that failed cold-32b is clean.
- Provenance (meets the fresh-cold definition): run-manifest `cache_hits`
  0; run and cache roots did not exist at attempt start; 272 cache files,
  every mtime after the attempt start; 0 content-identical files in 28
  other cache roots (informational only). Every cached `prompt_hash` equals
  the Stage 17b table (0 mismatches); stale-cache refresh off.
- Provider: 272 provider records (run-manifest calls: Discovery 161,
  Boundary Review 80, Global Review/Audit 30, variant link 1), all
  succeeded on the first attempt; 0
  repairs, 0 retries, no usage-limit marker. Tokens in 10,677,798 / out
  2,011,664.
- **Run fingerprint (cold-34 must match):** Claude CLI 2.1.308, sha256
  `ca923c86ac84b30574a82331a05b6e066c27477a926ceaffe46a845a33e4dd37`; model `claude-opus-5-5`; algorithm
  `dual-profile-direct-v1`; routing `quality-gate-risk-routing-v9`;
  Settings fingerprint sha256
  `c81f0ece91debb4f1637ba5eecc3af64a91da256f586917408de458317d170d1`; run fingerprint
  (provider, model, prompt hashes, routing, algorithm) sha256
  `04f5de6e76150fd763c5669be38aed69a32376097e5c2f874c902f89052b9cc5`. No `LIVECLIP_CLAUDE_*` override in
  `.env` (absent) or `.env.local` (key names only recorded).
- Miss diagnostics (observations only; per the acceptance policy no patch
  follows a PASS run): (1) **S03**: the in-tolerance audit row was rejected
  by Global Review and Global Audit as a duplicate of
  `sh_0005_yawn_compare_with_choice`, whose start is +12440 ms (outside
  tolerance); the same miss as cold-30, cold-31 and cold-32b. (2) **L05**:
  all three in-tolerance rows were blocked for `material_interruption` over
  the suspected pen-failure remark at cues 2337–2340; cold-32b hit L05, so
  this is new run-to-run fragility.
- Renders: 12 clips, rc 0, automatic checks pass. Human editorial/audio
  review pending (separate evidence category, not part of strict PASS).
- **Consecutive cold strict PASS count: 1/2.**
- Recovery: docs-only; reverting this commit removes only this record. No
  code, prompt, routing, algorithm or benchmark change; the freeze is
  unaffected.
- (Historical next step; done: cold-34 strict PASS 92.5, count 2/2, see
  the cold-34 section above.) **Next: cold-34** (consecutive run 2 of 2) on the same frozen tree with
  the same fingerprint as above; a cold-Nb continuation counts as one run.
  Pre-run checks as for cold-33. Human review of the cold-27 through
  cold-33 renders stays pending. Push and merge still need explicit consent.

## FREEZE ACCEPTED at 50232af (Stage 16b + Stage 17 + Stage 17b) (2026-11-05) — consecutive cold strict PASS 0/2

- **Freeze SHA `50232af0cb0b0194fb663528b569998a8a2fd79b`** (Stage 17b code commit; it
  contains Stage 16b `b5d8def` and Stage 17 `2932b7c`). On
  `claude/liveclip-stage8-routing`; not pushed or merged to `main`. Frozen
  paths and run conditions: "Acceptance policy from Stage 17" below, as
  corrected here.
- **Tester:** independent tester at `c5e9f96` (freeze-diff to `50232af` empty): `make
  lint` rc 0; backend pytest 3224 passed; vitest 80 passed; e2e 4/4;
  concurrency 5/5; media-process 3/3; freeze-diff rc 0; `caffeinate` held
  for the full suite (a 40 s maintenance sleep occurred only during lint,
  not under `caffeinate`). Deterministic validation only; no real model call.
- **Reviewer:** independent reviewer: Stage 17 ACCEPT with nits (13/13 mutations caught,
  replay identical); Stage 17b ACCEPT with nits; FREEZE-READY yes (8/8
  prompt mutations caught; the 17 prompt hashes computed from the tree
  equal the `STATUS.md` table and the test pins; six-run replay
  byte-identical). Nits: P2 provenance criterion; P3 run-environment
  pinning and `.gitignore`; two P3 prompt-wording notes left unchanged by
  decision. All recorded here; no code or prompt change.
- **Fresh cold (precise; Stage 17b, provenance criterion corrected at
  freeze acceptance, reviewer P2).** A fresh run's run manifest records
  `cache_hits == 0`, its cache root did not exist or was empty at run
  start, and every cache file in that root has an mtime at or after the
  run's attempt start. A continuation segment (cold-Nb) may copy only the
  cache of the immediately previous segment of the same run (cold-N for
  cold-Nb, cold-Nb for cold-Nc); its run manifest records `cache_hits`
  equal to the number of entries copied from that segment, every carried
  file is byte-identical to that segment's file, and every new file has an
  mtime at or after the segment start. Content identity against other
  cache roots is reported for information only: identical model outputs
  under identical frozen prompts legitimately produce identical cache
  files, so it is not a pass/fail criterion. A warm run, or a run seeded
  from any other root, is a diagnostic, never acceptance evidence.
  (History: the Stage 17b wording also required 0 cache files
  content-identical to a file in any earlier cache root; the freeze
  reviewer's P2 showed that two honest runs on the same frozen prompts may
  produce identical files, so that clause was replaced before any counted
  run.)
- **Run environment (freeze reviewer P3).** The two counted runs must
  have equal run-manifest `provider`, `model`, `prompt_hashes`, routing
  policy (as final-validated) and algorithm version; the same pinned
  Claude CLI binary (`.cache/claude-cli/2.1.308/claude`, sha256
  `ca923c86ac84b30574a82331a05b6e066c27477a926ceaffe46a845a33e4dd37`,
  `--version` 2.1.308); and the same effective Settings, with no `.env`
  or `.env.local` override of the `LIVECLIP_CLAUDE_*` model, timeout or
  attempt settings. Each run records `ls -la .env .env.local` presence
  and, for a present file, only the names of its `LIVECLIP_` keys, never
  values. Check at this docs commit (2026-11-05): `.env` absent;
  `.env.local` present and ignored (`.gitignore` `.env.*`), with no
  `LIVECLIP_CLAUDE_*` and no `LIVECLIP_STRUCTURED_PROVIDER` key; the CLI
  binary's recomputed sha256 equals the pin and its mode is 0555.
- **`.gitignore` added to the freeze path list** (it decides which local files
  are ignored, for example `.env.*` and `.cache/`); it is unchanged between
  `50232af` and this commit.
- **Accepted residuals (freeze reviewer P3, unchanged by decision).**
  (1) The duration-minimum sentences in `main.md` line 8 ("Do not use
  greetings, thanks, likes/follows, ... to meet a duration minimum") and
  `global_review.md` ("The Profile minimum must be met by on-topic
  content, not by chat, calls to action, greetings or device talk") do not
  restate the single-cue exemption. (2) The `global_audit.md` exemption
  reads "passes over" without "without leaving the topic", unlike the
  other five statements. Both are left as they are because any prompt edit
  changes prompt identities and starts a new freeze; they are recorded for
  a future prompt revision.
- **Consecutive cold strict PASS count: 0/2.**
- Recovery: docs-only; reverting this commit restores the Stage 17b wording.
  No code, prompt, routing, algorithm or benchmark change; the freeze is
  unaffected.
- (Historical next step; done: cold-33 strict PASS 92.5, count 1/2, see
  the cold-33 section above.) **Next: cold-33**, the first counted fresh cold run, at the frozen tree.
  Pre-run: freeze-diff (including `.gitignore`) rc 0 with empty porcelain;
  new empty cache root; CLI sha256 and version; `.env`/`.env.local`
  presence and `LIVECLIP_` key names. Human review of the cold-27 through
  cold-32b renders stays pending (separate evidence category). Push and
  merge still need explicit consent.

## Stage 17b: Stage 17 reviewer nits (gift wording, freeze definitions) (2026-11-05) — ACCEPTED at 50232af (FREEZE SHA; was implemented, pending verification)

- **Status: implemented, pending independent tester and reviewer.** Prompts
  and tests in `50232af0cb0b0194fb663528b569998a8a2fd79b` on `claude/liveclip-stage8-routing`; this docs
  commit follows. Not pushed or merged to `main`. Routing policy
  `quality-gate-risk-routing-v9`, algorithm version `dual-profile-direct-v1`,
  cache-key schema, persisted schemas, Python behaviour, evaluator,
  thresholds, benchmark JSON/MD and `tools/loop_engineering` are unchanged.
  Once the tester and reviewer accept, `50232af0cb0b0194fb663528b569998a8a2fd79b` is the **freeze SHA**
  (definitions in "Acceptance policy from Stage 17" below). (Later,
  2026-11-05: tester and reviewer accepted; freeze SHA; see the FREEZE
  section above.)
- **Stage 17 reviewer verdict: ACCEPT with nits** on the Stage 16b + Stage 17
  candidate at `66b7555` (code `b5d8def`, `2932b7c`): no P0/P1. Reviewer
  mutations (scratch copies only; results in
  `/private/tmp/claude-501/-Users-junhuaxu-autoclip-claude/11442fc6-5e35-49d6-afb1-e25ebe8c47b5/scratchpad/stage17-review/mut_results.txt`):
  every recorded mutation caught, 13 of 13: Stage 16b A1 regeneration-phase
  mislabel (the R7 survivor of the Stage 16 review, now caught), A2 timing
  pass-through dropped, A3 backstop stores the message, A4 Darwin wall
  clock, A5 unbounded evidence path, A6 cancelled message dropped, A7
  aggregate drops timing; Stage 17 B1 one attested fact dropped, B2 release
  only on an unchanged interval, B3 release ignoring the raw flag on the
  shrink path, B4 audit payload on raw flags and B4' audit payload on the v8
  rule, B5 rejected duplicates not twin sources (P-b'). The reviewer's
  independent six-run replay (`stage17-review/replay_v9.json`) equals the
  Stage 17 replay table. Nits: P2 "gifts" listed as a platform prompt that
  is `material_interruption` even when brief, conflicting with the
  single-cue thanks exemption for a one-cue thanks for a gift; P3
  `risk_discovery`'s "a brief greeting or audience acknowledgement"; P3
  Boundary Review's duration test did not say that board-writing and the
  live-demo microphone remark are part of the lesson; P3 the freeze and
  "fresh cold" definitions were imprecise. All fixed here.
- (1) **Prompts (generic wording; no cue numbers, times, anchor IDs or quoted
  transcript).** In all five places that list platform prompts (`main.md`,
  `coverage_audit.md`, `risk_discovery.md`, `boundary_review.md`,
  `global_review.md`) the list now reads "(requests for fan badges, follows,
  likes or gifts, homepage plugs, requests for viewers to join on
  microphone)": a gift or follow is a prompt only when the speaker asks for
  it. Every exemption statement adds "including a single-cue thanks for a
  gift or follow" (`main.md`, mirrored verbatim in `coverage_audit.md` and
  `risk_discovery.md`; `boundary_review.md` definition and duration test;
  `global_review.md`; `global_audit.md`). Boundary Review's cross-reference
  now reads "the single-cue exemption above covers a single-cue thanks for a
  gift or follow but never these requests, chat reading or
  troubleshooting" (was "never covers them"). `risk_discovery.md`'s
  rhetorical-question paragraph uses the single-cue wording ("a single-cue
  audience thanks, greeting or name call-out that the speaker passes over";
  "the intervening cue"). Boundary Review's duration test adds "Writing the
  taught term on the board and the speaker's brief equipment or listening
  explanation attached to an immediate live example are part of the lesson
  and are not removed in this test." Lines re-wrapped at the usual width.
- (2) Hash table (all 17 identities; `prompt_hashes.py` on `git archive
  66b7555` and on the Stage 17b tree; the "before" column equals the Stage
  17 table; script and JSON in
  `/private/tmp/claude-501/-Users-junhuaxu-autoclip-claude/11442fc6-5e35-49d6-afb1-e25ebe8c47b5/scratchpad/stage17b/`):

  | prompt identity | before (66b7555, Stage 17) | after (Stage 17b) | changed |
  |---|---|---|---|
  | `short_highlight.discovery` | `ff8aeed5916548aa8e34b4183e0b1e1302dc9e31afc78f50518991593c6a6ab5` | `2832239f9534ce78ed7dc19d99dae0d9044267dc20ad2e773372065cfbf3f802` | yes |
  | `short_highlight.coverage_audit` | `0e6927b50f086f190c31ec57d2c58fc6763bef4e34f72d614db566e12cc2aa29` | `834f4e170e3e99fe2f181d77f275915cb3e4839a3e65fd57a74be74e721dac31` | yes |
  | `short_highlight.precision_audit` | `3c8bcd41051aafcd4e9cb87037937e045ae9457e5cbbdaeb9805d5d73f0d25d8` | `80e8fc4c1c5705f9a8411ceb20dcd03cfe058dc7cef36260c4e0456d5a3be382` | yes |
  | `short_highlight.precision_confirmation` | `3d39dd7d0e8fde23c7b2f54998c4f59a7fe1c09ed79e859c54dd79edb0771b1e` | `be470cf717a5a815adcec65e3a9df5b6caf4af0464481a8eb930eb7c806218e2` | yes |
  | `short_highlight.risk_discovery` | `a335cc1532f8fbab3ef15b2eb9d8a80462cdac97d2cbabcdcbf4cc1a51266d2c` | `8e03366fc65f11d93aa57c6c74eaddb815a1e81c4d5fec19e6a438a2ae6504ed` | yes |
  | `short_highlight.boundary_review` | `622d230f0290c8526181e3b36f55730a3e6b190b7efa977a6dbdd9941216d9e5` | `ec2f6175bd57e1eb252170c9168d78a8e55d06790e0443c2cc2404de0aca01c2` | yes |
  | `short_highlight.global_review` | `f9477baa0e5dd267e091b51e6b3c42276e92bd1a4b40d3549f16e2d29b86d39b` | `a47b9e7124620763756b294cc3e05cbac3d85267a0e666b3ac1ab26eeb6aa646` | yes |
  | `short_highlight.global_audit` | `a4ff7d01d8f84b4d5cb6ab94c4acb8730d69cacbdba7cb4960c9479af4f896ed` | `5c35970f963583cb46ab3f8a5b52da9416ebc9c8d003a6a908a05e504b2400fc` | yes |
  | `mini_lesson.discovery` | `03010be4c3baa706fbb77f7590d5ca4a91b53de0c42c8138e7e6a8085ecb8666` | `f29619ec3161e468cb5def022d568490a07cecba1ce774a3e3db849679af24ba` | yes |
  | `mini_lesson.coverage_audit` | `b5dc773e58cbd24a1dd8498f0be3867880e24944e00ce7944c57aff644452eb2` | `984cdbaf69b98630fbd88ec0c531f4cb19a62af0438877f51b9c4ba24d5153a1` | yes |
  | `mini_lesson.precision_audit` | `286795bb1d3f5bc8a72ddce67c81ee4eab1d7548198ef93a0063c2b5ab8716d7` | `941db84773ebc6a1bbd454e6d6c648de0fa66b0b28f83dccf4eab8da196a2870` | yes |
  | `mini_lesson.precision_confirmation` | `1a4959e0a4b130282c79c0743c7fdf3dd151a253cdc67dd99313e5ce2fa82ef3` | `fd86951677ffa03a8e19fe2f2b16a2c3ea1051c2d4f6f4f971e3d4b390f3705b` | yes |
  | `mini_lesson.risk_discovery` | `2a3e44f2a63dcb10f395434b18014ee0b012586aeee695b827685648d8a3a4ba` | `76809629a4714f03ded6fda51d16b0f07db781256030fcc984a33585437ed7c4` | yes |
  | `mini_lesson.boundary_review` | `63f525607cad124aaf0002fe89476bdcbbfa565b94b454da9f3142eb8ae2aa5f` | `abb7f51674cdae7cdbc9f7471a7cdfefbe1c2c0a48099ccc80320368c8032d23` | yes |
  | `mini_lesson.global_review` | `857eb960f1c4a40aefbf2c4d43b9d9c778dc62d19d50729a5489f4241bef284a` | `ea58c71b71b81d000f5df3ca31e718e1a5acef6a423ccbeeed780e6d456180e3` | yes |
  | `mini_lesson.global_audit` | `a9d42e17e6fb374595a3eec64db9041caf358cb4cdb55a397f1fddc02b29c08f` | `092264576bfe411281b1d2f041e50ea0e0b758c9ca2acb71992dc875ab970d1f` | yes |
  | `variant_link` | `def25b05bd987a293cf74d5f964ca00504d8d247cfd8b1d4af17299289152aef` | `def25b05bd987a293cf74d5f964ca00504d8d247cfd8b1d4af17299289152aef` | no |

  16 of 17 identities change (`main.md` is loaded by every stage except the
  variant link); the variant link is unchanged. Pins re-pinned with a Stage
  17b justification in `tests/integration/test_dual_profile_evaluation.py`
  (`FROZEN_DISCOVERY_PROMPT_HASHES`, `PINNED_REVIEW_PROMPT_HASHES`). The next
  real run has a cold cache for every stage except the variant link.
- (3) Tests (`test_dual_profile_flag_contract.py` 86 → 102, +16): the Stage
  17 pins (`MI_THRESHOLD`, Boundary Review definition, cross-reference and
  duration test, Global Review/Audit restatements) carry the new wording;
  new `test_gifts_are_prompts_only_when_requested_and_a_gift_thanks_stays_exempt`
  across all 8 stages × 2 Profiles: the superseded Stage 17 patterns
  (`STAGE17B_SUPERSEDED`: the bare "gifts" list, "never covers them", "a
  brief greeting or audience acknowledgement", "the intervening greeting"
  and the exemption sentences without the gift thanks) are absent; the
  requests list and the gift-thanks exemption are present; every "gift(s)"
  in the prompt lies inside one of those two phrases; per-stage counts of
  both phrases in the stage's own text; no digits or CJK in either phrase.
- Self-check: `make lint` rc 0; targeted pytest (11 dual-profile, prompt
  and structured-provider files) 677 passed; full backend pytest
  3224 passed (3208 at Stage 17 plus 16 Stage 17b items). Six-run offline replay re-run against the Stage 17b tree
  (`stage17-sim/replay_v9.py`, output
  `stage17b/replay_v9.txt` / `replay_v9.json`): byte-identical table and
  JSON to Stage 17 (routing unchanged; stored outputs do not depend on
  prompt text). Deterministic validation only; no real model call.
- Recovery: revert `50232af0cb0b0194fb663528b569998a8a2fd79b` (and this docs commit); restores the
  Stage 17 prompt hashes. No routing, cache-key or schema impact.

## Stage 17: routing v9 ending-edge release and narrowed interruption exemption (2026-11-05) — REVIEWER ACCEPT WITH NITS at 66b7555; nits → Stage 17b; ACCEPTED with 17b at 50232af (freeze)

- **Reviewer ACCEPT with nits** at `66b7555` (no P0/P1; details and nits in
  Stage 17b above). The bullets below are the historical implementation
  record; Stage 17b supersedes the platform-prompt list (gifts only as
  requests) and adds the single-cue gift or follow thanks to the exemption.
- **Status (historical): implemented, pending independent tester and reviewer** (to be
  verified together with Stage 16b). Code, prompts and tests in
  `2932b7c15af600a900a8838deed4cfcf08a9c95b` on `claude/liveclip-stage8-routing`; this docs commit
  follows. Not pushed or merged to `main`. Routing policy
  `quality-gate-risk-routing-v9` (v1–v8 and unmarked artifacts still load).
  Unchanged: algorithm version `dual-profile-direct-v1`, cache-key schema,
  persisted semantic-outcome schema, evaluator, thresholds, benchmark JSON/MD
  and `tools/loop_engineering`. Every Discovery and review prompt hash
  changes (16 of 17; table below), so the next real run has a cold cache for
  every stage except the variant link.
- User decisions (2026-11-05): (1) **"Both" fixes**: routing policy P-a
  (Discovery `topic_not_closed` persistence released by an attesting
  Boundary Review) and the prompt narrowing of the Stage 15 exemption.
  Optional P-b' (a rejected duplicate is not a source of flags it carries
  only through persistence) was **not approved**; the twin union is
  unchanged. (2) Acceptance **"Freeze, 2 cold PASS in a row"** (policy
  below).

### cold-32b analysis (independent read-only reviewer, 2026-11-05)

Evidence and scripts:
`/private/tmp/claude-501/-Users-junhuaxu-autoclip-claude/11442fc6-5e35-49d6-afb1-e25ebe8c47b5/scratchpad/cold32b-analysis/ANALYSIS.txt`
(replays use `git archive b758f71`, the real `assemble_final_profile_result`
and the real evaluator; the v8 replay of cold-32b reproduces its stored final
result exactly; no model call, nothing written under `data/`).

- **L02 = a deterministic rule contradiction.** The base candidate's
  Discovery raised `topic_not_closed` with a scope claim (the curriculum
  continues with later steps), not a claim that the interval's own ending
  fails to close. Boundary Review kept the interval unchanged, attested
  opening, ending, central objective and shortest boundary all true and
  cleared the flag. Routing v5–v8 persists a structural Discovery flag unless
  Boundary Review shrinks an edge, so the flag survived. The Global Audit,
  told never to choose a persisted-flag row as representative, rejected the
  base as a duplicate of its clean same-interval risk-discovery twin; the v6
  twin union (non-risk rows are sources whatever their status) then gave that
  twin the very flag the audit avoided, and the quality gate blocked it. For
  identical intervals the audit rule could never succeed. Boundary Review
  judged that interval closed in every earlier run; Discovery had never
  flagged the base before. `missing_required_prior_steps` is advisory, never
  persisted or gated.
- **Forbidden composite = the Stage 15 exemption read too broadly (n = 1,
  "made more likely", not proven).** Three base mini rows inside the
  forbidden composite range (all flags empty at Boundary and Global Review,
  all four facts true, final `manual_review`) contained interior calls to
  action and platform prompts, chat reading and presentation
  troubleshooting. Their Boundary Review reasons invoked the Stage 15 text
  ("a brief audience thanks, greeting, name call-out or acknowledgement that
  the speaker passes over ... is neither an interruption nor padding"). In the
  five earlier runs the same intervals were blocked by the reviews' own
  padding/interruption flags (routing never had to act); inside cold-32b two
  sibling rows kept `material_interruption` for the same material. A
  "strings of short demonstrations are composites" rule was rejected because
  two of the three P0 mini golds are such chains; the generic signal is the
  interior non-teaching material.
- Failure-mode table (stored as-run):

  | run | hard failure | model event | deterministic amplifier | class |
  |---|---|---|---|---|
  | warm-28 | negative anchor N07 | Boundary + Global Review missed a topic switch on a short row (Discovery right) | v3 had no persistence | policy gap (fixed v4) |
  | warm-28 | irrelevant padding (N07) | Boundary Review trimmed a mini core insufficiently | none | model variance |
  | cold-30 | P0 L01 | Discovery device-padding false positive on the only exact row | v4 padding persistence + audit "match" policy | policy (fixed v5) |
  | cold-31 | P0 L02 | risk Discovery `material_interruption` on a one-cue thanks | union from the risk record | policy (fixed v6) + prompt |
  | cold-32b | P0 L02 | base Discovery `topic_not_closed` false positive (scope claim) | v5 persistence + audit representative rule + union | policy (P-a, Stage 17) |
  | cold-32b | forbidden composite | Boundary/Global Review exempted CTA and troubleshooting (3 rows) | none | model / prompt regression (Stage 17 prompt) |

  Other misses (not hard failures): S03 3/6 and L07 3/6 runs, representative
  choice (model variance).
- Fragility estimate: on 119 gold-exact rows Discovery raised a gated flag on
  11 (9.2 %), Boundary Review on 1, Global Review on 2. With about 1.5–2 exact
  rows per P0, a single structural Discovery vote decides an interval often
  enough for about 13–17 % loss per P0 per run and about 35–45 % for "at
  least one of three P0 lost"; observed 3 of 6 runs. Each single-cause fix
  closed the last path and the next run found a new one (v4 → v5 → v6 →
  Stage 15 prompt → composite): the structure is "any one of K judgments
  vetoes". Hence the freeze-and-repeat acceptance policy below rather than
  another patch per failed run. Reviewer longer-term options (targeted second
  opinion, cue-localised flags) are recorded, not approved.

### Stage 17 implementation

- (1) **Routing v9 (P-a)**, inside the single helper
  `discovery_persisted_flags` (`src/liveclip/pipeline/dual_profile.py`):
  when Boundary Review did not shrink the interval, a Discovery
  `topic_not_closed` (new constant `ENDING_EDGE_STRUCTURAL_FLAGS`) is not
  persisted if Boundary Review's own item does not carry it and
  `boundary_attests_complete_unit` holds (`opening_complete`,
  `ending_complete`, `central_objective_complete` and
  `shortest_complete_boundary` all true). `material_interruption`,
  `topic_switch_inside` and `asr_uncertain_blocks_meaning` keep v5
  persistence (released only by a shrink). Because final assembly, the
  Global Audit payload (`persisted_discovery_gated_flags`), the
  persisted-flag representative validator, the near-identical pair fallback
  keep order and the `persisted_flag_representative_duplicates` manifest
  diagnostic all call this helper, they stay consistent. The twin union
  (`same_interval_twin_flags`) is unchanged. A Global Review that re-adds
  `topic_not_closed` still gates through the merged flags.
- (2) **Prompts (generic wording; no cue numbers, times, anchor IDs or quoted
  transcript).** `main.md`: the only exemption is a single-cue audience
  thanks, greeting or name call-out that the speaker passes over without
  leaving the topic; inside the interval, calls to action and platform
  prompts (fan badges, follows, likes, homepage plugs, gifts, requests for
  viewers to join on microphone), chat reading and presentation
  troubleshooting (waiting for a pen or colour, glare, asking whether viewers
  can see) are `material_interruption` even when brief, like audibility
  checks, and are subtracted when testing the Profile duration minimum;
  writing the taught term on the board is part of the lesson; the Stage 14
  live-demo microphone sentence is unchanged. Mirrored verbatim in
  `coverage_audit.md` and `risk_discovery.md`; `boundary_review.md` mirrors it
  in its `material_interruption` definition, its interior cross-reference
  ("the single-cue exemption above never covers them") and its on-topic
  duration test (calls to action, platform prompts, chat reading and
  presentation troubleshooting are removed in it even when brief; the closing
  acknowledgement edge rule is unchanged); `global_review.md` and
  `global_audit.md` restate it beside the interior audibility rule.
  `global_review.md` also states the v9 release (Boundary Review resolves a
  Discovery `topic_not_closed` without trimming when its own item clears the
  flag and attests a complete opening, ending, central objective and
  shortest boundary), so its persistence description stays true.
  `precision_audit.md` already defers to the main-contract threshold and is
  unchanged (its hash changes through `main.md`). Stage 14 padding-edge rules
  and the Stage 15 self-promotion rule are unchanged (their contract tests
  still pass).
- (3) Hash table (all 17 identities; printed by
  `/private/tmp/claude-501/-Users-junhuaxu-autoclip-claude/11442fc6-5e35-49d6-afb1-e25ebe8c47b5/scratchpad/stage17-sim/hash_table.py`
  from `prompt_hashes.py` run on `git archive 03ec7ef` and on the Stage 17
  tree; the "before" column equals the Stage 16b table):

  | prompt identity | before (03ec7ef, Stage 16b) | after (Stage 17) | changed |
  |---|---|---|---|
  | `short_highlight.discovery` | `42f26c40658f26efa7efdc51bbca2b9ae7c82d7e2c6665cf1abd9a80f5cc1ed1` | `ff8aeed5916548aa8e34b4183e0b1e1302dc9e31afc78f50518991593c6a6ab5` | yes |
  | `short_highlight.coverage_audit` | `d59f993675d587ac81b902ea0db24a70877dc49048382a4296485ff58fb279a4` | `0e6927b50f086f190c31ec57d2c58fc6763bef4e34f72d614db566e12cc2aa29` | yes |
  | `short_highlight.precision_audit` | `5c7445188cbe9d52a52ff50d3c480d8fd45f2ddee0177f7ab0841ae7660e52fa` | `3c8bcd41051aafcd4e9cb87037937e045ae9457e5cbbdaeb9805d5d73f0d25d8` | yes |
  | `short_highlight.precision_confirmation` | `edcc0a5fb314a92937a4c621cc5f1872e2c0780158aa0933528d19d110331d05` | `3d39dd7d0e8fde23c7b2f54998c4f59a7fe1c09ed79e859c54dd79edb0771b1e` | yes |
  | `short_highlight.risk_discovery` | `804d156fda48f709d59b0cfe8bc59f0457677798c13ad774ce74307fad67eec5` | `a335cc1532f8fbab3ef15b2eb9d8a80462cdac97d2cbabcdcbf4cc1a51266d2c` | yes |
  | `short_highlight.boundary_review` | `89eb40e58aacd8e0bfdfcb03d3937bb90299659516ff1bc27db35d8c84026b3f` | `622d230f0290c8526181e3b36f55730a3e6b190b7efa977a6dbdd9941216d9e5` | yes |
  | `short_highlight.global_review` | `14fc738fcbda816b1ce415540a579504bd605b479639dc6e2c83961f4ff187a4` | `f9477baa0e5dd267e091b51e6b3c42276e92bd1a4b40d3549f16e2d29b86d39b` | yes |
  | `short_highlight.global_audit` | `d3b000d3910dd4d699741f704810f859d4b8f3aa930e078d41829ed435a1e8b3` | `a4ff7d01d8f84b4d5cb6ab94c4acb8730d69cacbdba7cb4960c9479af4f896ed` | yes |
  | `mini_lesson.discovery` | `cb37977bbad61c0c1ba64039164bc2c5543e0fd8d14ad44beedc65d9cd4aa84a` | `03010be4c3baa706fbb77f7590d5ca4a91b53de0c42c8138e7e6a8085ecb8666` | yes |
  | `mini_lesson.coverage_audit` | `42e2a18413d919ca69989cf39d6b7aca1b5f0f444bfd95a1e77f7fc64685eb8a` | `b5dc773e58cbd24a1dd8498f0be3867880e24944e00ce7944c57aff644452eb2` | yes |
  | `mini_lesson.precision_audit` | `d864bcf6bfa50352e6eacec3eb02b84922daccc31877af345acc385f0e9900f8` | `286795bb1d3f5bc8a72ddce67c81ee4eab1d7548198ef93a0063c2b5ab8716d7` | yes |
  | `mini_lesson.precision_confirmation` | `fbfdd8eb99e86f4407b382d4c60defa0d8beb91f8f838755a20f62ecf89d8e92` | `1a4959e0a4b130282c79c0743c7fdf3dd151a253cdc67dd99313e5ce2fa82ef3` | yes |
  | `mini_lesson.risk_discovery` | `6ba50849cc3b3707dc72d6d97333e1e839f3fe34001b7d3daa7531cba793b952` | `2a3e44f2a63dcb10f395434b18014ee0b012586aeee695b827685648d8a3a4ba` | yes |
  | `mini_lesson.boundary_review` | `50d3041f34fcbbeca570738ef5e14c8dcccdc07df409fd0379b4b4c1ed340cf9` | `63f525607cad124aaf0002fe89476bdcbbfa565b94b454da9f3142eb8ae2aa5f` | yes |
  | `mini_lesson.global_review` | `99287e4cf343de527b9e56809e528a60224c92bf8b8c6a630007fa610d7968f1` | `857eb960f1c4a40aefbf2c4d43b9d9c778dc62d19d50729a5489f4241bef284a` | yes |
  | `mini_lesson.global_audit` | `509db61a808132aa9662be5fcb72250b2f4000247945d8548504304576337619` | `a9d42e17e6fb374595a3eec64db9041caf358cb4cdb55a397f1fddc02b29c08f` | yes |
  | `variant_link` | `def25b05bd987a293cf74d5f964ca00504d8d247cfd8b1d4af17299289152aef` | `def25b05bd987a293cf74d5f964ca00504d8d247cfd8b1d4af17299289152aef` | no |

  16 of 17 identities change; the variant link is unchanged.

  Pins re-pinned with a Stage 17 justification in
  `tests/integration/test_dual_profile_evaluation.py`
  (`FROZEN_DISCOVERY_PROMPT_HASHES`, `PINNED_REVIEW_PROMPT_HASHES`); the
  variant link pin is unchanged.
- (4) Tests (+51 items: `test_dual_profile.py` 141 → 160,
  `test_dual_profile_flag_contract.py` 68 → 86,
  `test_dual_profile_evaluation.py` 99 → 113): ending-edge constant; all four
  facts required (each false keeps the flag); release on an unchanged and on
  an extended interval; Boundary Review keeping the flag still gates (and the
  audit-payload view keeps it); only the ending-edge flag is released next to
  each interior flag; the N07 persistence test now covers the three interior
  flags; L02-shape chain (released base is not a persisted-flag row, so the
  same-interval risk twin stays `manual_review`; with any fact false the twin
  is still blocked); service level: release for `topic_not_closed` alone and
  interior flags still persisting beside it; audit payload, representative
  rule, pair fallback keep order, manifest diagnostic and final routing treat
  an attested `topic_not_closed` exactly like an unflagged candidate; the
  representative rule fires for each false fact and for a Boundary Review that
  keeps the flag; v9 marker accepted with v1–v8; prompt contracts for the
  narrowed exemption across all 8 stages × 2 Profiles (superseded Stage 15
  wording absent everywhere, no digits or CJK in the rule), the Boundary
  Review definition/cross-reference/duration test, the Global Review/Audit
  restatements and the Global Review v9 sentence.
- (5) Mutation self-check (scratch copy of `src`/`tests` only;
  `/private/tmp/claude-501/-Users-junhuaxu-autoclip-claude/11442fc6-5e35-49d6-afb1-e25ebe8c47b5/scratchpad/stage17-sim/mutate.py`,
  results `mutation_results.txt`): 8 of 8 caught — M1 no v9 release (21
  failures), M2 attest `ending_complete` only (12), M3 ignore the
  Boundary-cleared condition (2), M4 release every structural flag (27), M5
  audit payload computed with a different rule (6), M6 `main.md` keeps the
  Stage 15 exemption (18), M7 Boundary Review duration test drops the
  subtraction (3), M8 Global Review drops the mirror (3).
- (6) Offline replay (stored stage outputs of six runs; `git archive` of the
  Stage 17 code commit;
  `/private/tmp/claude-501/-Users-junhuaxu-autoclip-claude/11442fc6-5e35-49d6-afb1-e25ebe8c47b5/scratchpad/stage17-sim/replay_v9.py`,
  output `replay_v9.txt` / `replay_v9.json`; the v8 column is the v5–v8
  persistence rule in the same tree and equals the reviewer's v8 replay; the
  v9 column equals the reviewer's P-a replay):

  | run | v8 rule (this tree) | v9 shipped | mini hits v9 | hard failures v9 | negatives v9 | rows changed v8->v9 | v8 == reviewer v8 / v9 == reviewer P-a | validate |
  |---|---|---|---|---|---|---|---|---|
  | cold-27 | PASS 95.0 | PASS 95.0 | 5 ['L01', 'L02', 'L03', 'L04', 'L05'] | - | - | - | True / True | ok |
  | warm-28 | FAIL 95.0 | FAIL 95.0 | 5 ['L01', 'L02', 'L03', 'L04', 'L05'] | ['irrelevant_padding'] | - | - | True / True | ok |
  | warm-29b | PASS 95.0 | PASS 95.0 | 5 ['L01', 'L02', 'L03', 'L04', 'L05'] | - | - | - | True / True | ok |
  | cold-30 | FAIL 92.5 | FAIL 92.5 | 5 ['L02', 'L03', 'L04', 'L05', 'L07'] | ['missing_any_p0_mini_lesson'] | - | - | True / True | ok |
  | cold-31 | PASS 92.5 | PASS 92.5 | 5 ['L01', 'L02', 'L03', 'L04', 'L05'] | - | ['N08'] | - | True / True | ok |
  | cold-32b | FAIL 92.5 | FAIL 97.5 | 6 ['L01', 'L02', 'L03', 'L04', 'L05', 'L07'] | ['forbidden_composite_interval'] | - | [('mini', 'risk_curriculum_steps_1_to_4_claim_chain', 'blocked', 'manual_review')] | True / True | ok |

  Exactly one row changes in six runs: cold-32b
  `risk_curriculum_steps_1_to_4_claim_chain` blocked → `manual_review` (L02
  back). cold-32b stays FAIL 97.5 on `forbidden_composite_interval` only
  (short 7, mini 6/6). Negative-anchor findings unchanged in every run (only
  cold-31 N08 informational `manual_review`). v9 releases persistence on 0–5
  rows per run; every other release changes no status. Fidelity: final
  routing is replayed exactly; the Global Audit is not re-run (its payload
  changes under v9, so a real run's audit may keep the base as representative,
  as in runs 27–31), and the prompt change needs a real cold run.
- Self-check: `make lint` rc 0 (ruff check, ruff format, mypy, schema check,
  web typecheck); targeted pytest (dual-profile unit, flag contract,
  delivery, render, integration, lineage prompts, benchmark evaluators)
  8 files, 494 passed; full backend pytest 3208 passed (3138 at Stage 16, plus 19 Stage 16b and 51 Stage 17 items). Deterministic validation only; no
  real model call.
- Recovery: revert `2932b7c15af600a900a8838deed4cfcf08a9c95b` (and this docs commit). Reverting restores v8
  routing and the Stage 16b prompt hashes; artifacts written with the v9
  marker would then fail to load until re-run, and Stage 17 cache entries are
  simply not hit by the reverted prompts.

### Acceptance policy from Stage 17 (user decision 2026-11-05, "Freeze, 2 cold PASS in a row"; definitions made precise in Stage 17b)

- After Stage 17 is accepted (independent tester and reviewer), code and
  prompts are **frozen** at that SHA.
- Benchmark acceptance requires **two consecutive fresh cold runs with strict
  PASS on the frozen SHA**.
- A failed run is **analysed before any change**; no immediate patching. Any
  later change starts a new frozen SHA and a new two-run count.
- A usage-limit continuation segment (cold-Nb on the preserved cache of
  cold-N) still counts as **one** run.
- **FROZEN (precise; Stage 17b).** The freeze covers the code/prompt tree,
  not the documentation. A run is on the frozen SHA when, at its start:
  (a) `git diff --quiet <freeze-sha> -- src tests scripts config tools apps
  migrations pyproject.toml uv.lock alembic.ini Makefile .gitignore
  liveclip_dual_profile_benchmark_v1.json liveclip_dual_profile_benchmark_v1.md`
  exits 0 and `git status --porcelain --untracked-files=all -- <the same
  paths>` is empty (no committed, uncommitted or untracked change). Every
  listed path exists in the tree. `apps` holds the API and worker entry
  points and the review console (`apps/web`); the console is not on the
  benchmark path, but it is code, so it is frozen too. The two root
  benchmark files are the evaluator's inputs. (b) The 17 prompt identities
  computed from that tree equal the recorded Stage 17b hash table. (c) The
  routing policy is `quality-gate-risk-routing-v9` and the algorithm version
  is `dual-profile-direct-v1` (cache-key schema unchanged), and the run's
  final results record exactly these. Docs-only commits (`STATUS.md`,
  `docs/`, `tasks/`, `.agent/`, `AGENTS.md`, `CLAUDE.md`, `README.md`) touch
  none of these paths, so HEAD may move by commits that record run results
  without resetting the count. (`.gitignore` was added to this list at
  freeze acceptance, reviewer P3.)
- **Fresh cold (precise; Stage 17b, provenance criterion corrected at
  freeze acceptance, reviewer P2).** A fresh run's run manifest records
  `cache_hits == 0`, its cache root did not exist or was empty at run
  start, and every cache file in that root has an mtime at or after the
  run's attempt start. A continuation segment (cold-Nb) may copy only the
  cache of the immediately previous segment of the same run (cold-N for
  cold-Nb, cold-Nb for cold-Nc); its run manifest records `cache_hits`
  equal to the number of entries copied from that segment, every carried
  file is byte-identical to that segment's file, and every new file has an
  mtime at or after the segment start. Content identity against other
  cache roots is reported for information only: identical model outputs
  under identical frozen prompts legitimately produce identical cache
  files, so it is not a pass/fail criterion. A warm run, or a run seeded
  from any other root, is a diagnostic, never acceptance evidence.
  (History: the Stage 17b wording also required 0 cache files
  content-identical to a file in any earlier cache root; the freeze
  reviewer's P2 showed that two honest runs on the same frozen prompts may
  produce identical files, so that clause was replaced before any counted
  run.)
- **Run environment (freeze reviewer P3).** The two counted runs must
  have equal run-manifest `provider`, `model`, `prompt_hashes`, routing
  policy (as final-validated) and algorithm version; the same pinned
  Claude CLI binary (`.cache/claude-cli/2.1.308/claude`, sha256
  `ca923c86ac84b30574a82331a05b6e066c27477a926ceaffe46a845a33e4dd37`,
  `--version` 2.1.308); and the same effective Settings, with no `.env`
  or `.env.local` override of the `LIVECLIP_CLAUDE_*` model, timeout or
  attempt settings. Each run records `ls -la .env .env.local` presence
  and, for a present file, only the names of its `LIVECLIP_` keys, never
  values. Check at this docs commit (2026-11-05): `.env` absent;
  `.env.local` present and ignored (`.gitignore` `.env.*`), with no
  `LIVECLIP_CLAUDE_*` and no `LIVECLIP_STRUCTURED_PROVIDER` key; the CLI
  binary's recomputed sha256 equals the pin and its mode is 0555.
- **What counts (Stage 17b).** A run aborted by a provider or environment
  failure (usage limit, CLI or transport failure, host interruption) before
  a strict evaluation exists counts neither way: re-run it as a new fresh
  cold run, or continue it as cold-Nb under the rule above. A run with a
  strict evaluation counts: strict PASS adds one to the consecutive count;
  strict FAIL resets the count to zero and is analysed before any change.
  Any change to a frozen path, a prompt identity, the routing policy or the
  algorithm version starts a new freeze SHA and a count of zero.
- **Evidence categories.** Strict PASS is deterministic evaluator evidence
  about real-model output. Rendering plus human editorial/audio review
  remains a separate evidence category: it is not part of strict PASS and is
  not implied by it.
- **Freeze SHA.** The freeze candidate is the Stage 17b code commit
  `50232af0cb0b0194fb663528b569998a8a2fd79b`; it becomes the freeze SHA once the independent tester and
  reviewer accept it. The Stage 17 tree (`2932b7c`) is no longer the
  candidate, because Stage 17b changes 16 of the 17 prompt identities.
  (Later, 2026-11-05: accepted; `50232af0cb0b0194fb663528b569998a8a2fd79b` is the
  freeze SHA.)
- **Amendment (user decision 2026-11-07, Stage 19; appended, the bullets
  above are historical and unchanged).** The benchmark freeze now covers
  only the **dual-profile benchmark closure**, no longer the whole
  `src tests scripts config tools apps migrations pyproject.toml uv.lock
  alembic.ini Makefile .gitignore` tree. The current freeze SHA stays
  `f525338ed9427b0fcac9925bac6075d60af13e69` and its count stays **2/2**. Changes outside the closure do
  not reset the count and need no cold re-run, provided the reviewer's
  freeze evidence below is clean at every checkpoint. A change inside the
  closure, to a prompt identity, the routing policy or the algorithm
  version still starts a new freeze SHA and a count of zero. The closure
  (transitive in-repo import closure of
  `src/liveclip/services/dual_profile_evaluation.py` and
  `src/liveclip/pipeline/dual_profile.py`, the `dual-profile-eval` CLI
  entry, the evaluator and its imports, the benchmark files and the
  dependency lock; derivation in
  `docs/exec-plans/liveclip-customer-delivery.md`, "Freeze closure"):
  `src/liveclip/__init__.py`, `src/liveclip/__main__.py`,
  `src/liveclip/limits.py`, `src/liveclip/cli/__init__.py`,
  `src/liveclip/cli/app.py`, `src/liveclip/clipping_skills`,
  `src/liveclip/config`,
  `src/liveclip/domain/{__init__,candidate,clip_profile,edit_plan,review,semantic_validation,state_transitions,time,transcript}.py`,
  `src/liveclip/media/{__init__,ingest,models,process,secure_files}.py`,
  `src/liveclip/observability`,
  `src/liveclip/pipeline/{__init__,dual_profile,semantic_global,semantic_lineage,semantic_profiles,semantic_transport,srt}.py`,
  `src/liveclip/prompts`, `src/liveclip/providers`,
  `src/liveclip/renderer`,
  `src/liveclip/services/{__init__,captions,dual_profile_evaluation,structured_editorial_provider}.py`,
  `scripts/{__init__,evaluate_benchmark,benchmark_gates}.py`,
  `liveclip_dual_profile_benchmark_v1.json`,
  `liveclip_dual_profile_benchmark_v1.md`, `pyproject.toml`, `uv.lock`
  (brace lists expand to individual files; directories are frozen
  recursively). **Reviewer freeze evidence, every checkpoint:** (1)
  `git diff --exit-code f525338 -- <closure paths>` exits 0 and
  `git status --porcelain -- <closure paths>` is empty; (2)
  `tests/unit/test_dual_profile_freeze_pins.py` passes and an independent
  recompute of the 17 prompt identities matches the Stage 18b "after"
  column; (3) the Settings fingerprint recompute equals
  `c81f0ece91debb4f1637ba5eecc3af64a91da256f586917408de458317d170d1`; (4) re-running
  `scripts/evaluate_benchmark.py` on the stored cold-35 and cold-36 inputs
  yields byte-identical `benchmark-result.json`; (5) when
  `src/liveclip/services/dual_profile_delivery.py` changes, the cold-36
  review-package `manifest.json` regenerated before/after is identical
  (only the wall-clock `created_at` normalised; procedure in the Stage 19
  ExecPlan). Stage 19 must not edit `src/liveclip/cli/app.py`.
- Clarification (appended 2026-11-07 after the Stage 19a review; the bullet
  above is unchanged): of the CLI only the three files
  `src/liveclip/__main__.py`, `src/liveclip/cli/__init__.py` and
  `src/liveclip/cli/app.py` are frozen, not `cli/app.py`'s whole import
  graph. Evidence item (3): the Settings fingerprint is computed with exactly two environment overrides, `LIVECLIP_STRUCTURED_PROVIDER=claude-cli` and `LIVECLIP_CLAUDE_EXECUTABLE=<repo>/.cache/claude-cli/2.1.308/claude` (key names and path only; no `.env` value is read or recorded), the same as the counted cold-35/cold-36 runs. Evidence item (6), added:
  `.venv/bin/python -m liveclip dual-profile-eval --help` exits 0.

### Stage 16b status

- Stage 16b (`b5d8def`) remains implemented, **pending independent
  verification**; it will be verified together with Stage 17. (Later,
  2026-11-05: verified and accepted with Stage 17 and 17b at the freeze
  SHA `50232af`.)
- (Historical next step; the Stage 17 reviewer accepted with nits, which
  became Stage 17b.) Next: independent tester and reviewer on the Stage 16b and Stage 17 SHAs;
  then freeze and the two fresh cold runs; human review of the cold-31,
  cold-32b and earlier renders stays pending.
- (Historical next step; done: freeze accepted, see the FREEZE section
  above; next is cold-33.) Next (Stage 17b): independent tester and reviewer on `50232af0cb0b0194fb663528b569998a8a2fd79b`; on
  acceptance it is the freeze SHA; then two consecutive fresh cold strict
  PASS runs on it under the definitions above. Human review of the cold-27
  through cold-32b renders stays pending (separate evidence category).
  Push and merge still need explicit consent.

## Stage 16b: Stage 16 reviewer P3 nits (2026-11-04) — ACCEPTED with Stage 17/17b at 50232af (freeze; was implemented, pending verification)

- **Status: implemented, pending independent tester and reviewer.** Code and
  tests in `b5d8def745d468863917ae04d1c2d1dd314004c2` on `claude/liveclip-stage8-routing` (main checkout,
  after the Stage 16 fast-forward to `58186f5`); this docs commit follows.
  Not pushed or merged to `main`. No prompt file, prompt hash, evaluator,
  threshold, benchmark, routing policy (`quality-gate-risk-routing-v8`),
  algorithm version (`dual-profile-direct-v1`), cache-key schema or
  persisted semantic-outcome schema change; the success path is unchanged.
- Stage 16 reviewer verdict: **ACCEPT with nits** (no P0–P2; 7 of 8
  independent mutations caught; R7, the regeneration-phase provider failure
  labelled `repair`, survived). Reviewer notes in
  `/private/tmp/claude-501/-Users-junhuaxu-autoclip-claude/11442fc6-5e35-49d6-afb1-e25ebe8c47b5/scratchpad/stage16-review/` (`mut.py`, `mut_results.txt`). Stage 16
  (`b1f11ec` code, `58186f5` docs) was fast-forwarded into
  `claude/liveclip-stage8-routing`; its isolated worktree is left for the
  Controller to remove.
- (1) R7: `test_a_regeneration_provider_failure_names_the_regeneration_phase`
  (unit: phase, attempts `initial`/`repair`, records, audit, summary) and
  `test_a_regeneration_provider_failure_is_recorded_as_the_regeneration_phase`
  (integration: `failed_phase` `regeneration` in
  `failed-short_highlight-discovery.json` and in `failure-manifest.json`,
  fixed timeout message, three call records, nothing cached).
- (2) Timing pass-through: `_aggregate_semantic_failures` forwards the
  selected failure's `timeout_seconds` / `suspended_seconds`, and every
  stage rewrap of an earlier error (v1 Discovery, Global Review repair,
  Boundary Review, the v4 local-request rewrap and the v4 batch aggregate)
  forwards them, so an aggregated timeout still says "timed out after N s".
  An AST test checks every `StructuredProviderError(<error>.code, ...)` in
  `src/liveclip` (at least ten) passes both keywords. Exception: the durable
  v4 unit outcome (`SemanticUnitOutcome`, persisted) stores only its failure
  code, so the rewrap built from it carries no timing; that schema is not
  changed. This corrects the Stage 16 wording "carried through every
  rewrap" below, which held only for the provider-level rewraps.
- (3) Fixed messages: `STRUCTURED_INPUT_BUDGET_EXCEEDED` "structured provider
  request exceeds its context budget; no model call ran",
  `STRUCTURED_REPAIR_BUDGET_EXCEEDED` "structured repair request exceeds its
  context budget; no repair call ran", `SEMANTIC_UNIT_INTERNAL_ERROR`
  "semantic unit failed with a local internal error", `PROVIDER_CANCELLED`
  "structured provider request was cancelled". None reads "request failed"
  or "could not be validated".
- (4) Backstop: the safer option. `failure-manifest.json`
  (`unexpected_error`) keeps only `exception_type` (the class name, checked
  as an identifier, else `Exception`) and `exception_message_recorded:
  false`; the bounded `error` text is gone. An arbitrary exception may quote
  a local path, an account identity or a token and this file is durable; the
  text still reaches the operator once on stderr through the re-raised
  exception. Test: an exception quoting a synthetic address, token and home
  path leaves none of them in the manifest.
- (5) Sleep clock: the gap is measured on a sleep-counting clock,
  `time.clock_gettime(CLOCK_MONOTONIC_RAW)` on Darwin (keeps counting during
  sleep, never stepped by NTP or by hand; `time.monotonic` there is
  `mach_absolute_time`, which stops) and `time.time()` elsewhere. It also
  counts toward the deadline (`max(monotonic, wall, sleep clock)`), so a
  sleep is enforced even if the wall clock was stepped back. On Darwin a
  wall-clock step forward without sleep stays a plain `TimeoutExpired`.
  `ProcessInterruptedBySleep.wall_elapsed_seconds` is the elapsed time on
  that clock. Tests with patched clocks: sleep classified, sub-gap lead,
  spent monotonic budget, wall step without sleep (plain timeout), sleep with
  the wall clock stepped back (detected), and clock selection (raw on Darwin,
  wall elsewhere); the suite also passes with the fallback forced.
- (6) CLI summary: `_failure_summary` (shared by the exhausted-validation and
  provider-failure summaries) puts code, profile, stage, subject and phase
  first, keeps bounded notes, trims a long evidence path from its start to
  the room left (the file name survives), then the trimmed detail; the
  result never exceeds 480 characters, so `_safe_cli_error` never replaces
  it with the generic message. The backstop's `failure evidence:` note is
  bounded the same way. Tests: unit (both summaries, with and without a long
  note) and CLI (rc 1, code and file name printed, no generic message).
- Tests: 19 new test items (structured-provider failures 23 → 36, flag
  contract 67 → 68, media process 13 → 16, dual-profile integration
  97 → 99); one existing backstop test now asserts the text is absent.
- Mutation self-check (scratch copies of the main checkout `src` only;
  `/private/tmp/claude-501/-Users-junhuaxu-autoclip-claude/11442fc6-5e35-49d6-afb1-e25ebe8c47b5/scratchpad/stage16b-mut/mut.py`, results in `results.txt`): 12 of 12 caught —
  R7 regeneration mislabelled `repair`, B1 aggregate drops the timeout, B2 a
  stage rewrap drops the timeout, B3 budget message removed, B4 internal
  message removed, B5 backstop stores the message, B6 raw clock never used,
  B7 gap measured on the wall clock, B8 deadline ignores the sleep clock, B9
  evidence path unbounded, B10 path keeps its head, B11 raw clock reads the
  wall clock.
- Prompt hashes: all 17 identity hashes printed from the main checkout by
  `/private/tmp/claude-501/-Users-junhuaxu-autoclip-claude/11442fc6-5e35-49d6-afb1-e25ebe8c47b5/scratchpad/stage16b-hashes.py` equal the Stage 16 table
  (`stage16-hashes-after.txt`); no prompt file changed.
- Self-check: `make lint` rc 0 (ruff check, ruff format, mypy, schema check,
  web typecheck); targeted pytest (29 files: dual-profile suites, structured
  provider, Claude CLI, Codex, OpenAI, media process, stage handlers,
  semantic executor/unit recovery/transport/global, transport budget, edit
  text guard, lineage runtime and CLI tests) 999 passed. Deterministic
  validation only; no real model call.
- Recovery: revert `b5d8def`. No cache, prompt or algorithm impact; a
  backstop manifest written before Stage 16b may contain an `error` text.
- Next: independent tester and reviewer on the Stage 16b SHAs; cold-32b
  analysis (below); human review of the cold-31, cold-32b and earlier
  renders stays pending.
- (2026-11-05) Verification deferred by the Controller: Stage 16b will be
  independently verified together with Stage 17 (above). The cold-32b
  analysis is recorded in the Stage 17 section.

## cold-32b real run at b758f71 (2026-11-04) — strict FAIL 92.5 (continuation of cold-32)

- continuation of cold-32 at `b758f71` (routing `quality-gate-risk-routing-v8`, real Claude CLI): eval rc 0; 99 cache hits from the preserved cold-32 cache plus 182 fresh provider records; 0 sleep during the run; provenance clean (0 content-identical cache files vs 26 other cache roots). Strict **FAIL 92.5**. Hard failures: (1) `missing_any_p0_mini_lesson` (L02): the base `ml_0006_steps_1_to_4_numbered` kept its Discovery `topic_not_closed` flag through structural persistence after Boundary Review cleared it without a trim; Global Review rejected it as a duplicate of its risk twin `risk_curriculum_steps_1_to_4_claim_chain`, and the twin union passed the gated flag to that risk receiver, so the quality gate blocked it; (2) `forbidden_composite_interval` (new): three `ml_0003_*` mini candidates routed `manual_review` overlap 1099200–1351000 ms. Short 7/8 (S03 missed); mini 5/6 (L01, L03, L04, L05, L07 hit); R01 blocked, R02 `manual_review`; every N07/N08-overlapping row blocked or rejected; Discovery `material_interruption` mini 69 / short 21. 12 renders rc 0, human editorial/audio review pending. Evidence `data/evaluations/dual-profile-strict-eval-20261104-claude-cold-32b/evidence/`. Analysis pending. (Later, 2026-11-05: analysed by an independent read-only reviewer; summary, user decisions and Stage 17 in the section above.)
- Evidence category: real-model inference at `b758f71` (authorized Claude
  CLI subscription run); it is not evidence for Stage 16 or Stage 16b, which
  change only failure paths. Renders passing automatic checks are not human
  review.

## Stage 16: provider-failure observability (Stage 15c reviewer Part B) (2026-11-04) — REVIEWER ACCEPT WITH NITS at 58186f5; nits → Stage 16b

- **Reviewer ACCEPT with nits** at `58186f54c3ebc7bf3255ef5046aa25a9c25f04c3`
  (code `b1f11ec`): no P0–P2; 7 of 8 independent mutations caught (R7, a
  regeneration-phase provider failure labelled `repair`, survived). The P3
  nits became Stage 16b (above). Fast-forwarded into
  `claude/liveclip-stage8-routing`. The bullets below are the historical
  implementation record; Stage 16b corrects the backstop `error` field, the
  "every rewrap" wording and the wall-clock gap.
- **Status (historical): implemented, pending independent tester and reviewer.** Code and
  tests in `b1f11ecbea257488815fce3f8636bc853078ba2f` on local branch
  `claude/liveclip-stage16` (from `b758f71`, in an isolated worktree); this
  docs commit follows. Not pushed or merged. No prompt file, prompt hash,
  evaluator, threshold, benchmark, routing policy
  (`quality-gate-risk-routing-v8`), algorithm version
  (`dual-profile-direct-v1`) or cache-key schema change. The success path
  (routing, outputs, cache bytes, `provider-calls.json`) is unchanged.
- Stage 15c was **accepted** at `b758f7172f6cecebadb4afc82de502788d26de9e`
  (tester PASS: lint rc 0, backend 3104 passed, vitest 80, e2e 4/4,
  concurrency test 5/5, no sleep in the test window; reviewer ACCEPT: 7 of 7
  independent mutations caught, offline replay identical).
- cold-32 root cause (reviewer Part B): `short_highlight` Global Review hit
  two consecutive wall-clock `PROVIDER_TIMEOUT`s (the initial request and its
  one semantic retry) while the machine slept. Every unlisted
  `StructuredProviderError` code was mapped to "structured model output could
  not be validated" (`_structured_error_message`), so the timeout was
  misreported; `_resolve_call` wrapped only deterministic `ValueError`
  failures and the run wrapper caught only
  `DualProfileValidationExhaustedError`, so no `failed-*.json`,
  `provider-calls.json` or `failure-manifest.json` was written and every
  completed call record was lost (reviewer P3 nit). The cold-32 stage cache
  was verified valid by a read-only integrity check (99 files; identity,
  prompt hash, cache-key recomputation and output model all match). A
  continuation run **cold-32b** on the preserved cache was started at
  `b758f71`; its result is pending and is not evidence for Stage 16 (it runs
  `b758f71` code). (Later: cold-32b finished, strict FAIL 92.5; see its
  section above.)
- P1 provider failures keep their evidence: `_resolve_call` wraps a
  `StructuredProviderError` from the initial generation (after its one
  semantic retry), the repair or the regeneration into
  `DualProfileProviderFailureError(RuntimeError)` carrying stage, profile,
  subject, cache key, phase, failure code, the validation attempts made so
  far, and the unit's accumulated plus failing call records. It is recorded
  in `_ResolutionAudit` in the same ordered list as exhausted units, so
  concurrent chunk failures are all kept. The run wrapper writes, to the run
  directory only (never the cache): `failed-<profile>-<stage>.json`
  (`status: provider_failed`, `failure_code`, `failed_phase`, fixed
  `message`, `provider_calls`, `provider_attempts`, `attempts`,
  `concurrent_exhausted_units`, `concurrent_provider_failed_units`), a
  partial `provider-calls.json` (completed units, the failing unit, then
  every other failed unit in failure order) and `failure-manifest.json`
  (`failure_kind: provider_failure`, `failure_code`, `failed_phase`,
  `concurrent_failed_subject_ids`, `concurrent_failures`). An exhausted
  validation keeps its Stage 13d/13e format and now also lists a concurrent
  provider failure. Backstop: any other exception after the run directory
  exists writes only `failure-manifest.json` (`failure_kind:
  unexpected_error`, `exception_type`, a bounded one-line `error`, every
  completed call record plus those of already failed units) and adds a
  `failure evidence: <path>` note. Every error is re-raised; an
  evidence-writer failure is attached as a note and never masks it.
- P2 fixed messages (shared by the Claude CLI, Codex and OpenAI providers):
  `PROVIDER_TIMEOUT` "structured provider request timed out after N s" (N
  is the configured timeout; bare text when unknown),
  `PROVIDER_INTERRUPTED_BY_SLEEP`, `PROVIDER_ERROR`,
  `PROVIDER_CONFIGURATION`, `STRUCTURED_TOOL_EVENT`, and
  `STRUCTURED_OUTPUT_MISSING` ("was missing"); an unlisted code says
  "structured provider request failed (CODE)". "could not be validated" is
  kept only for `STRUCTURED_OUTPUT_INVALID`. `StructuredProviderError`
  gains optional `timeout_seconds` / `suspended_seconds` (fixed numbers,
  never provider content), carried through every rewrap.
- P2 sleep detection: `run_cancellable_process` raises
  `ProcessInterruptedBySleep` (a `subprocess.TimeoutExpired` subclass, so
  every other caller keeps its timeout semantics) when the deadline fired,
  the monotonic clock had not used the budget, and the wall clock ran more
  than `SLEEP_DETECTION_GAP_SECONDS` (60 s) ahead of it. The Claude CLI and
  Codex providers map it to `PROVIDER_INTERRUPTED_BY_SLEEP` (record code
  `STRUCTURED_PROVIDER_INTERRUPTED_BY_SLEEP`); `_generate_with_semantic_retry`
  never retries it (fail fast with evidence). The durable job pipelines keep
  classifying it as transient (`semantic_executor`), exactly as the timeout
  it was before.
- P3 CLI: `dual-profile-eval` prints "dual Profile provider failure CODE in
  PROFILE STAGE (SUBJECT) during PHASE; evidence: PATH; cause: MESSAGE"
  (bounded, only the cause is trimmed) and rc 1; for the backstop it prints
  the error and then the manifest path on a second stderr line.
- Decisions: (1) the sleep class subclasses `TimeoutExpired` rather than
  changing timeout behaviour; (2) a large wall-clock lead after the
  monotonic budget was already spent stays an ordinary timeout; (3) only the
  sleep code is exempt from the dual-profile semantic retry (timeouts are
  still retried once, as before); (4) a concurrently cancelled unit
  (`ProviderCancelled`) is still neither resolved nor failed and its calls
  are not listed (unchanged); (5) a provider failure file includes the
  provider's own repair attempts (parsed model output, the same policy as
  exhausted evidence; the Claude CLI provider already drops any output that
  contains its account identity).
- Tests: integration — two `PROVIDER_TIMEOUT`s in short Global Review
  (failure file, partial calls with completed plus both failing calls,
  manifest, no cache entry for the unit, every earlier entry byte-identical
  and reused as a cache hit by a rerun, re-raised); two concurrent Global
  Review chunk provider failures both recorded; an exhausted unit and a
  provider-failed unit overlapping in Discovery; an unexpected `ValueError`
  mid-run writes the backstop manifest; an error before the run directory
  exists writes nothing. Unit — message per code, timeout/sleep text, only
  `STRUCTURED_OUTPUT_INVALID` says "could not be validated"; Claude CLI,
  Codex and OpenAI mappings; `run_cancellable_process` with patched clocks
  (sleep, sub-gap lead, spent monotonic budget, real timeout, pickling); no
  semantic retry on sleep, one retry on timeout, repair-phase failure keeps
  the initial attempt; bounded summary; job-pipeline classification; CLI rc
  1 with code, stage and evidence path. One existing test
  (`test_resolve_call_regeneration_exhaustion_names_the_real_cause`) now
  expects the wrapped error and checks the provider message on its cause.
- Mutation self-check (scratch copies of the worktree `src` only;
  `/private/tmp/claude-501/-Users-junhuaxu-autoclip-claude/11442fc6-5e35-49d6-afb1-e25ebe8c47b5/scratchpad/stage16-mut/mutate.py`,
  results in `mutation_results.txt`): 12 of 12 caught — M1 initial provider failure not wrapped (6 tests fail), M2 failure not recorded in the audit (3), M3 sleep semantically retried (1), M4 no sleep classification (1), M5 sleep ignores a spent monotonic budget (1), M6 old "could not be validated" default and no timeout text (11), M7 no unexpected-error backstop (1), M8 CLI prints the generic message (1), M9 provider failure file labelled `validation_exhausted` (1), M10 Claude CLI maps sleep to `PROVIDER_TIMEOUT` (1), M11 concurrent units' records dropped from `provider-calls.json` (3, the Stage 13e exhausted test included), M12 repair-phase provider failure unwrapped (1).
- Prompt hashes: all 17 identity hashes, printed from the worktree by
  `/private/tmp/claude-501/-Users-junhuaxu-autoclip-claude/11442fc6-5e35-49d6-afb1-e25ebe8c47b5/scratchpad/stage16-hashes.py`,
  equal the Stage 15c table (`stage15c-review/hashes.txt`); no prompt file
  changed.
- Self-check: `ruff check` (src, tests, scripts, tools) and `ruff format
  --check` clean; `mypy src/liveclip` clean (202 files); targeted pytest
  (dual-profile suites, Claude CLI, Codex, OpenAI, structured-provider,
  semantic executor, media process and CLI tests; 18 files) 581 passed;
  full backend pytest tests 3138 passed (3104 at b758f71 plus 34 new). Deterministic validation only; no real model call.
- Recovery: revert `b1f11ec`. No cache, prompt or algorithm impact; the new
  evidence files appear only in failed run directories.
- (Historical next step; the reviewer accepted Stage 16 with nits, Stage 16b
  followed and cold-32b finished, above.) Next: independent tester and
  reviewer on the Stage 16 SHAs; record the cold-32b result when it finishes; human review of the cold-31 and earlier
  renders stays pending.

## Stage 15c: risk-twin review covers risk-record receivers (routing v8), Stage 15b reviewer nits (2026-11-04) — ACCEPTED at b758f71

- **Accepted** at `b758f7172f6cecebadb4afc82de502788d26de9e` (code
  `b026c64`, docs `c99d198` and `b758f71`): tester PASS: lint rc 0, backend
  3104 passed, vitest 80, e2e 4/4, concurrency test 5/5, no sleep in the
  test window; reviewer ACCEPT: 7 of 7 independent mutations caught, offline
  replay identical. Reviewer Part B (the cold-32 failure was misreported and
  left no evidence) becomes Stage 16 (above). The bullets below are the
  historical implementation record.
- **Status (historical): implemented, pending independent tester and reviewer.** Code and
  tests in `b026c64b42fb92e66841150d69d8167655b99c61` on local branch `claude/liveclip-stage15c` (from
  `e960414`); this docs commit follows. Both commits were fast-forwarded into
  `claude/liveclip-stage8-routing`; the isolated worktree and the
  `claude/liveclip-stage15c` branch were then removed. Not pushed or merged
  to `main`. No prompt
  file, prompt hash, evaluator, threshold, benchmark, algorithm version
  (`dual-profile-direct-v1`) or cache-key schema change.
- Stage 15b was **accepted** at `e960414b381d6086151f8fe0572feb5d2b8784f9`
  (tester PASS: lint rc 0, backend 3101 passed, vitest 80, e2e 4/4, concurrency test 5/5, no sleep; reviewer ACCEPT with nits: no P0–P2, 8 of 9 independent mutations caught (R5b, a service diagnostic computed as `len(sources)`, survived), replay byte-identical, every documented hash matches). Reviewer notes in
  `/private/tmp/claude-501/-Users-junhuaxu-autoclip-claude/11442fc6-5e35-49d6-afb1-e25ebe8c47b5/scratchpad/stage15b-review/`
  (`risksel.py`, `mutation_results.txt`).
- cold-32 (fresh cold run, real Claude CLI) was **started at `e960414`**
  (Stage 15b, routing v7) in the main checkout; its result is pending and is
  not evidence for Stage 15c. Stage 15c changes no prompt hash, so its
  cached stage outputs stay valid; only final routing differs, and only
  where a selected risk record shares an interval with a different tagged
  risk record.
- cold-32 (started at `e960414`, routing v7, real Claude CLI) was **interrupted by a machine sleep**: the lid was closed and the charger unplugged at 15:56 PST; the evaluation exited rc 1 at 16:37 with stderr only "structured model output could not be validated" and no `failed-*.json` was written. The `short_highlight` stage cache (discovery, coverage_audit, boundary_review, global_review) is preserved. The run is **environment-invalid** (no benchmark result, no evidence for or against any stage); a continuation run **cold-32b** on the preserved cache is planned.
- User decision (2026-11-04): "when a risk twin has a high-risk tag, its
  twin can't be auto-published". v7 applied it only to non-risk receivers.
- Nit 1 (routing): routing policy **`quality-gate-risk-routing-v8`**
  (constant and `Literal`; v1–v7 and unmarked artifacts still load). Step 3
  of final assembly, risk-twin review, now downgrades ANY row still
  `selected` after the twin union, a risk-discovery record included, whose
  identical final interval has a DIFFERENT risk-discovery record carrying an
  `AUTO_BLOCKING_RISK_TAGS` tag (whatever that record's status). A record is
  never its own source. Everything else is unchanged: `manual_review` only
  (never `blocked`), tags and flags not copied, the same prefix and reason
  text, the same position (after the twin union, before Top-N), idempotent,
  and the single helper `risk_twin_review` still drives assembly, the
  `risk_twin_review_downgrades` diagnostic and the `validate_against`
  cross-check (no `selected` row may be pending; every prefixed row must be
  backed by a tagged risk twin; the count must match). A downgraded risk
  record stays `manual_review`: step 5 only retains REJECTED risk records as
  `blocked`, and a formerly selected row carries no gated flag. A selected
  risk record cannot itself carry an automatic-blocking tag (the
  `FinalProfileCandidate` validator), so only untagged or
  non-automatic-blocking risk records are new receivers.
- Nit 2 (test gap): `RiskTwinProvider` gains a base-pass same-interval twin
  that Global Review keeps `manual_review` (`manual_twin`) and a
  risk-discovery record with only `commercial_claim` that Global Review
  selects (`risk_commercial_twin`); its Global Audit mock decides the listed
  twin pairs `distinct_objective`. The new service test
  `test_service_risk_twin_review_diagnostic_counts_downgrades_not_tagged_twins`
  has two rows with a tagged risk twin and one downgrade, so it fails when the
  service diagnostic counts `len(sources)` (mutation R5b, verified
  scratch-only).
- Nit 3 (accepted residual, outside the user decision): a selected row next
  to a NON-risk twin that carries an automatic-blocking risk tag is not
  downgraded. Risk tags have never been shared between non-risk twins in any
  routing version; that twin's own review already routes it (it can never be
  `selected` itself), and the decision is about risk twins only. Pinned by the
  existing `tagged_base` case of
  `test_risk_twin_review_needs_an_auto_blocking_tag_on_a_risk_record`.
- Tests (changed existing assertions explained):
  - `tests/unit/test_dual_profile.py`: the `risk_pair` case that pinned the
    v7 behaviour ("a selected risk record is not downgraded by another risk
    record") is flipped and moved into the new
    `test_risk_twin_review_downgrades_a_selected_risk_record_too`
    (justification: the user decision covers every twin of a tagged risk
    twin): the selected risk record becomes `manual_review` with the exact
    prefixed reason and no tag; the tagged source keeps its status and
    reason; `sources` excludes the source itself; the manifest cross-check
    accepts the result with diagnostic 1 and rejects an unrouted result
    ("violates the risk-twin review rule"); a lone tagged risk record has no
    sources. The helper test's `sources` now also lists the three
    risk-record receivers (each tagged record sees only the other). The
    routing-marker test expects v8 and loads v1–v8.
  - `tests/integration/test_dual_profile_evaluation.py`: the three marker
    assertions expect v8; new service tests for nit 2 (above) and
    `test_service_risk_twin_review_drops_a_selected_risk_record_to_manual_review`
    (the selected `commercial_claim` risk record and the lesson both
    `manual_review` with the prefix, `health_advice` not copied, the tagged
    record unprefixed, diagnostic `{short 0, mini 2}`, cross-check with the
    risk membership).
- Mutation self-check (`/private/tmp/claude-501/-Users-junhuaxu-autoclip-claude/11442fc6-5e35-49d6-afb1-e25ebe8c47b5/scratchpad/stage15c-sim/mutate.py`, scratch copies of the
  worktree `src` only; results in `mutation_results.txt`): 12 of 12 caught (an earlier draft of
  this record said 13 of 13; the script runs twelve mutations) —
  v7 receivers (non-risk only), no self-exclusion, risk-only receivers,
  R5a validator counts sources, **R5b service counts sources (now caught by
  the nit-2 test)**, R5c both, and the Stage 15b reviewer's R1 (Top-N before
  review), R2 (pending includes manual), R3 (start-only key), R4 (no reverse
  status check), R6 (first twin only), R7 (downgraded = any manual twin).
- Offline replay (`/private/tmp/claude-501/-Users-junhuaxu-autoclip-claude/11442fc6-5e35-49d6-afb1-e25ebe8c47b5/scratchpad/stage15c-sim/replay.py`, adapted from Stage 15b:
  the worktree's v8 assembler and strict evaluator on the stored stage
  outputs read-only from the main checkout's `data/evaluations`; the v7
  baseline is the same code with receivers restricted to non-risk rows; the
  v8 manifest cross-check, including both diagnostics, ran on every run; no
  tracked edit, no model call):

  | Run | v7 replay | v8 replay | v7→v8 changes | final JSON identical (excl. marker) | `risk_twin_review_downgrades` (short/mini) | risk-record receivers (status) |
  | --- | --- | --- | --- | --- | --- | --- |
  | cold-27 | PASS 95.0 | PASS 95.0 | none | yes | 0 / 0 | 4 (all `blocked`) |
  | warm-28 | FAIL 95.0 (`irrelevant_padding`) | FAIL 95.0 (`irrelevant_padding`) | none | yes | 0 / 0 | 0 |
  | warm-29b | PASS 95.0 | PASS 95.0 | none | yes | 0 / 0 | 0 |
  | cold-30 | FAIL 92.5 (`missing_any_p0_mini_lesson`) | FAIL 92.5 | none | yes | 0 / 0 | 0 |
  | cold-31 | PASS 92.5 | PASS 92.5 (N08 informational) | none | yes | 0 / 0 | 0 |

  Every evaluator field is identical between v7 and v8, and the v7 replay
  equals the Stage 15b replay results. No stored run has a selected risk
  record on a tagged risk twin's interval, so v8 changes nothing here.
  Routing evidence only, not a benchmark pass.
- Prompt hashes: all 17 identity hashes (printed by
  `/private/tmp/claude-501/-Users-junhuaxu-autoclip-claude/11442fc6-5e35-49d6-afb1-e25ebe8c47b5/scratchpad/stage15c-sim/hashes.py` from the worktree) equal the Stage 15b table
  below; no prompt file changed.
- Self-check: `ruff check` and `ruff format --check` clean on the changed
  files; `mypy` clean on the changed `src` files (the two test files report
  the same pre-existing errors as at `e960414`, one fewer in
  `test_dual_profile.py`); targeted pytest (`test_dual_profile.py`,
  `test_dual_profile_flag_contract.py`,
  `tests/integration/test_dual_profile_evaluation.py`,
  `test_semantic_lineage_prompts.py`, `test_semantic_validation_contract.py`)
  325 passed; full backend `pytest tests` 3103 passed, 1 failed (`test_stage_runner.py::test_running_stage_observes_durable_cancel_and_acknowledges_it`, a 3 s/5 s thread-wait test in code this stage does not touch, run while cold-32 loaded the host; it and its module pass in isolation, 3 passed).
- Re-verification after integration (main checkout at `c99d198`, before this docs commit): `make lint` rc 0; targeted pytest (the five files above) 325 passed; all 17 prompt hashes equal the Stage 15b table; mutation script re-run on scratch copies of the main checkout's `src` (`/private/tmp/claude-501/-Users-junhuaxu-autoclip-claude/11442fc6-5e35-49d6-afb1-e25ebe8c47b5/scratchpad/stage15c-sim/mutate_main.py`, `mutation_results_main.txt`): 12 of 12 caught, R5b by `test_service_risk_twin_review_diagnostic_counts_downgrades_not_tagged_twins` and the v7 receiver restriction by three tests; offline replay re-run from the main checkout (`/private/tmp/claude-501/-Users-junhuaxu-autoclip-claude/11442fc6-5e35-49d6-afb1-e25ebe8c47b5/scratchpad/stage15c-sim/replay_main.py`, `replay_output_main.txt`) identical to the table above. Deterministic validation only.
- Recovery: v1–v7 artifacts still load; reverting to v7 is a revert of
  `b026c64`. Cached stage outputs are unaffected.
- (Historical next step; Stage 15c was accepted at `b758f71`, cold-32b was
  started there, and Stage 16 followed, above.) Next: independent tester and
  reviewer on the Stage 15c SHAs; the
  continuation run cold-32b on the preserved cold-32 cache (the cold-32
  attempt itself is environment-invalid); human review of the cold-31 and
  earlier renders stays pending.

## Stage 15b: risk-twin review drops selected twins to manual review (routing v7), Stage 15 reviewer P3s (2026-11-04) — ACCEPTED at e960414

- **Accepted** at `e960414b381d6086151f8fe0572feb5d2b8784f9` (code
  `11df4c6`, docs `e960414`): tester PASS: lint rc 0, backend 3101 passed, vitest 80, e2e 4/4, concurrency test 5/5, no sleep; reviewer ACCEPT with nits: no P0–P2, 8 of 9 independent mutations caught (R5b, a service diagnostic computed as `len(sources)`, survived), replay byte-identical, every documented hash matches. Reviewer nits 1–2 become
  Stage 15c (above); nit 3 is an accepted residual. The bullets below are
  the historical implementation record.
- **Status (historical): implemented, pending independent tester and reviewer.** Code,
  prompts and tests in `11df4c61a829dc80f24929013019d6aff88f2d45` on local
  branch `claude/liveclip-stage8-routing` (after `8af759a`); this docs commit
  follows. Not pushed or merged. No evaluator, threshold, benchmark,
  algorithm version (`dual-profile-direct-v1`) or cache-key schema change.
- Stage 15 was **accepted** at `8af759ad2ac9866d9ef08b82fae49136f9cc068f`
  (below). Reviewer P3-a..d are folded into this stage.
- User decision (2026-11-04, after the Stage 15 review): "Add: drop to
  manual review".
- The v6 trade-off, stated precisely (P3-a): risk tags were never shared
  between same-interval twins in any routing version; only gated quality
  flags were. In v3–v5, when a risk-discovery twin carried a gated flag (for
  example the `material_interruption` the risk pass is told to keep), the
  flag union blocked a selected non-risk twin as a side effect; that side
  effect, not any risk rule, was what kept such a twin from automatic
  publication when its own reviews found no risk (a risk twin without a gated
  flag never stopped it). v6 removed the side effect, so a non-risk twin
  whose own reviews raised no risk and no gated flag could be `selected`
  next to a risk twin carrying an automatic-blocking risk tag. Stage 15b
  closes the automatic-publication part of that gap, whether or not the risk
  twin carries a gated flag (so it is stricter than v3–v5 there). The other part
  stays an accepted trade-off: a base twin whose own reviews miss a real
  interior interruption that only the risk pass caught is not blocked by the
  union (it becomes `manual_review` when the risk twin carries an
  automatic-blocking risk tag, as risk-pass records usually do; a human sees
  it before release).
- Routing policy **`quality-gate-risk-routing-v7`** (constant and `Literal`;
  v1–v6 and unmarked artifacts still load). New step 3 of final assembly,
  risk-twin review: a non-risk row (outside the structural `risk_record_ids`)
  that is still `selected` after the twin union, whose identical final
  interval has at least one risk-discovery record carrying an
  `AUTO_BLOCKING_RISK_TAGS` tag (whatever that record's status), becomes
  `manual_review` with the new Python-only prefix
  `"Deterministic risk-twin review: "`, followed by
  `same-interval risk-discovery twin <id> carries <tags>` for each source
  twin (sorted by ID, tags in enum order) and the review's own reason. Risk
  tags and quality flags are not copied (a status downgrade only). Rows
  already `manual_review`, `blocked` or `rejected`, risk records themselves,
  non-identical intervals and non-automatic-blocking tags (for example
  `commercial_claim`) are unaffected. The prefix is in
  `DETERMINISTIC_REASON_PREFIXES` (so `reject_reserved_reason_prefixes`
  refuses it in Global Review and Global Audit output), and the
  `validate_against` reverse check requires a row with this prefix to be
  `manual_review` (every other Python-only prefix except Top-N still requires
  `blocked`).
- Position (decision): after the twin union (step 2) and before Top-N
  (step 4), risk-record routing and the quality gate (step 5). After the
  twin union, so a row that inherits a non-risk twin's gated flag stays
  `blocked` with the quality-gate prefix and only rows still `selected` are
  considered. Before Top-N, so Top-N ranks only rows that already obey the
  rule: it never spends a slot on a downgraded row and never picks a
  replacement that would then be downgraded (the rule's inputs, intervals and
  the risk twins' tags, are not changed by any later step). Step 5 cannot
  touch a downgraded row: risk routing acts on rejected risk records, and the
  quality gate acts on `manual_review` rows with a gated flag, which a
  formerly selected row never carries (`AUTO_BLOCKING_QUALITY_FLAGS` is every
  flag). Downgrade-only and idempotent: on its own output nothing is pending.
- Single helper `risk_twin_review(values, risk_record_ids)` (sources,
  pending, downgraded) with `route_risk_twin_review` applying it; the service
  computes the new run-manifest diagnostic `risk_twin_review_downgrades` (per
  Profile, the number of final rows carrying the prefix) from the final rows
  with the same helper, and `DualProfileRunManifest.validate_against(...,
  risk_record_ids=...)` re-derives it: no `selected` row may still be
  pending, every prefixed row must have an automatic-blocking risk twin, and
  the diagnostic must equal the recomputed count. Manifests written before
  the field load with `{}`; delivery's `validate_against(final)` call (no
  risk membership) still runs the reverse prefix check.
- Code P3-c: the no-op `candidate_id != value.candidate_id` filter in
  `same_interval_twin_flags` is removed (a risk record's own flags are in
  `own` and subtracted anyway; the reviewer's equivalent mutation M5); the
  private `_final_rows` is now the public `final_profile_rows`, reused by the
  service instead of its inline rebuild (same rows, same order).
- Prompts (generic wording; no cue numbers, times, anchor IDs or quoted
  transcript):
  - `boundary_review.md` (P3-b): the on-topic duration test now subtracts
    only "interior material that meets the `material_interruption` threshold
    above (audience chat, comment reading, calls to action or device talk
    that breaks the teaching or claim logic)"; "A brief audience thanks,
    greeting, name call-out or acknowledgement that the speaker passes over
    without leaving the topic is neither flag and is not removed in this
    test". The old list subtracted every greeting and then required
    `padded_with_irrelevant_content` alongside `material_interruption`,
    contradicting the Stage 15 threshold.
  - `main.md` (P3-d): the 167-character microphone/demonstration line is
    re-wrapped (words unchanged); `global_audit.md`'s 166-character
    near-identical line is re-wrapped the same way (its hash changes anyway
    through `main.md`).
- Prompt identity hashes at Stage 15b (full values, printed by
  `load_dual_profile_prompt` / `load_dual_profile_variant_link_prompt` in
  `/private/tmp/claude-501/-Users-junhuaxu-autoclip-claude/11442fc6-5e35-49d6-afb1-e25ebe8c47b5/scratchpad/stage15b-sim/hashes.py`, pinned in `FROZEN_DISCOVERY_PROMPT_HASHES`
  and `PINNED_REVIEW_PROMPT_HASHES`); every stage that loads `main.md`
  changed (bytes only for all but boundary_review), so cold-32 would be cold
  for every stage except the variant link:

  | Profile | Stage | sha256 |
  | --- | --- | --- |
  | short_highlight | discovery | `42f26c40658f26efa7efdc51bbca2b9ae7c82d7e2c6665cf1abd9a80f5cc1ed1` |
  | short_highlight | coverage_audit | `d59f993675d587ac81b902ea0db24a70877dc49048382a4296485ff58fb279a4` |
  | short_highlight | precision_audit (not run) | `5c7445188cbe9d52a52ff50d3c480d8fd45f2ddee0177f7ab0841ae7660e52fa` |
  | short_highlight | precision_confirmation (not run) | `edcc0a5fb314a92937a4c621cc5f1872e2c0780158aa0933528d19d110331d05` |
  | short_highlight | risk_discovery (not run) | `804d156fda48f709d59b0cfe8bc59f0457677798c13ad774ce74307fad67eec5` |
  | short_highlight | boundary_review | `89eb40e58aacd8e0bfdfcb03d3937bb90299659516ff1bc27db35d8c84026b3f` |
  | short_highlight | global_review | `14fc738fcbda816b1ce415540a579504bd605b479639dc6e2c83961f4ff187a4` |
  | short_highlight | global_audit | `d3b000d3910dd4d699741f704810f859d4b8f3aa930e078d41829ed435a1e8b3` |
  | mini_lesson | discovery | `cb37977bbad61c0c1ba64039164bc2c5543e0fd8d14ad44beedc65d9cd4aa84a` |
  | mini_lesson | coverage_audit | `42e2a18413d919ca69989cf39d6b7aca1b5f0f444bfd95a1e77f7fc64685eb8a` |
  | mini_lesson | precision_audit | `d864bcf6bfa50352e6eacec3eb02b84922daccc31877af345acc385f0e9900f8` |
  | mini_lesson | precision_confirmation | `fbfdd8eb99e86f4407b382d4c60defa0d8beb91f8f838755a20f62ecf89d8e92` |
  | mini_lesson | risk_discovery | `6ba50849cc3b3707dc72d6d97333e1e839f3fe34001b7d3daa7531cba793b952` |
  | mini_lesson | boundary_review | `50d3041f34fcbbeca570738ef5e14c8dcccdc07df409fd0379b4b4c1ed340cf9` |
  | mini_lesson | global_review | `99287e4cf343de527b9e56809e528a60224c92bf8b8c6a630007fa610d7968f1` |
  | mini_lesson | global_audit | `509db61a808132aa9662be5fcb72250b2f4000247945d8548504304576337619` |
  | cross_profile | variant_link (unchanged) | `def25b05bd987a293cf74d5f964ca00504d8d247cfd8b1d4af17299289152aef` |

- Tests (changed existing assertions explained):
  - `tests/unit/test_dual_profile.py`: new — selected non-risk twin plus a
    risk twin with automatic-blocking tags → `manual_review`, exact prefixed
    reason (enum tag order), no tag or flag copied, risk twin still blocked by
    risk routing; `manual_review`/`blocked`/`rejected` twins unchanged;
    `commercial_claim` risk twin, an automatic-blocking tag on a non-risk
    twin, and a selected risk record next to a tagged risk record → no
    downgrade; non-identical start or end → no downgrade; twin union first
    (blocked with the quality-gate prefix); Top-N interaction (`top_n=1`: two
    downgraded rows, the clean replacement selected, the next clean row
    Top-N-rejected); helper sources/pending/downgraded, multi-twin reason and
    idempotence; manifest diagnostic default, mismatch, round trip, unbacked
    prefix and pending-row violations; the prefix is refused in model output
    and must be `manual_review`. Changed: the Stage 15 manifest test now also
    sets `risk_twin_review_downgrades` (0); the routing-marker test expects
    v7 and loads v1–v7; the reserved-prefix test lists six prefixes.
  - `tests/integration/test_dual_profile_evaluation.py`: the three marker
    assertions expect v7; `RiskTwinProvider` takes the risk tag. The Stage 15
    service test now uses `commercial_claim` so it isolates the v6 property
    (with `health_advice` the lesson is now `manual_review`, the intended v7
    change); new
    `test_service_risk_twin_review_drops_the_selected_twin_to_manual_review`
    (risk pass: lesson `manual_review` with the prefix, no tags,
    diagnostic `{short 0, mini 1}`; base-pass look-alike: blocked by the
    union, diagnostic 0); the Global Review reserved-prefix repair test is
    parametrized with the new prefix; hash pins updated with justification.
  - `tests/unit/test_dual_profile_flag_contract.py`: new test for the
    reconciled Boundary Review duration test (both Profiles).
  - Mutation self-check (`/private/tmp/claude-501/-Users-junhuaxu-autoclip-claude/11442fc6-5e35-49d6-afb1-e25ebe8c47b5/scratchpad/stage15b-sim/mutate.py`, scratch copies of
    `src` only): 12 of 12 behavioural mutations caught (rule after Top-N,
    before the union, any risk tag, any source, risk receivers, block instead
    of manual_review, validator skips pending, validator skips backing,
    service diagnostic zero, no reverse status check, tags copied, prefix not
    reserved); the P3-c revert passes every test (equivalent, as intended).
- Offline replay (`/private/tmp/claude-501/-Users-junhuaxu-autoclip-claude/11442fc6-5e35-49d6-afb1-e25ebe8c47b5/scratchpad/stage15b-sim/replay.py`, adapted from the Stage 15
  replay: the real v7 assembler and the strict evaluator on stored stage
  outputs; the v6 baseline is the same code with the risk-twin review step
  replaced by the identity; no tracked edit, no model call; the v7 manifest
  cross-check, including both diagnostics, ran on every run):

  | Run | v6 replay | v7 replay | v6→v7 status changes | `risk_twin_flags_not_propagated` (short/mini) | `risk_twin_review_downgrades` (short/mini) |
  | --- | --- | --- | --- | --- | --- |
  | cold-27 | PASS 95.0 | PASS 95.0, short 8/8, mini 5/6 | none | 0 / 3 | 0 / 0 |
  | warm-28 | FAIL 95.0 (`irrelevant_padding`) | FAIL 95.0 (`irrelevant_padding`), short 8/8, mini 5/6 | none | 0 / 3 | 0 / 0 |
  | warm-29b | PASS 95.0 | PASS 95.0, short 8/8, mini 5/6 | none | 0 / 3 | 0 / 0 |
  | cold-30 | FAIL 92.5 (`missing_any_p0_mini_lesson`) | FAIL 92.5, short 7/8, mini 5/6 (L02–L05, L07) | none | 0 / 3 | 0 / 0 |
  | cold-31 | PASS 92.5 | PASS 92.5, short 7/8 (S03 miss), mini 5/6 (L01–L05), N08 informational | none | 0 / 4 | 0 / 0 |

  Every evaluator field (status, score, hits, hard failures, risk and
  negative-anchor findings, human-review list) is identical between the v6
  and v7 replays. In every run, 15–25 mini non-risk rows share an interval
  with a risk-discovery twin carrying an automatic-blocking tag, but none is
  `selected` (all are `manual_review`, `blocked` or `rejected` already), and
  no short row has such a twin, so the rule downgrades nothing in these
  stored outputs. Routing evidence only, not a benchmark pass.
- Self-check: `make lint` rc 0; targeted pytest (`test_dual_profile.py`,
  `test_dual_profile_flag_contract.py`,
  `tests/integration/test_dual_profile_evaluation.py`,
  `test_semantic_lineage_prompts.py`, `test_semantic_validation_contract.py`)
  322 passed; `pytest -k "dual_profile or delivery or benchmark"` 557
  passed.
- (Historical next step; Stage 15b accepted at `e960414`, cold-32 started
  there, and Stage 15c, above, followed.) Independent tester and reviewer on
  the Stage 15b SHAs, then a fresh cold run (cold-32) only with the user's
  go-ahead; human review of the cold-31 and earlier renders stays pending.

## Stage 15: risk-twin flags not propagated (routing v6), `material_interruption` threshold, self-promotion rule (2026-11-04) — ACCEPTED at 8af759a

- **Accepted** at `8af759ad2ac9866d9ef08b82fae49136f9cc068f` (code
  `289530e`, docs `8af759a`). Tester PASS: lint rc 0; `make test` backend
  3087 passed; vitest 80; e2e 4/4; concurrency test 5/5; no sleep.
  Reviewer ACCEPT with nits (no P0–P2; 8 mutation checks, 7 caught and 1
  equivalent; replay byte-identical; every documented hash matches). The P3
  nits become Stage 15b (above). The bullets below are the historical
  implementation record.
- **Status (historical): implemented, pending independent tester and reviewer.** Code,
  prompts and tests in `289530eba3b59f89325ede5c268f9064f8cb5257` on local
  branch `claude/liveclip-stage8-routing` (after `867d1cf`); this docs commit
  follows. Not pushed or merged. No evaluator, threshold, benchmark,
  algorithm version (`dual-profile-direct-v1`) or cache-key schema change.
- User decisions (2026-11-02/04, after cold-31 below): (1) routing option
  "Ignore risk-twin tags"; (2) restore the `material_interruption` threshold
  that Stage 14/14b over-broadened; (3) a candidate whose central objective
  is self-promotion is rejected.
- Routing policy **`quality-gate-risk-routing-v6`** (constant and `Literal`;
  v1–v5 and unmarked artifacts still load). In the same-interval twin flag
  union (step 2 of final assembly), records of the dedicated risk-discovery
  pass (structural `risk_record_ids`, taken from the risk-discovery pass
  outputs, never from ID prefixes) are no longer flag SOURCES. A risk record
  keeps its own flags and status and still RECEIVES the gated flags of its
  non-risk twins (conservative); non-risk twins share flags with each other
  exactly as in v3–v5, with the same "Deterministic quality gate: " prefix.
  Risk-record routing (rejected or Top-N-excluded risk records retained as
  `blocked`) and Discovery structural flag persistence are unchanged.
  Rationale: the risk pass is instructed to preserve interior interruptions
  of a risk chain and flag them so the record is routed to `blocked`; that
  routing intent is not a finding the base twin's own Boundary and Global
  Review must inherit.
- Single shared helper `same_interval_twin_flags(values, risk_record_ids)`
  (in `src/liveclip/pipeline/dual_profile.py`) is used by final assembly, by
  the service to compute the new run-manifest diagnostic
  `risk_twin_flags_not_propagated` (per Profile: the number of
  (candidate, gated flag) pairs that only risk-discovery twins carried and
  that were therefore not propagated), and by
  `DualProfileRunManifest.validate_against(..., risk_record_ids=...)`, which
  the service now calls with the structural risk membership: the final
  arrays must leave nothing to inherit under the v6 rule and the diagnostic
  must equal the recomputed count. The helper is idempotent on its own
  output. Manifests written before the field load with `{}`; delivery's
  `validate_against(final)` call (no risk membership) is unchanged. No
  other validator, audit payload or diagnostic assumed full twin symmetry.
- Prompts (generic wording; no cue numbers, times, anchor IDs or quoted
  transcript):
  - `main.md` (shared by every stage): "Interior content counts as
    `material_interruption` only when it actually breaks the teaching or
    claim logic; a brief audience thanks, greeting, name call-out or
    acknowledgement that the speaker passes over without leaving the topic
    is neither an interruption nor padding." The Stage 14 rules stay
    (padding = edge only; unrelated interior content is the interior flag;
    the brief live-demo equipment remark is part of the demonstration).
  - `risk_discovery.md`, `coverage_audit.md`: the same sentence mirrored;
    "flag each interior interruption that breaks the claim logic as
    `material_interruption` …"; risk_discovery's greeting-between-question-
    and-count paragraph now says "Mark an interruption only when it breaks
    the claim logic … and in either case keep the complete chain" (was "Mark
    the interruption").
  - `precision_audit.md`: "Greetings inside that chain are quality evidence"
    becomes "never permits dropping the defining opening; flag it only under
    the main contract's `material_interruption` threshold".
  - `boundary_review.md`: its definition now reads "breaks the teaching or
    claim logic" and lists the brief passed-over acknowledgement among
    non-interruptions; the Stage 14c audibility cross-reference is kept.
    `global_review.md` and `global_audit.md` keep their audibility wording
    (consistent: audibility trouble breaks the demonstration) and receive the
    threshold through `main.md`.
  - Self-promotion: `boundary_review.md` (set `central_objective_complete`
    to false, keep evidenced `commercial_claim`, say so in `review_reason`;
    never trim it into a teaching clip; clearing a padding flag does not
    resolve it), `global_review.md` (mark `rejected`, a risk-discovery
    record is retained `blocked`; not merely flagged or `manual_review`) and
    `global_audit.md` (replace such a kept candidate as `rejected`): a
    candidate whose central objective is the speaker's own credentials,
    qualifications, pricing, course sales or schedule is not a teaching or
    highlight unit, even when no explicit purchase prompt appears; a brief
    credential or course mention inside a real lesson does not make that
    lesson self-promotion.
- Prompt identity hashes at Stage 15 (full values, printed by
  `load_dual_profile_prompt` / `load_dual_profile_variant_link_prompt`,
  pinned in `FROZEN_DISCOVERY_PROMPT_HASHES` and
  `PINNED_REVIEW_PROMPT_HASHES`); every stage that loads `main.md` changed
  (only the variant link, which does not load it, is unchanged), so cold-32
  is a cold run:

  | Profile | Stage | sha256 |
  | --- | --- | --- |
  | short_highlight | discovery | `b1d4d8785d1a1076f7faf287322bbfd4a0e8b60cc7d54a952e39df81200e2fb0` |
  | short_highlight | coverage_audit | `152554adb34d813306c9bb367121e11ea3eb6bf5dbe59f26c78a8b6bba930f88` |
  | short_highlight | precision_audit (not run) | `4a780e95388c5006fdb15ab4e3453a4a55a178a8cf18dfb6ab9a7cac4e8e6a15` |
  | short_highlight | precision_confirmation (not run) | `2b9ccdb7452def45a8324d1f531ac20e63293cded9d2a93ba0565a452e0b5bd5` |
  | short_highlight | risk_discovery (not run) | `d99432948d5f8ebbd92164bc7a33b2998ebef923d4be6e36557fd4eacda8cd38` |
  | short_highlight | boundary_review | `a8a541a17cc46a96c00bf31133604ce146a2a7db3fd202283b0b506f75822cae` |
  | short_highlight | global_review | `a516005061a596684ba18b91fe11be44ae75534fa47488106acb902b6f283700` |
  | short_highlight | global_audit | `c5a26dadf1d5cf54e81c4fae1f279aefe8a356fe4ccb3377aab08e2b766dcaea` |
  | mini_lesson | discovery | `00c58be1b0fae7dffdb7c5f6b63e1839dacd3f5d53d5a6efbf979cf282708a80` |
  | mini_lesson | coverage_audit | `460e83b9b9bdac197cb4ec4c1b91fd5fe4c279ccbf1f9bc8028660bb247375e8` |
  | mini_lesson | precision_audit | `56a4154c06e390d80ddd6aca97b7fe9512102abd93a8dfe368cfb1e1fa7873d5` |
  | mini_lesson | precision_confirmation | `00440c52138d423abaaa565e8981037b2cf6e1577b689b62ed274fe9e37b3db2` |
  | mini_lesson | risk_discovery | `4066e60cd6f6028e0245a207e5dbb41797dafef12e73e56a89778907467de3f7` |
  | mini_lesson | boundary_review | `678c8d7ece250ea28f0bfbea8298020c779eb8e749e4c5155516173035cf51c2` |
  | mini_lesson | global_review | `e7d615f5f9b61f6b55bfb6222d0895c50f17486fb1595c3ae08f222b485f6ccb` |
  | mini_lesson | global_audit | `c3ff60041f124dd337585541006bf78cf3f05cd5b462f2e33ab5812a74f95e76` |
  | cross_profile | variant_link (unchanged) | `def25b05bd987a293cf74d5f964ca00504d8d247cfd8b1d4af17299289152aef` |

- Tests (changed existing assertions explained):
  - `tests/unit/test_dual_profile.py`: Stage 9's
    `test_risk_record_twin_shares_flags_and_stays_blocked` is replaced by
    `test_risk_record_twin_keeps_its_flags_but_is_not_a_flag_source` (the
    base twin now stays `manual_review` without the risk twin's
    `topic_switch_inside`; the risk twin still keeps the flag and its
    "Deterministic risk routing: " block) — the intended v6 behaviour change.
    New: L02 shape (clean base, risk twin with a Discovery
    `material_interruption` persisted after a Boundary Review extension to
    the identical interval: base stays `manual_review`, risk twin blocked);
    non-risk twin still propagates and blocks next to a risk twin (which also
    receives the flag); risk twin receives a non-risk twin's flag; helper
    counts, advisory flags never shared, idempotence, and the v3–v5
    symmetric rule without risk records; manifest diagnostic default,
    mismatch, round trip and v6-rule violation. The routing-marker test now
    expects v6 and loads v1–v6.
  - `tests/integration/test_dual_profile_evaluation.py`: the two Stage 13/14
    marker assertions expect v6; new service test
    `test_service_twin_union_ignores_risk_pass_sources_structurally`
    (risk-pass twin: lesson stays `selected`, diagnostic `{short 0, mini 1}`;
    the same twin from the base pass under a `risk_` look-alike ID still
    blocks the lesson, diagnostic 0); hash pins updated with justification.
  - `tests/unit/test_dual_profile_flag_contract.py`: the Stage 14b
    risk_discovery/coverage_audit interior-rule strings now include "that
    breaks the claim logic"; new tests for the threshold sentence in every
    stage (and in the risk_discovery/coverage_audit stage text itself), the
    Boundary Review definition, and the self-promotion rule in
    boundary_review/global_review/global_audit.
- Offline replay (new scratch folder
  `/private/tmp/claude-501/-Users-junhuaxu-autoclip-claude/11442fc6-5e35-49d6-afb1-e25ebe8c47b5/scratchpad/stage15-sim/replay.py`,
  adapted from the cold-31 and L01 analysis simulators: the real v6
  assembler and the strict evaluator on stored stage outputs; a v5 baseline
  is the same code with every twin treated as a source; no tracked edit, no
  model call; the v6 manifest cross-check ran on every run):

  | Run | Stored | v5 replay | v6 replay | v5→v6 status changes | risk-twin diagnostic (short/mini) |
  | --- | --- | --- | --- | --- | --- |
  | cold-27 | PASS 95.0 | PASS 95.0 | PASS 95.0, short 8/8, mini 5/6 | `ml14_nasal_problem_full` blocked→manual_review | 0 / 3 |
  | warm-28 | FAIL 95.0 | FAIL 95.0 (`irrelevant_padding`) | FAIL 95.0 (`irrelevant_padding`), short 8/8, mini 5/6 | `ml14_nasal_problem_full` blocked→manual_review | 0 / 3 |
  | warm-29b | PASS 95.0 | PASS 95.0 | PASS 95.0, short 8/8, mini 5/6 | `ml14_nasal_problem_full` blocked→manual_review | 0 / 3 |
  | cold-30 | FAIL 92.5 | FAIL 92.5 | FAIL 92.5 (`missing_any_p0_mini_lesson`), short 7/8, mini 5/6 (L02–L05, L07) | none | 0 / 3 |
  | cold-31 | FAIL 87.5 | FAIL 87.5 | **PASS 92.5**, short 7/8 (S03 miss), mini 5/6 (L01–L05) | `ml6_steps1to4_curriculum` and `audit_regional_nasal_hard_to_fix` blocked→manual_review | 0 / 4 |

  Status, score, hits, hard failures and negative-anchor findings of the
  four earlier runs are unchanged versus the v5 replay; the only evaluator
  delta there is one more `manual_review` row in the human-review list. In
  cold-31 the R02 match (`audit_regional_nasal_hard_to_fix`, a
  coverage-audit record) becomes `manual_review` (allowed; it was
  `manual_review` in cold-27/warm-28/warm-29b as well); R01 stays blocked;
  every risk-discovery record keeps its status; N08
  (`sh_0015_teacher_cert_verify`, manual_review) stays an informational
  finding because the replay reuses cold-31's stored review outputs (the
  self-promotion prompt can act only in a new run). Routing evidence only,
  not a benchmark pass: the prompts changed and a real run re-decides every
  stage. (Stage 15b reconciliation, reviewer P3-d: cold-30 stays FAIL 92.5
  here although the Stage 14 counterfactual gave PASS 97.5 because this
  replay keeps the stored Global Audit replacement that blocked the L01 row
  "to match routing", and Python only ever downgrades, whereas the Stage 14
  counterfactual reverted such rows to the initial Global Review.)
- Self-check: `make lint` rc 0; targeted pytest (`test_dual_profile.py`,
  `test_dual_profile_flag_contract.py`,
  `tests/integration/test_dual_profile_evaluation.py`,
  `test_semantic_lineage_prompts.py`, `test_semantic_validation_contract.py`)
  308 passed.
- (Historical next step; Stage 15 accepted at `8af759a`, and Stage 15b,
  above, followed.) Next: independent tester and reviewer on the Stage 15
  SHAs, then a fresh cold run (cold-32) only with the user's go-ahead; human
  review of the cold-31 and earlier renders stays pending.

## cold-31 real run at 867d1cf (2026-11-02) — strict FAIL 87.5 (fresh cold acceptance attempt)

- Fresh cold run, real Claude CLI at `867d1cf` (pinned 2.1.308, attempt
  start epoch 1793609949, single segment): eval rc 0 in 3778 s; 242 provider
  records (Discovery 160 calls, Boundary Review 56 plus 3 repairs, Global
  Review/Audit 22, variant link 1), 0 retries, no rate-limit marker;
  `cache_hits` 0; tokens in 11,130,783 / out 1,116,524; 239 new cache files,
  0 content-identical to any of 25 earlier cache roots; every recorded prompt
  hash equals the Stage 14c table below (0 mismatches). Routing
  `quality-gate-risk-routing-v5`.
- Strict **FAIL 87.5** (`missing_any_p0_mini_lesson`: L02). Short 7/8 (S03
  missed: the retained representative starts +12440 ms, outside tolerance,
  as in cold-30). Mini 4/6: L01, L03, L04, L05 hit; **L02 missed by the
  Stage 9 twin union** (below); L07 missed (representative choice variance:
  the Global Audit re-pointed the cluster to a 2832–2927 representative;
  the gold-exact interval existed after Boundary Review in every run; hit
  only in cold-30). R01 and R02 blocked; all 9 N07-overlapping candidates
  blocked; N08 `sh_0015_teacher_cert_verify` (a short clip about the
  speaker's own teaching credentials) `manual_review` — informational under
  the evaluator's negative-anchor policy (no hard failure, no score effect).
  11 renders rc 0, automatic checks pass; human editorial/audio review
  pending. Roots
  `data/evaluations/dual-profile-{benchmark,cache,strict-eval}-20261102-claude-cold-31`;
  evidence (`twin-gate.txt`, `trails-extra.txt`, `diagnostics.txt`, …) in
  `data/evaluations/dual-profile-strict-eval-20261102-claude-cold-31/evidence/`.
- Analysis (read-only reviewer; offline replays, no model calls): the exact
  L02 base candidate `ml6_steps1to4_curriculum` (cues 825–939) was clean
  through Discovery, Boundary Review and Global Review (`manual_review` 78)
  and was blocked only by the same-interval twin union, which copied
  `material_interruption` from its risk-discovery twin
  `risk_steps1to4_through_mix_switch` (Discovery flag over a one-cue viewer
  thank-you, kept by its Boundary Review, which extended the interval to the
  identical one). The base twin's own reviews judged that cue harmless.
  Replays: v5, v4 and no-persistence all FAIL 87.5; "v5 with the union
  ignoring risk-record sources" PASS 92.5 (2 rows change in cold-31; cold-27,
  warm-28, warm-29b, cold-30 unchanged). Prompt attribution (n=1, "made more
  likely", not proven): after Stage 14/14b wording, Discovery
  `material_interruption` counts rose (mini 55–60 → 76, short 15–20 → 32)
  while padding flags fell, because `main.md` and the risk/coverage passes
  named every interior interruption without Boundary Review's "actually
  breaks the teaching logic" threshold. N08: no flag covered a clip whose
  central objective is self-credentialing, so Boundary Review dropped the
  padding flag.
- User decisions → Stage 15 (above).

## Stage 14c: Stage 14b reviewer REJECT follow-ups (2026-11-02) — ACCEPTED at 867d1cf

- **Accepted** at `867d1cf669ffb9d8eccce40ba97d84fd44e016ef`. Tester PASS:
  lint rc 0; backend 3056 passed; vitest 80; e2e 4; concurrency test 5/5;
  no sleep. Reviewer ACCEPT with nits. cold-31 (above) ran at this SHA. The
  bullets below are the historical implementation record.

- **Stage 14b reviewer verdict: REJECT** on the docs commit
  `66265e2e79d36a08e98e46c857ae71a490da2049` (P2, docs only): the Stage 14b
  hash table below listed intermediate-draft values for global_review and
  global_audit (both Profiles). The code at `9664efe` was not at fault;
  `66265e2` changed no code. Reviewer P3 nits on `boundary_review.md` are
  folded into this stage so cold-31 tests the final wording.
- **Status (historical): implemented, pending independent tester and reviewer** in the
  Stage 14c commit on local branch `claude/liveclip-stage8-routing` (after
  `66265e2`). Not pushed or merged. Routing policy stays
  `quality-gate-risk-routing-v5`; no Python routing, evaluator, threshold,
  benchmark, algorithm version (`dual-profile-direct-v1`) or cache-key schema
  change; gate semantics unchanged.
- `boundary_review.md` (generic wording, no cue numbers, times or anchor
  IDs):
  - the `material_interruption` definition now cross-references that
    interior audibility checks, connection lag and playback trouble are such
    unrelated content and count as `material_interruption`;
  - interior chat, calls to action, greetings or device talk kept only for
    duration: flag `padded_with_irrelevant_content` alongside
    `material_interruption` (or `topic_switch_inside`), never instead of it
    (consistent with `main.md` "may accompany, never replace").
- New test `test_review_stage_prompt_identities_match_pins`
  (`tests/integration/test_dual_profile_evaluation.py`) pins the full
  service-recorded identity hash (`load_dual_profile_prompt(...).sha256`, as
  recorded in `prompt_hashes`) of boundary_review, global_review and
  global_audit for both Profiles, plus the variant link
  (`load_dual_profile_variant_link_prompt().sha256`); the Discovery-family
  pins stay in `FROZEN_DISCOVERY_PROMPT_HASHES`. Verified by a temporary
  revert of `boundary_review.md` (test fails), then restored.
- Prompt identity hashes at Stage 14c (full values, recomputed with
  `load_dual_profile_prompt` / `load_dual_profile_variant_link_prompt`):

  | Profile | Stage | sha256 |
  | --- | --- | --- |
  | short_highlight | discovery | `c3b728702f3c25228c3cb74eac3385e62c98c3902a72138460e695ead301d00e` |
  | short_highlight | coverage_audit | `09fcecd9dfbdbf7e99178a7be2c0a791cce9c98ec6c0de674c94407165fbfda5` |
  | short_highlight | precision_audit (not run) | `1c65af1b172ce5211f4e26e8c3718e11dfea112a436e2687224c9e8de81af967` |
  | short_highlight | precision_confirmation (not run) | `8bdbe2f65704db36efa6d3fead5c49fec1618431391047ac1c70e13aca716bd4` |
  | short_highlight | risk_discovery (not run) | `12244a54202e4a167804cbf890b38c852f2988add221bffe24158bccb2bb5e2d` |
  | short_highlight | boundary_review (changed in 14c) | `2ac809c282ca5fd8e4b18030e09d8798084e3854ccaf93710d73a5277c009a8e` |
  | short_highlight | global_review | `d2bf9404377dc32f882e4b8a57cff9d3c98520f135fd0f78525b26b7f094da53` |
  | short_highlight | global_audit | `51885f0f5a34d45d3d506869a3a492b9fa1be00c0357d20af834f6d1b30441c3` |
  | mini_lesson | discovery | `7500e47a912db6855186843d799c62c7c2935920c1b1b84c8f2e7382c54fc75b` |
  | mini_lesson | coverage_audit | `407c2c9d68f0f722e9efd8974d2cd4aa5418f89fb9b151b80ba641903e50c994` |
  | mini_lesson | precision_audit | `0377c54e8cc0e74fe0645d7192cd402d85129fdaa6e5e9fc29e9583e24f8b0aa` |
  | mini_lesson | precision_confirmation | `17eccbac257c129aa42979c008ec8ff83cc536ae2bfb0e38fa43b27b0a370024` |
  | mini_lesson | risk_discovery | `7e9af46465b7b4319b00988ef7709e4e89aa68dec12263dcf536e9b9d25bab46` |
  | mini_lesson | boundary_review (changed in 14c) | `b1c10a166b90821f2695bf225319bf504a02e91a208a9e8b1f304d58bb0f798f` |
  | mini_lesson | global_review | `42f5a0bf8163ed72926f71a452d164e50821d3694f5ff92b5e2d47500d32682a` |
  | mini_lesson | global_audit | `7740969edf51653bf251a59c26a4997f55f8fed0d33593ea122dc4837fa88cde` |
  | cross_profile | variant_link | `def25b05bd987a293cf74d5f964ca00504d8d247cfd8b1d4af17299289152aef` |

  "Not run": the service loads precision_audit, precision_confirmation and
  risk_discovery only for Mini Lesson, so those Short Highlight values are
  never recorded in a run's `prompt_hashes`. Only boundary_review changed
  versus Stage 14b (Short `b4c4e88a…` -> `2ac809c2…`, Mini `c9cad7b3…` ->
  `b1c10a16…`); cold-31 is cold for every stage regardless (Stage 14).
- Self-check: `make lint` rc 0; targeted pytest (`test_dual_profile.py`,
  `test_dual_profile_flag_contract.py`,
  `tests/integration/test_dual_profile_evaluation.py`,
  `test_semantic_lineage_prompts.py`, `test_semantic_validation_contract.py`)
  277 passed.
- (Historical next step; Stage 14c accepted and cold-31 ran, above.)
  Next: independent tester and reviewer on the Stage 14c SHA (covering
  Stage 14b `9664efe` too), then the fresh cold run cold-31 only with the
  user's go-ahead; human review of the cold-30 and earlier renders stays
  pending.

## Stage 14b: Stage 14 reviewer P3 follow-ups (2026-11-02) — REJECTED (P2 docs hashes); fixed in Stage 14c

- **Reviewer REJECT** on docs commit `66265e2` (P2): the hash table below
  listed wrong global_review/global_audit values; corrected in place by
  Stage 14c (see above). The bullets below are the historical
  implementation record.

- **Status (historical): implemented, pending independent tester and reviewer** in
  `9664efe5b14c410984e452e339b7c245db480e14` (prompts and tests) on local
  branch `claude/liveclip-stage8-routing`, after the Stage 14 docs commit
  `2c088fe`; this docs commit follows. Not pushed or merged. Routing policy
  stays `quality-gate-risk-routing-v5`; no Python routing, evaluator,
  threshold, benchmark, algorithm version (`dual-profile-direct-v1`) or
  cache-key schema change. Gate semantics are unchanged: every flag the
  new wording names is gated.
- Prompt alignment with `main.md` ("padding flags describe EDGE material
  only"):
  - `boundary_review.md`, `global_review.md`, `global_audit.md`: audibility
    checks, connection lag and network or playback trouble are padding at an
    edge of the interval; inside the interval, between on-topic cues, they
    are `material_interruption`, and a padding flag may be added alongside
    that interior flag, never used instead of it (replaces "padding (and an
    interruption when they split a demonstration)"). The speaker's brief
    equipment/listening explanation attached to an immediate live example
    stays part of the demonstration, neither padding nor an interruption.
    This matches Boundary Review's existing interior-chat rule
    (`padded_with_irrelevant_content` when only off-topic material meets the
    Profile minimum).
  - `risk_discovery.md`, `coverage_audit.md`: interior sales, greeting,
    device or topic interruptions of a risk chain are flagged
    `material_interruption` (or `topic_switch_inside` when another topic
    starts inside the chain); padding flags describe edge material only and
    may accompany, never replace, the interior flag (replaces "attach the
    corresponding quality flags").
  - Wording stays generic (no cue numbers, times or anchor IDs).
- Prompt hashes at `9664efe` (full values pinned in tests; corrected by
  Stage 14c: the `66265e2` draft of this list gave global_review
  `879ae319…`/`0b2c6031…` and global_audit `3011be92…`/`dcb20886…`, which are
  not the service-recorded values):
  - Changed, Short Highlight: coverage_audit `09fcecd9…`, risk_discovery
    `12244a54…` (not run for this Profile), boundary_review `b4c4e88a…`,
    global_review `d2bf9404…`, global_audit `51885f0f…`.
  - Changed, Mini Lesson: coverage_audit `407c2c9d…`, risk_discovery
    `7e9af464…`, boundary_review `c9cad7b3…`, global_review `42f5a0bf…`,
    global_audit `7740969e…`.
  - Unchanged versus Stage 14: discovery (short `c3b72870…`, mini
    `7500e47a…`), precision_audit (short `1c65af1b…`, mini `0377c54e…`),
    precision_confirmation (short `8bdbe2f6…`, mini `17eccbac…`) and the
    variant link (`def25b05…`). Stage 14 already changed every stage hash,
    so cold-31 is cold for all stages regardless.
- Tests: `test_prompts_name_interior_interruptions_and_keep_padding_flags_at_the_edges`
  (five stages x two Profiles); integration
  `test_padding_only_discovery_flags_validate_like_an_unflagged_candidate`
  (representative rule, blocked duplicate, near-identical pair fallback
  keep order): a candidate whose only Discovery gated flags are padding
  (Boundary Review cleared, no trim) has an empty persisted set and an
  identical audit-repair, fallback, diagnostic and final mini result to an
  unflagged candidate, while a structural flag changes the result. It fails
  when `discovery_persisted_flags` persists every gated flag (v4 shape;
  verified by a temporary mutation, then restored).
- Self-check: `make lint` rc 0; targeted pytest (`test_dual_profile.py`,
  `test_dual_profile_flag_contract.py`,
  `tests/integration/test_dual_profile_evaluation.py`, prompt contract
  tests) 276 passed.
- Next (historical; superseded by Stage 14c above): independent tester and
  reviewer on the Stage 14b SHA, then the fresh cold run cold-31 only with
  the user's go-ahead; human review of the cold-30 and earlier renders stays
  pending.

## Stage 14: padding flags follow Boundary Review (2026-11-01) — ACCEPTED at 2c088fe

- **Accepted** at `2c088fe1af349cb4a93502fe10a5ba8769ef9183` (code
  `fc31907`, docs `2c088fe`). Tester PASS: lint rc 0; `make test` backend
  3042 passed; vitest 80; e2e 4/4; concurrency test 5/5; no sleep.
  Reviewer ACCEPT with nits (no P0–P2); the reviewer's replay reproduced
  cold-27 PASS 95.0, warm-28 FAIL 95.0 (unchanged), warm-29b PASS 95.0,
  cold-30 PASS 97.5 (routing evidence only). The P3 nits become Stage 14b.
  The status bullet below is the historical implementation record.

- cold-30 (fresh cold run, real Claude CLI at `194ba65`, pinned 2.1.308,
  attempt start epoch 1793597156; acceptance attempt): eval rc 0;
  `cache_hits` 0; 231 calls (Discovery family 158, Boundary Review 52,
  Global Review/Audit 20, variant link 1) plus 3 Boundary Review repairs,
  0 retries, no rate-limit marker; tokens in 10,899,690 / out 1,085,708;
  0 content-identical cache files versus 24 earlier cache roots. Strict
  **FAIL 92.5** (`missing_any_p0_mini_lesson`): short 7/8 (S03 start
  +12440 ms outside tolerance); mini 5/6: L01 missed only because Discovery
  padding-flag persistence blocked the exact candidate
  `precision_ml_0005_breathy_mix_vs_leak_vs_breathy_voice` (cues 690–746),
  and L07 hit for the first time
  (`confirm_high_note_nasal_loop_through_rhinitis_qualification`); R01 and
  R02 blocked; all 8 N07-overlapping candidates blocked or rejected. 12
  renders rc 0, automatic checks pass; human review pending. Roots
  `data/evaluations/dual-profile-{benchmark,cache,strict-eval}-20261101-claude-cold-30`;
  evidence in
  `data/evaluations/dual-profile-strict-eval-20261101-claude-cold-30/evidence/`.
- L01 chain in cold-30: the precision_audit Discovery pass raised
  `device_or_waiting_padding` for cues 694–698 (a brief remark about having
  no sound card and moving closer right before a live vocal demonstration);
  Boundary Review cleared it explicitly without trimming; the initial
  Global Review kept it `manual_review` (80); the Global Audit, seeing
  `persisted_discovery_gated_flags=[device_or_waiting_padding]`, replaced
  the row with `blocked` "to match routing"; v4 persistence would have
  blocked it anyway. The microphone/demonstration exception lived only in
  `stages/discovery.md` and `stages/boundary_review.md`; the
  precision_audit, risk_discovery and coverage_audit passes never loaded it.
- Reviewer replay analysis (read-only, real assembler and strict evaluator
  on stored stage outputs of cold-27, warm-28, warm-29b, cold-30): padding
  flags were the sole blocker on 9 persisted rows, all overlapping gold
  (S04/L01, R01, L07), none overlapping a negative anchor; every true
  padding case was also gated by Boundary or Global Review itself.
  Structural persistence produced the only true positives (the N07
  `topic_switch_inside` short row in warm-28/warm-29b). Policy "structural
  flags persist, padding flags follow Boundary Review" predicted cold-27
  PASS 95.0, warm-28 FAIL 95.0 (unchanged; its mini N07 padding row is
  covered by the Stage 13 pair audit, not persistence), warm-29b PASS 95.0,
  cold-30 PASS 97.5 (L01 hit, mini 6/6).
- User decision (2026-11-01): option "Padding follows BR + prompt" →
  Stage 14.
- (Historical; accepted above.) **Status: implemented, pending independent
  tester and reviewer**. Code, prompts and tests in `fc31907266ee07485567580f5b125ced76775cfe`; this docs commit follows. Not pushed or
  merged. No evaluator, threshold, benchmark, algorithm version
  (`dual-profile-direct-v1`) or cache-key schema change.
- Routing policy `quality-gate-risk-routing-v5`: Discovery flag persistence
  applies only to `PERSISTED_STRUCTURAL_GATED_FLAGS`
  (`material_interruption`, `topic_switch_inside`, `topic_not_closed`,
  `asr_uncertain_blocks_meaning`), still unless Boundary Review shrank an
  edge, still with the reason prefix "Deterministic flag persistence: ".
  `PADDING_GATED_FLAGS` (`device_or_waiting_padding`,
  `sales_or_cta_padding`, `padded_with_irrelevant_content`) are not
  persisted; they follow Boundary Review and any flag Global Review or the
  audit sets, and still gate when kept. The two classes partition
  `MANUAL_REVIEW_BLOCKING_QUALITY_FLAGS` exactly (checked at import; no
  gated flag is in neither class). `discovery_persisted_flags` remains the
  single function behind final assembly, the audit payload
  `persisted_discovery_gated_flags`, the persisted-flag representative rule,
  the pair fallback keep order and the manifest diagnostic. v1–v4 and
  unmarked artifacts still load.
- Prompts: the shared `main.md` (loaded by every Discovery pass and by
  Boundary Review) now states the microphone/demonstration rule and that
  padding flags describe edge material only (unrelated interior content is
  `material_interruption` or `topic_switch_inside`;
  `padded_with_irrelevant_content` may be added when only off-topic material
  meets the Profile minimum, never instead of the interior flag). The
  duplicate sentence in `stages/discovery.md` is removed; the richer
  Boundary Review wording stays. `global_review.md` and `global_audit.md`
  say that only structural Discovery flags persist and that a candidate is
  not blocked "to match routing" for a padding flag Boundary Review cleared.
  Every stage prompt hash changed (cold cache for all stages; Stage 14b,
  above, later changed coverage_audit, risk_discovery, boundary_review,
  global_review and global_audit again):
  - Short Highlight: discovery `c3b72870…`, coverage_audit `e98ed2f7…`,
    precision_audit `1c65af1b…`, precision_confirmation `8bdbe2f6…`,
    risk_discovery `eba1cd91…`, boundary_review `db074ead…`, global_review
    `b84f4e82…`, global_audit `f60fcde6…`.
  - Mini Lesson: discovery `7500e47a…`, coverage_audit `edf10867…`,
    precision_audit `0377c54e…`, precision_confirmation `17eccbac…`,
    risk_discovery `bb219de4…`, boundary_review `c40eadb0…`, global_review
    `cf624569…`, global_audit `bb1a3e32…`.
  - Variant link unchanged (`def25b05…`).
- CLI P3: the bounded exhaustion summary now includes the exception notes
  (for example "failure evidence could not be written: …", truncated to 160
  characters) when the evidence writer itself failed.
- Offline replay (the reviewer's simulator against the Stage 14 code, no
  tracked file touched, no model call): identical to the predicted policy:
  cold-27 PASS 95.0, warm-28 FAIL 95.0 (`irrelevant_padding`,
  `ml0007_strong_mix_vs_yanyin_core`, unchanged), warm-29b PASS 95.0,
  cold-30 PASS 97.5 (L01 hit, mini 6/6). Counterfactual caveats from the
  analysis apply (Global Review/Audit rows written because of persistence
  are reverted to the initial review; a real run re-decides the L07 pair
  group and the prompts changed, so this is routing evidence only, not a
  benchmark pass).
- (Historical next step; the tester and reviewer accepted Stage 14 at
  `2c088fe`, above.) Next: independent tester and reviewer on the Stage 14
  SHA, then a fresh cold run (cold-31) only with the user's go-ahead; human review of the
  cold-30 renders and earlier renders stays pending.

## Stage 13e: Stage 13d reviewer follow-ups (2026-11-01) — ACCEPTED at 194ba65

- **Accepted** at `194ba653b0abd9712bc750eaf2d6aada594a61c3`. Tester PASS:
  backend 3003 passed; vitest 80; e2e 4; concurrency test 5/5. Reviewer
  ACCEPT with an offline cold simulation, no blocker. The status bullet
  below is the historical implementation record.
- (Historical; accepted above.) **Status: implemented, pending independent
  tester and reviewer** on local branch `claude/liveclip-stage8-routing`, one
  code commit (`194ba65`) after the docs commit `7bf1bb7` that accepted Stage 13d and recorded warm-29b. Not pushed
  or merged. Python and tests only (plus wording in `PRODUCT_SPEC.md`): no
  prompt, cache-key, algorithm, evaluator, threshold or benchmark change.
- P2 (reviewer probe as a regression test):
  `test_assembly_only_audit_error_is_repaired_without_the_pair_label`. A
  merged Global Audit whose only failure is final assembly (an ordinary
  overlap pair decided distinct; a selected score at the threshold) must
  raise the assembly error alone and be repaired. Deleting
  `if assembly_error is not None: raise assembly_error` in the merged-audit
  check makes it fail (verified by a temporary deletion, then restored).
- P3 (evidence writer): `run_dual_profile_evaluation` now catches any
  `Exception` from the failure-evidence writer (previously only
  `OSError`/`ValueError`) and attaches it as a note
  (`failure evidence could not be written: <type>: <message>`); the
  validation error always propagates. Test:
  `test_a_failure_evidence_writer_bug_never_replaces_the_validation_error`
  (narrowing the catch again fails it).
- P3 (concurrent exhaustion), fixed: `_resolve_call` records every
  `DualProfileValidationExhaustedError` on the run's resolution audit before
  raising. The executor waits for in-flight units, so when a second unit of
  the same stage exhausts while the first error propagates, the failure
  evidence keeps both: the failure file lists it under
  `concurrent_exhausted_units` (attempts, errors, call records), the partial
  `provider-calls.json` lists completed units, the failing unit, then the
  other exhausted units, and `failure-manifest.json` adds
  `concurrent_failed_subject_ids` (counts and tokens include them).
  Remaining limitation (documented in the docstring and `PRODUCT_SPEC.md`):
  a unit that ends with any other error (cancelled after the first failure,
  or a provider failure) is neither resolved nor exhausted, and its calls
  are not listed. Test:
  `test_concurrently_exhausted_units_both_reach_the_failure_evidence` (two
  Discovery windows meet at a barrier before their regeneration returns;
  removing the record call fails it).
- P3 (wording): the attempt and writer docstrings and the Stage 13d
  `PRODUCT_SPEC.md` amendment now say that only the Claude CLI provider
  drops (and fails) an output containing its subscription account identity;
  other providers have no such filter. A Stage 13e amendment records the
  concurrent-evidence and writer rules.
- P3 (tests): the identical `keep_lesson_blocked` overlap-audit mode is
  merged into `blocked_dup`; the warm-29 regression test uses `blocked_dup`.
- Offline evidence (nothing written under `data/`):
  - all 17 prompt hashes (16 stage prompts plus the variant link) are
    identical to `bc150c5` (Global Audit short `686a9fba…`, mini
    `bdb7ff05…`);
  - sentinel replay (any model call raises) on a fresh scratchpad `cp -Rp`
    copy of `data/evaluations/dual-profile-cache-20261101-claude-warm-29b`
    (309 files): **233 hits, 0 calls**, 0 repairs, no fallback, stale 0,
    `persisted_flag_representative_duplicates` mini 6 / short 0;
    `final-validated.json`, `global-review.json`, `boundary-review.json`
    and both Discovery files byte-identical to the warm-29b run; the run
    manifest differs only in the call, token, latency and repair counters;
    the cache copy and the source cache are unchanged (309 sha256 sums).
- (Historical next step; Stage 13e was accepted at `194ba65` and cold-30
  ran, above.) Next: independent tester and reviewer on the Stage 13e SHA,
  then cold-30
  (fresh cold run at the final code) as the acceptance run, only with the
  user's go-ahead.

## warm-29b real run (2026-11-01) — strict PASS 95.0 (warm diagnostic, NOT acceptance evidence)

Evidence categories stay distinct: this run is real-model inference evidence
(warm, diagnostic, **not** an acceptance run); the strict evaluator result is
deterministic validation of that output; rendering plus human
editorial/audio review is a separate acceptance activity and is **not**
claimed here. Acceptance needs a fresh cold run at the final code (planned
as cold-30, after the Stage 13e cleanup is verified).

- Code: HEAD `bc150c5f5fc772f574e09c305ba0d7d5d9991bc9` (Stage 13d,
  accepted below). Pinned Claude CLI 2.1.308, subscription login.
- Roots: `data/evaluations/dual-profile-benchmark-20261101-claude-warm-29b`
  (run) and cache `data/evaluations/dual-profile-cache-20261101-claude-warm-29b`,
  a `cp -Rp` copy of the warm-29 cache (306 files). Attempt start epoch
  1793593441 (2026-11-01 20:24:01 -0800).
- Eval rc 0 in 666 s.
- Calls and provenance:
  - 230 cache hits; exactly 3 new calls (short Global Audit 108.5 s, mini
    Global Audit 456.7 s, variant link 48.2 s) plus 1 repair (short Global
    Audit), 4 provider records; 0 retries; no 429, 529 or usage-limit
    errors. Tokens: input 1,773,780, output 81,778.
  - Cache 306 → 309 files; 0 pre-existing files changed; every new file
    has mtime at or after the attempt start; the warm-29 source cache is
    unchanged.
  - Manifest: stale cache resolutions 0; `boundary_opening_fallbacks` `[]`;
    `audit_pair_fallbacks` `[]` (no fallback used);
    `persisted_flag_representative_duplicates` mini 6, short 0.
- Strict result: **PASS 95.0**, evaluator rc 0, no hard failures, no PASS
  blockers. Durable output:
  `data/evaluations/dual-profile-strict-eval-20261101-claude-warm-29b`
  (evidence in its `evidence/` subfolder).
  - Components: short 20, mini 25, risk 10, boundary 15, both 15, audit 10.
  - Short 8/8; S06 matched by `sh0009_balanced_mix_step5` (selected).
  - Mini 5/6: L01–L05 hit. L07 still missed: the exact `precision_yuge…`
    candidate was rejected; `confirm_6001180…` starts −30540 ms from the
    anchor.
  - R01 `blocked`, R02 `manual_review`; no misroutes.
- Both warm-28 N07 hard failures are cleared:
  - `audit_sh0009_throat_tight_strong_mix_diagnosis` is `blocked` with
    "Deterministic flag persistence: " (`topic_switch_inside`).
  - `ml0007_strong_mix_vs_yanyin_core` vs the L04 match
    `audit_ml0008_yanyin_myth_core_chain`: the audit decided the overlap
    near-identical pair as a duplicate. `ml0007…core` is `rejected` with
    `duplicate_of_candidate_id` `audit_ml0008…`, and `audit_ml0008…` stayed
    `manual_review` (L04 hit). No fallback was used.
- Pair and row diagnostics:
  - Prefix rows: short flag-persistence blocked 5; mini quality-gate
    blocked 2.
  - Audit pairs, short 6: nested 2 duplicate + 2 distinct; overlap 2
    distinct.
  - Audit pairs, mini 59: nested 21 duplicate / 23 distinct; overlap 3
    duplicate (near-identical) / 10 distinct; containment 2 duplicate
    (near-identical). All 5 near-identical pairs were decided as
    duplicates.
  - Advisory-only rows: short 4 `manual_review`; mini 3 `manual_review`,
    4 `blocked`, 7 `rejected`.
  - Unflagged `manual_review` rows: short 36, mini 16 (warm-28: 41/19).
  - Twin gated disagreement: 0 of 21.
- Renders: 14 clips into `<run>/renders/`, rc 0 in 266 s, all automatic
  checks pass. Human visual/audio review is PENDING with the user, as is
  the L07 gap listening.
- Comparison: cold-27 PASS 95.0; warm-26 PASS 97.5; warm-28 FAIL 95.0
  (N07 ×2); warm-29 failed closed; warm-29b PASS 95.0.
- Next: Stage 13e reviewer follow-ups (section above), independent
  verification, then cold-30 (fresh cold run at the final code) as the
  acceptance run, only with the user's go-ahead.

## Stage 13d failure observability and duplicate-status alignment (2026-11-01) — ACCEPTED at bc150c5; warm-29b strict PASS 95.0 (diagnostic)

- **Status: ACCEPTED** (2026-11-01) at
  `bc150c5f5fc772f574e09c305ba0d7d5d9991bc9`. Not pushed or merged.
  - Tester: **PASS** at `bc150c5`: lint rc 0; backend 3000 passed in
    1663.46 s; vitest 14 files / 80 tests; e2e 4; targeted 327; no sleep
    between 19:50 and 20:22 on 2026-11-01.
  - Reviewer: **ACCEPT** at `bc150c5`, no P0/P1. Only the Global Audit
    hashes changed (short `686a9fba…`, mini `bdb7ff05…`); mutation testing
    killed 11 of 12 mutants; the simulations reproduced; the strict
    evaluator on cold-27 and warm-28 is byte-identical. Decision 3 judged
    legitimate: a blocked duplicate can count as R01/R02 routing, exactly
    like any blocked candidate. The reviewer's P2 and P3 findings are
    Stage 13e.
  - The first real run on this code, warm-29b, is a strict PASS 95.0
    (warm, diagnostic; section above).
- History: first recorded as **implemented, pending independent tester and
  reviewer; real run pending** on local branch
  `claude/liveclip-stage8-routing`, in two code
  commits after the docs commit `56690c0` that accepted Stage 13c and
  recorded warm-29:
  - `6e1152c` (Commit Q): failure observability and validator messages;
    Python only, no prompt or cache-key change;
  - Commit R (the commit that adds this section): duplicate-status contract
    alignment, the Global Audit prompt, the fallback-order check and the
    Stage 13c reviewer P3s.
  Not pushed or merged.
- Observability (`DualProfileValidationExhaustedError`, a `ValueError`):
  - raised by `_resolve_call` when validation is still failing after the
    one repair and the one regeneration, in any stage; it carries each
    failed attempt's structured output and error (`initial`, or
    `stale_cache` under `--refresh-stale-cache`; `repair`; `regeneration`)
    and the unit's provider call records;
  - `run_dual_profile_evaluation` then writes, to the run directory only,
    `failed-<profile>-<stage>.json`, a partial `provider-calls.json`
    (`partial: true`; completed units plus the failing unit) and
    `failure-manifest.json` (written last), and re-raises; an evidence write
    error is attached as a note and never masks the validation error;
  - the cache is written only for resolved units, as before; outputs are
    the provider's parsed outputs (Claude CLI already drops any output that
    contains the account identity); no credential is written;
  - the CLI still exits 1 and prints a bounded summary (unit, evidence
    file, the start of the last error) under the 500-character limit.
  - Not covered (unchanged): a `StructuredProviderError` raised by the
    repair or regeneration call itself (a provider/schema failure, not a
    validation exhaustion) still propagates without the earlier attempts.
- Validator messages:
  - final assembly names each violating candidate, its status, its
    duplicate target and the allowed statuses, and reports every row
    violation (duplicate reference/status, selected score/flag/risk/boundary
    facts) in one message (at most 20, then a count);
  - `validate_nested_pair_decisions` reports every pair violation with the
    members' IDs, statuses and references, and its text states exactly the
    final rule;
  - audit pair-rule messages name the duplicate.
- Contract alignment (Controller decision 3):
  - `DUPLICATE_ALLOWED_STATUSES = (rejected, blocked)`, for any candidate,
    in final assembly (and therefore in the Global Review chunk check and
    the merged-audit check), matching the pair validator. A `selected` or
    `manual_review` duplicate stays a hard error; nothing is coerced and
    nothing is promoted.
  - Relaxing only makes more outputs valid, so every cached review/audit
    output that validated before still validates; no cache key changes.
  - Downstream-consumer audit (read only), no consumer assumes
    duplicate ⇒ rejected:
    - delivery (`dual_profile_delivery.py`), review package
      (`delivery/dual_profile_review.py`), rendering, script export and the
      variant link payload use only `selected`/`manual_review` rows;
    - Top-N touches only `selected`; the quality gate only
      `manual_review`; flag persistence and the twin union downgrade only
      retained rows, so a blocked duplicate passes through unchanged with
      its reference and the model's reason;
    - risk routing turns only `rejected` risk records into `blocked`; a
      blocked risk duplicate stays legal and keeps its reference;
    - `resolved_duplicates`, the representative rules, the Stage 13c orphan
      logic and the manifest cross-checks treat `rejected` and `blocked`
      alike (non-retained), and an orphan must still keep its reference;
    - the reverse prefix check concerns only Python-prefixed rows;
    - the strict evaluator (`scripts/evaluate_benchmark.py`,
      `scripts/benchmark_gates.py`, unchanged) never reads
      `duplicate_of_candidate_id`; it scores `selected`/`manual_review` as
      outputs and accepts `manual_review`/`blocked` as risk routing, so a
      blocked duplicate is a non-output exactly like a rejected one.
- Fallback order (decision 5): the merged-audit check now runs final
  assembly and the listed-pair rules together. When both fail, one plain
  `ValueError` reports both (`<assembly>; Global Audit pairs: <pairs>`), so
  a repair sees everything and the fallback correctly does not run (it
  cannot fix an assembly error). When only the pair rules fail, the
  `AuditPairRuleError` reaches the fallback as before. No coercion of
  `selected`/`manual_review` to `rejected` was added.
- Prompt (decision 4): only `global_audit.md` changed. It says a duplicate
  ends `rejected` or `blocked`, never `selected`/`manual_review`; that
  Python only blocks retained rows with gated or persisted flags and never
  changes a rejected row (a rejected `risk_discovery` candidate is kept as
  `blocked`); and that when both members of a listed pair carry persisted
  flags the audit decides `distinct_objective` (Python blocks both) or marks
  both as duplicates of a non-persisted representative. The `near_identical`
  parenthetical no longer mentions containment starts. General wording only.
  - Deviation: for a `near_identical` pair whose members both carry
    persisted flags, the prompt asks the audit to set both `blocked` itself,
    because the near-identical rule is checked before routing and would
    otherwise refuse `distinct_objective` with both members retained.
  - Global Audit hashes: short `bb9d2e6ad638…` →
    `686a9fbafa60e00900f0bc6ad7f0cb211ba1a8de0ba9b3de19ee1e01acfaaa64`;
    mini `4c8313b0d62b…` →
    `bdb7ff0545a935c421cf9f06d8033e3e0ca2d2f497c91a64e5517a7039dd8a86`.
    Every other stage hash is unchanged (Discovery family, Boundary Review,
    Global Review, variant link `def25b05bd98…`). Both audits already missed
    at `6089884`, so the next run still costs 3 calls plus repairs.
- Stage 13c reviewer P3s: stale "representatives first" wording corrected
  (dual-profile ExecPlan, the Stage 13c test list below, the test comment);
  new tests for the Global Review chunk prefix check, a full prefix
  mid-text, the audit exemption limited to fallback-blocked IDs (now a
  `fallback_blocked` argument of `reject_reserved_reason_prefixes`), the
  exact five prefixes, merged vs initial fallback planning, the orphan
  record shape and the orphan keeping its duplicate reference.
- Offline evidence (fresh scratchpad `cp -Rp` copies of
  `data/evaluations/dual-profile-cache-20261030-claude-warm-29`, 306 files;
  nothing written under `data/`; the source cache's 306 sha256 sums are
  unchanged afterwards):
  - Sentinel replay (placeholder audits that satisfy the rules): 230 hits,
    exactly 3 calls (2 audits + variant link), 0 repairs, no fail-closed; 3
    new cache entries carrying the new audit hashes, 0 pre-existing entries
    changed. Pair counts unchanged: short nested 4, overlap 2,
    near-identical 0, 32/89 persisted; mini nested 44, overlap 13,
    containment 2, near-identical 5, 55/116 persisted.
  - Forced-fallback replay (placeholder audit keeps every pair): 5
    near-identical records and 2 `orphaned_duplicate` records (the
    Global Review-level duplicates of `ml0007…core`), as at Stage 13c; the
    warm rerun made 0 calls with 233 hits; `final-validated.json`,
    `global-review.json` and `boundary-review.json` byte-identical, the
    manifest identical apart from the call counters.
  - The analyst's 11 warm-29 what-if scenarios (crafted short audit outputs
    for initial, repair and regeneration on the reconstructed payload):
    new code 10 accepted, 1 failed closed as intended (`manual_with_dup`, a
    `manual_review` duplicate, now with the candidate-naming message); at
    `6089884` 7 failed with the warm-29 stderr and 4 were accepted.
    - Accepted at the first attempt: `both_blocked_distinct`,
      `both_blocked_third`, `both_rejected_third`, `waist_blocked`
      (`both_blocked_third` and `waist_blocked` failed at `6089884`).
    - Accepted by the downgrade-only fallback after repair and regeneration
      (persisted-flag representative rule, the model's duplicate accepted
      unchanged): `blocked_dup` (the warm-29 shape), `rejected_dup`,
      `blocked_dup_core_blocked`, `blocked_dup,rejected_dup,blocked_dup`,
      `both_blocked_nodup_duplicate,blocked_dup,blocked_dup` and
      `both_blocked_nodup_duplicate,blocked_dup,rejected_dup`. At
      `6089884` only `rejected_dup` and the last one were accepted; the
      other four failed with the warm-29 stderr.
  - Forced-failure observability on the real payload (`manual_with_dup`):
    the run directory holds `failed-short_highlight-global_audit.json`
    (3 attempts with outputs and errors, `cache_written: false`), a partial
    `provider-calls.json` and `failure-manifest.json`; the cache copy is
    unchanged (306 files, 0 new, 0 changed); 0 email matches.
- Tests (mock/fixture only): assembly reports every row violation;
  pair-validator messages; blocked duplicate accepted for any candidate
  and a retained duplicate never coerced (mutation reverting the allowed
  statuses is killed by 3 tests); the warm-29 shape reaches the fallback;
  a blocked non-risk duplicate needs no repair; assembly and pair errors
  reported together without the fallback; forced-failure evidence in the
  run directory only with the cache untouched; CLI exit 1 with a bounded
  summary; Global Audit prompt contract; the P3 gaps above.

## warm-29 real run (2026-10-30) — FAILED CLOSED in the short Global Audit; Stage 13d decided

- **Result: failed closed, not a quality result.** Real Claude CLI at
  `6089884` (Stage 13c accepted code), warm, diagnostic. No
  `provider-calls.json`, `run-manifest.json` or new cache file was written.
- Setup:
  - pinned Claude CLI 2.1.308 (`.cache/claude-cli/2.1.308/claude`);
  - attempt start epoch 1793401583 (2026-10-30 16:06:23 -0700), eval
    started 1793401601;
  - roots `data/evaluations/dual-profile-benchmark-20261030-claude-warm-29`
    (run) and `data/evaluations/dual-profile-cache-20261030-claude-warm-29`
    (cache), with evidence in
    `data/evaluations/dual-profile-strict-eval-20261030-claude-warm-29/evidence/`;
  - the cache is a `cp -Rp` copy of the warm-28 cache: 306 files,
    byte-identical before the run; after the run 0 new, 0 removed and 0
    pre-existing files changed, and the warm-28 source cache is unchanged;
  - `--discovery-concurrency 3`; 0 sleep/wake entries; 0 email matches in
    the scratch output and evidence.
- Failure: eval rc 1 after 263 s, in the short Global Audit (the first
  uncached call). Stderr:
  `deterministic validation still failed after one repair and one regeneration: duplicate candidate must be retained as a rejected audit row`.
  The run directory holds only `discovery-short.json`.
- The raw model outputs (initial, repair, regeneration) cannot be recovered:
  `claude_cli.py` runs with `--no-session-persistence` in a temporary
  directory and keeps stdout in memory, and the service writes nothing on
  a validation failure.
- Read-only analysis (offline reconstruction of the exact short audit
  payload from a cache copy, plus what-if simulations with crafted audit
  outputs; scripts in the session scratchpad `w29/`):
  - **Root cause: two validators contradict each other.**
    `validate_nested_pair_decisions` accepts a `rejected` or `blocked`
    duplicate for any candidate, and its error text tells the model
    "rejected or blocked with duplicate_of_candidate_id". Final assembly
    (`assemble_final_profile_result`) accepts a `blocked` duplicate only for
    `risk_discovery` records, and the short Profile has none.
  - `global_audit.md` (Stage 13b) says a candidate with persisted gated
    flags "will be blocked". It never says a duplicate stays rejected even
    when it carries such flags, and gives no guidance when both members of
    a pair carry persisted flags. The short payload's nested pair
    `sh0018_nasal_highnote_diag` ⊃ `sh0018_nasal_highnote_core` is such a
    pair (both `manual_review`, both with persisted `material_interruption`).
  - Short payload: 89 candidates (47 manual_review, 34 blocked, 6 rejected,
    2 selected); 6 audit pairs (4 nested, 2 overlap, 0 near-identical); 32
    candidates with persisted gated flags; no risk records.
  - The simulations reproduce the exact warm-29 stderr when a non-risk
    duplicate is set to `blocked`, and show that the model can oscillate
    between the two validators' messages across repair and regeneration.
  - `_audit_pair_fallback` only handles `AuditPairRuleError`. This failure
    was a plain `ValueError` from the final-assembly check of the merged
    audit, which runs before the pair rules, so no fallback ran.
  - The validator message names no candidate and uses "retained" in the
    opposite sense to the prompt.
- Controller decisions (2026-10-30), implemented as Stage 13d:
  - **Commit Q, failure observability and validator messages (Python
    only).** When validation is exhausted after repair and regeneration
    (any stage), raise a typed error carrying each attempt's structured
    output, each error and the provider call records; the service writes
    `failed-<profile>-<stage>.json`, a partial `provider-calls.json` and a
    failure manifest to the run directory only (never the cache) and
    re-raises; the CLI still exits non-zero. Validator messages name the
    candidate IDs, the current status, the duplicate target and the allowed
    statuses, separate a retained duplicate from a wrong non-output status,
    report every violation in one message where feasible, and the
    pair-validator text matches the final rule. No prompt or cache-key
    change.
  - **Commit R, contract alignment and audit prompt.** Final assembly
    accepts a duplicate as `rejected` or `blocked` for any candidate,
    matching the pair validator (both statuses are non-output). A
    `selected`/`manual_review` duplicate stays a hard error and is never
    coerced. Python still never promotes, and a blocked risk duplicate
    stays legal. Only `global_audit.md` changes (never `main.md`,
    `repair.md`, the profile files or another stage file, which would
    invalidate about 230 cached calls): a duplicate ends `rejected` or
    `blocked`; Python blocks only retained rows with gated or persisted
    flags and never changes a rejected row; when both members of a listed
    pair carry persisted flags, decide `distinct_objective` or make both
    duplicates of a non-persisted representative. The stale containment
    "starts" wording in the `near_identical` parenthetical is fixed in the
    same edit. Both audits already miss at `6089884`, so the next run still
    costs 3 calls plus repairs. Also: check the audit validation order so
    the fallback sees whether pair rules are the only remaining failures;
    the Stage 13c reviewer P3s.

## Stage 13c audit fallback keep order and contract alignment (2026-10-30) — ACCEPTED at 6089884; warm-29 FAILED CLOSED

- **Status: ACCEPTED** (2026-10-30) at
  `608988463c9e98a7eb861e28a5a80360ea29366d` on local branch
  `claude/liveclip-stage8-routing` (two code commits, `4543d0a` and
  `6089884`, after the docs commit that accepted Stage 13b at `e48f601`).
  Not pushed or merged. (History: first recorded as implemented, pending
  independent tester and reviewer; real run pending. It had to land before
  the real run: once a real run writes fallback-marked audit entries, a
  later change to the fallback would make them fail closed on warm reruns.)
- Tester: **PASS** at `6089884`. Backend 2986 passed; vitest 80; e2e 4;
  targeted 255.
- Reviewer: **ACCEPT** at `6089884`, no P0/P1. P3s, taken up by Stage 13d:
  - stale "representatives first" wording (dual-profile ExecPlan, this
    file, a test comment);
  - reserved-prefix test gaps: the Global Review chunk check, a full prefix
    appearing mid-text being allowed, the audit exemption limited to
    fallback-blocked IDs, a hard-coded list of all five prefixes;
  - audit fallback test gaps: merged vs initial plan, orphan record shape,
    the orphan keeping its duplicate reference.
- The first real run on this code, warm-29, failed closed in the short
  Global Audit (section above).
- Python only. No prompt changed: Global Audit stays short
  `bb9d2e6ad638…` / mini `4c8313b0d62b…`, every cache key is unchanged, and
  the 3-call estimate holds.
- P2-A, orphaned duplicates (`plan_audit_pair_fallback`,
  `resolved_duplicates`, `_audit_pair_fallback`):
  - Keep order, fully deterministic (final, after the Controller decision
    below):
    1. no persisted Discovery gated flag first;
    2. shorter duration;
    3. more resolved duplicates;
    4. earlier start, then smaller ID.
    (History: the first 13c commit `4543d0a` put "more resolved duplicates"
    before duration.)
  - Unavoidable orphans are recorded: every duplicate whose resolved
    representative the fallback blocked gets an `orphaned_duplicate` record
    (blocked representative, duplicate, `pair_kind` nested, overlap,
    containment, or none for a Global Review-level duplicate). Nothing is
    promoted.
  - Before this, a block-caused representative violation of an overlap pair
    was recorded as an "accepted" duplicate; it is now an orphan record.
    "Accepted" records only ever come from the model's own output.
  - Wording corrected in PRODUCT_SPEC and the Stage 13b section: every
    blocked member keeps a retained near-identical partner. But for same-end
    and near-copy pairs the blocked longer member can hold media the kept
    member lacks, which is the keep-the-shortest-complete-version policy.
- Controller correction (user decision alignment): containment near-copy
  listing now follows the user decision exactly. The inner duration must be
  ≥ 9/10 of the outer, or the ends must be within
  `AUDIT_SAME_END_TOLERANCE_MS`. "Starts within the tolerance" was never
  approved and is removed; the decision log records the correction.
  - The audit prompt still mentions containment starts in its
    `near_identical` parenthetical. It is not changed here (to keep the hash
    and cache keys). It describes a superset of the code, and the model
    reads the precomputed field.
- P3-2: a block that resolves several near-identical pairs records each pair
  it resolves. The manifest cross-check changed accordingly: every blocked
  member must have at least one record whose other member is not blocked,
  and an orphan must name a fallback-blocked representative.
- P3-3, reserved prefixes:
  - Model review reasons may not start with a Python-only prefix
    (`DETERMINISTIC_REASON_PREFIXES`: audit fallback, flag persistence,
    quality gate, risk routing, Top-N). This is checked in Global Review
    chunk validation and on Global Audit replacements (repairable). Only
    rows the audit fallback itself blocked may carry its prefix.
  - Reverse manifest check: every final row with the audit-fallback prefix
    needs a near-identical fallback record. A Top-N prefix requires
    `rejected`; every other prefix requires `blocked`.
  - Checked read-only: every existing `final-validated.json` and
    `run-manifest.json` pair under `data/evaluations` (25 runs, including
    cold-27, warm-26 and warm-28) still passes `validate_against`, and no
    warm-28 Global Review or audit cache entry starts with a reserved prefix.
  - The strict evaluator output for cold-27 (PASS, rc 0) and warm-28 (FAIL,
    rc 1) is byte-identical to the stored results.
- P3-5: new tests kill M17 (a blocked row without the fallback prefix fails
  the manifest check) and M21 (the representative rule on containment
  pairs).
- P2-B (documented, plus a diagnostic):
  - The persisted-flag representative rule is enforced only on listed
    (Global Review-retained) pairs. Duplicates the Global Review already
    made that point to a persisted-flag representative rely on the prompt
    sentence alone.
  - The run manifest now reports `persisted_flag_representative_duplicates`
    (per Profile, over the final merged review) so the real run can measure
    it. Earlier manifests load with `{}`.
- Offline evidence (fresh scratchpad `cp -Rp` copies of the warm-28 cache;
  nothing written under `data/`):
  - Sentinel replay: 230 hits and exactly 3 model calls (2 audits + variant
    link), no fail-closed.
  - Pair counts are unchanged from Stage 13b:
    - short: nested 4, overlap 2, containment 0, near_identical 0;
    - mini: nested 44, overlap 13, containment 2, near_identical 5.
    - Both reviewer-identified containment pairs are still listed (both are
      end-close).
    - The L02 match appears only in its two nested pairs, and its sub-clip
      `audit_ml0006_step3…` only in a nested pair with
      `ml0006_steps1to3_from_step_marker`.
  - Forced-fallback replay at `4543d0a` (representative-first order,
    superseded; the placeholder audit keeps every pair, so the mini audit
    takes initial + repair + regeneration, then the fallback):
    - 5 near-identical records and 1 `orphaned_duplicate` record
      (`risk_yanyin_beginner_warning_core` →
      `risk_yanyin_warning_full_chain`, a Global Review-level duplicate);
    - no unrecorded orphan;
    - the warm rerun had 0 calls and 233 hits;
    - `final-validated.json`, `global-review.json` and
      `boundary-review.json` were byte-identical, and the manifest was
      identical apart from the call counters.
  - **Trade-off found** (decided by the Controller, see below): under the
    forced fallback,
    representative-first keeps `ml0007_strong_mix_vs_yanyin_core` (the
    representative of 2 Global Review duplicates; Boundary Review trimmed
    it, so it has no persisted flag) and blocks
    `audit_ml0008_yanyin_myth_core_chain`, the L04 match.
    - The Stage 13b order would have kept the shorter L04 match and
      orphaned the 2 duplicates.
    - This matters only if the real audit fails the near-identical rule
      three times. The prompt tie-break steers the model to the shortest
      complete version.
  - The placeholder audit's `persisted_flag_representative_duplicates` (mini
    7, short 1) is not evidence; the real run measures it.
- **Controller decision (2026-10-30): length before representative count.**
  - Rationale: representative-first kept `ml0007…core`, the 169 s clip that
    caused warm-28's N07 padding hard FAIL, and blocked the 142 s L04
    match. That reintroduces the failure Stage 13 targets and loses a
    P0-adjacent hit.
  - The user approved "keep the shortest independently complete version"
    as the dedup policy; a duplicate count is only a proxy and can
    contradict it. The P2-A orphan risk is accepted: orphans are recorded,
    never promoted.
  - Code: `plan_audit_pair_fallback` keep order is persisted-flag key →
    shorter duration → more resolved duplicates → earlier start → smaller
    ID.
  - Tests: the shorter member is kept over a longer representative, and its
    orphan is recorded with the kept/blocked statuses; equal duration is
    tie-broken by representative count.
  - Forced-fallback replay at the new order (fresh scratchpad copy of the
    warm-28 cache):
    - in the `ml0007_strong_mix_vs_yanyin_core` /
      `audit_ml0008_yanyin_myth_core_chain` pair the L04 match
      `audit_ml0008…` is **kept** (`manual_review`) and `ml0007…core` is
      blocked;
    - 5 near-identical records: `audit_6246760…` blocked for its 2
      containment pairs; `ml0007…core` blocked for 2 pairs (with
      `audit_ml0008…` and `risk_yanyin_beginner_warning_core`);
      `risk_age_decline_permanent_damage_2975_3066` blocked for its pair
      with `ml0021_decline_lowfirst_core`;
    - 2 `orphaned_duplicate` records, both Global Review-level duplicates
      (pair kind none) of `ml0007…core`: `ml0007_strong_mix_vs_yanyin_full`
      and `ml0008_yanyin_beginner_myth`;
    - no unrecorded orphan; the warm rerun made 0 calls with 233 hits;
      `final-validated.json`, `global-review.json` and `boundary-review.json`
      are byte-identical, and the manifest is identical apart from the call
      counters.
  - Sentinel replay at the new order: 230 hits, exactly 3 calls.
- Tests (mock/fixture only):
  - Unit:
    - containment boundaries updated: starts 5 s and 1 s now unlisted;
      short end tolerance 3/4 s;
    - shorter member kept first, then the representative of more duplicates
      among equally long members (wording corrected by Stage 13d; it
      previously read "representative kept first", the superseded `4543d0a`
      order);
    - unavoidable nested orphan recorded with its kind;
    - every resolved pair recorded;
    - representative rule on containment pairs (M21);
    - reserved prefixes;
    - reverse prefix checks;
    - blocked row without the prefix (M17);
    - an orphan naming a kept representative is refused.
  - Integration: a persisted-flag representative violation accepted and
    counted in the new diagnostic; a model-written fallback prefix repaired.
- `docs/PRODUCT_SPEC.md`: Stage 13c amendment and inline corrections.

## Stage 13b audit awareness, audit fallback, near-copy containment (2026-10-30) — ACCEPTED at e48f601; REAL RUN PENDING

- **Status: ACCEPTED** (2026-10-30) at
  `e48f6018bc9456278585ca1f63f0d0c225834697` on local branch
  `claude/liveclip-stage8-routing` (code commit after the docs commit that
  accepted Stages 12c and 13 at `b5da41c`); real run pending. Not pushed or
  merged. (History: first recorded as implemented, pending independent
  tester and reviewer; real run pending.)
- Tester: **PASS** at `e48f601`. `make lint` rc 0; backend 2976 passed in
  1632.67 s; vitest 14 files / 80; e2e 4; targeted 245. No sleep in the
  14:49–15:22 window on 2026-10-30.
- Reviewer: **ACCEPT** at `e48f601`, no P0/P1. 23/27 mutants killed.
  Deviation 3 is endorsed: accepting the model's duplicate unchanged is the
  only downgrade-only option for representative-rule violations. Sentinel
  replay: 230 hits, exactly 3 calls, no fail-closed. A forced-fallback
  cold → warm replay was byte-identical. The P2s and P3s (fallback keep
  order and orphaned duplicates, record granularity, a reverse prefix
  cross-check, mutant-killing tests, the GR-level persisted-flag gap) and a
  Controller correction of the containment criteria are taken up as
  Stage 13c.
- Origin: the Stage 13 reviewer P2s and the binding user decision on
  near-copy containment (2026-10-30). Everything lands before the real run.
  The Global Audit prompt hash already changed in Stage 13, so there is no
  extra cache cost.
- P2-1, the audit knows about persisted flags:
  - Problem: a representative that Fix 1 later blocks took its duplicates
    with it in every replay (cold-27 lost 5 rows, warm-28 3, warm-26 9).
  - Payload: each audit candidate (audit payload only; the Global Review
    payloads are unchanged) carries `persisted_discovery_gated_flags`. It is
    computed with `discovery_persisted_flags`, the same function Fix 1
    routing uses, so the two cannot drift.
  - Prompt: `global_audit.md` gains one general sentence. A candidate with
    persisted gated flags will be blocked, so it must never be chosen as a
    duplicate representative or kept as the retained member of a pair.
  - Validator: a `duplicate` decision on any listed pair whose resolved
    representative carries persisted gated flags fails with rule
    `persisted_flag_representative` and goes to repair.
- P2-2, deterministic Global Audit fallback (`AuditPairRuleError`,
  `plan_audit_pair_fallback`, `apply_audit_pair_blocks`):
  - When it applies: the pair rules (near-identical, overlap
    representative, persisted-flag representative) raise one structured
    error, and only after every other audit check passed. When, after
    repair and regeneration, these are the only failures left, a
    downgrade-only fallback runs instead of aborting.
  - Near-identical rule: each violating pair is resolved by blocking its
    longer member (ties: later start, then the lexicographically larger
    ID), with the reason prefix "Deterministic audit fallback: ".
  - Coverage guarantee: members are visited in keep order and a kept member
    blocks its still-undecided violating partners, so every blocked member
    has a near-identical partner that stays retained. The fallback never
    removes the only retained member covering an interval. (Corrected by Stage 13c: this overstates it. Every blocked member keeps a
    retained near-identical partner, but for same-end and near-copy pairs
    the blocked longer member can hold media the kept member lacks, which is
    the keep-the-shortest-complete-version policy. Duplicates of a blocked
    representative were also not recorded; Stage 13c records them.)
  - Deviation 1 (persisted flags): a member with persisted gated flags is
    kept last, because final routing would block it anyway.
  - Deviation 2 (chains): in a chain A > B > C, C blocks B; the pair A/B is
    then already resolved, so A, whose only partner is now blocked, stays
    retained.
  - Deviation 3 (representative rules): these violations cannot be fixed
    without promoting a candidate. The fallback accepts the model's
    duplicate unchanged and records it. It never promotes, and it never
    turns a rejected row into blocked.
  - Any other failure still raises, as does a near-identical violation the
    blocks do not resolve.
  - Manifest: every action is recorded in `audit_pair_fallbacks`
    (`AuditPairFallback`: profile, rule, pair IDs, `blocked_candidate_id`
    or `duplicate_candidate_id`). Earlier manifests load with an empty
    tuple.
  - Cross-checks, as in Stage 12c: shape per rule; unique actions and
    blocked IDs; a kept member is never blocked by another record; IDs
    belong to the run; a blocked member ends `blocked` with the fallback
    prefix; an accepted duplicate never becomes an output.
  - Cache: as for the Stage 12c Boundary Review fallback, the cache keeps
    the raw audit output plus a verified `conservative_fallback` marker
    (stage and affected IDs). A warm hit re-applies the fallback and
    re-records it; a tampered marker fails closed.
  - The fallback protocol is now generic: the stage fallback returns the
    validated output, the marker IDs and the manifest records. The Boundary
    Review fallback was moved onto it without any behavior change.
- P2-3, near-copy containment (binding user decision):
  - A containment pair (strictly inside, no shared edge cue) is listed as
    `pair_kind: containment`, always `near_identical: true`, only when it
    is a near-copy: the inner duration is at least 9/10 of the outer, or the
    ends or the starts are within `AUDIT_SAME_END_TOLERANCE_MS` (short
    3000, mini 5000). (Corrected by Stage 13c: the user approved only the
    9/10 and end-tolerance criteria; the starts criterion was a Controller
    addition and is removed.)
  - Other containment stays unlisted, which protects a full lesson with a
    sub-clip inside it.
  - The near-identical and representative rules apply to containment pairs
    as to overlap pairs.
- P3 wording:
  - `global_audit.md` no longer says "end at the same point". It refers to
    the precomputed `near_identical` field (ends, or for containment
    starts, within the boundary tolerance, or ≥90% of the shorter).
  - The Stage 13 "byte-identical payload" wording is corrected above.
- Prompt hashes:
  - Global Audit: short `48d61543a335…` → `bb9d2e6ad6382f7fac8293a718ffb189465d3a84e5dee7759579d57b8b936d71`;
    mini `1c710835f281…` → `4c8313b0d62b649f6e45c51d0e4cfdce4c240fe6e0cceac08e470992a9348934`.
    Relative to warm-28's cached audits (`746b625e589b…`, `cb115e030631…`),
    the audits still simply miss.
  - Unchanged: the Discovery family, Boundary Review (`3119f245c2cd`,
    `62fedbec56dc`), Global Review (`1faa9412f673`, `aea87440f0ab`) and
    variant link (`def25b05bd98`).
- Offline evidence (sentinel provider on a scratchpad `cp -Rp` copy of the
  warm-28 cache; nothing written under `data/`):
  - Calls: 230 hits and exactly **3** model calls (Global Audit short,
    Global Audit mini, variant link), with no fail-closed error. Discovery,
    Boundary Review and Global Review all hit. With a sentinel that allows
    nothing, the first call is the short audit. A real rerun therefore
    needs 3 calls plus any repairs.
  - Pairs in the new audit payloads:

    | Profile | nested | overlap | containment near-copy | near_identical |
    |---|---|---|---|---|
    | short | 4 | 2 | 0 | 0 |
    | mini | 44 | 13 | 2 | 5 (3 overlap + 2 containment) |

  - The two reviewer-identified containment pairs are now listed:
    `audit_6246760_age_decline_recovery_chain` ⊃ `ml0021_decline_lowfirst_core`
    and ⊃ `risk_age_decline_permanent_damage_2975_3066`.
  - The L02 match `ml0006_steps1to4_through_transition` appears only in its
    two existing nested pairs. Its containment of
    `audit_ml0006_step3_strongmix_vs_falsetto_contrast` stays unlisted.
  - Persisted flags: short 32 of 89 audit candidates (5 of them retained in
    the initial review); mini 55 of 116 (4 retained).
- Tests (mock/fixture only):
  - Unit:
    - near-copy containment boundaries: exactly 9/10 listed and 179/200
      not; ends 5/6 s; starts 5/6 s; a 0.34 sub-clip with distant edges
      stays unlisted; short tolerance 3/4 s;
    - shared-edge containment stays nested;
    - the persisted-flag representative rule;
    - pair-rule errors are raised only after every other check;
    - fallback block choice and ties, the chain and persisted-flag keep
      order, and downgrade-only blocks;
    - manifest `audit_pair_fallbacks` cross-checks.
  - Integration:
    - the audit-only persisted-flag payload field;
    - a persisted-flag representative repaired;
    - the near-identical fallback cold → warm round trip with refresh off
      and on (final output and manifest record reproduced with 0 calls,
      cache untouched, raw output plus marker);
    - representative-only violations accepted and recorded without
      promotion;
    - other failures still raise;
    - a tampered audit marker fails closed;
    - prompt wording checks.
- `docs/PRODUCT_SPEC.md`: Stage 13b amendment.
- Unchanged: Discovery, Boundary Review and Global Review prompts, cache-key
  derivation, `DUAL_PROFILE_ALGORITHM_VERSION`, benchmark JSON/MD,
  evaluator thresholds, guard patterns, frozen `tools/loop_engineering`.

## Stage 13 deterministic flag persistence and overlap adjudication (2026-10-30) — ACCEPTED at b5da41c; REAL RUN PENDING

- **Status: ACCEPTED** (2026-10-30) at
  `b5da41c7a60dec2f8e05417e64505cafe7dd5547` on local branch
  `claude/liveclip-stage8-routing`, together with Stage 12c (`4a30497`);
  real run pending. Not pushed or merged. (History: first recorded as
  implemented, pending independent tester and reviewer; real run pending.)
- Tester: **PASS** at `b5da41c`. `make lint` rc 0; backend 2953 passed in
  1632.59 s; vitest 14 files / 80; e2e 4; targeted 222. No sleep in the
  14:04–14:37 window on 2026-10-30.
- Reviewer: **ACCEPT** at `b5da41c`, no P0/P1.
  - 16/16 mutants killed.
  - The Fix-1-only replay reproduced FAIL 93.0. The 2-point drop is only
    the offline `call_data` artifact: a post-hoc evaluation with the real
    tokens gives 95.0 with identical rows.
  - Post-hoc runs with the Stage 13 routing: cold-27 stays PASS 95.0 and
    warm-26 stays PASS 97.5, with no hits lost. Evaluator output on cold-27
    and warm-28 is byte-identical.
  - P2s (audit unaware of persisted flags; no audit fallback; near-copy
    containment) are taken up as Stage 13b.
  - P3, literal-rule consequence (the user has been told): a 1-cue trim on
    either edge clears every Discovery gated flag, including end-edge flags
    such as `topic_not_closed` (the R01 record went from cue 1881 to 1882).
  - P3, deliberate: under `--refresh-stale-cache`, a marked fallback entry
    (Stage 12c) that later goes stale cannot be refreshed; its marker
    verification fails closed instead.
- Origin: the warm-28 root cause and the binding user decisions of
  2026-10-30 (warm-28 section below). General: no anchor times, IDs or
  wording appear in code, prompts or tests.
- **Fix 1, Discovery gated-flag persistence** (`assemble_final_profile_result`,
  helpers `discovery_persisted_flags` and `boundary_shrank_interval`):
  - For each final candidate, the gated flags
    (`MANUAL_REVIEW_BLOCKING_QUALITY_FLAGS`) on its Discovery record
    (whichever pass produced it) survive into the final merged flags unless
    Boundary Review shrank the interval on at least one edge (start cue
    later or end cue earlier). Extension alone or an unchanged interval
    keeps them; advisory flags are never persisted.
  - A `selected` or `manual_review` row that keeps one becomes `blocked`
    with the sibling prefix "Deterministic flag persistence: "; rejected
    and blocked rows keep their status and record the flag. Python only
    downgrades; it never raises here and never promotes.
  - Order (documented in the docstring): (1) review-stage validation,
    unchanged because it sees only the merged Boundary/Global flags, then
    persistence; (2) same-interval twin union, which therefore shares
    persisted flags; (3) Profile-local Top-N over rows still `selected`,
    so a persisted-flag row never takes a slot; (4) risk-record routing and
    the manual-review quality gate.
  - Applied at final assembly only, so persistence itself changes no
    request payload: the Global Review payloads are byte-identical, and the
    Global Audit payload changed only through Fix 2 (the pair list key was
    renamed from `nested_pairs` to `audit_pairs`). (Wording corrected by
    Stage 13b; it first said both payloads were byte-identical.)
  - `DUAL_PROFILE_ROUTING_POLICY_VERSION` is now
    `quality-gate-risk-routing-v4`; v1–v3 and unmarked artifacts still load.
- **Fix 2, overlap adjudication** (`audit_candidate_pairs`,
  `validate_audit_pair_decisions`, `AuditCandidatePair`, `AuditPairKind`):
  - The audit payload's pair list is now `audit_pairs` (it was
    `nested_pairs`). Each entry has `outer_candidate_id`,
    `inner_candidate_id`, `pair_kind` (`nested` | `overlap`) and
    `near_identical`.
  - Nested pairs are exactly the previous `nested_candidate_pairs`.
  - Overlap pairs are the other retained (`selected`/`manual_review`)
    same-Profile pairs where neither contains the other and the shared media
    is at least `AUDIT_OVERLAP_MIN_SHORTER_FRACTION` = 1/2 of the shorter
    candidate. `outer_candidate_id` is the earlier-starting member.
  - Containment without a shared edge stays unlisted, as before. Reason: in
    warm-28 such a pair includes the L02 match and a focused sub-lesson
    inside it; containment is the "focused lesson inside a broader lesson"
    case, which the audit may legitimately keep as distinct.
  - The audit must decide every pair of either kind, including pairs its
    replacements create, through the existing `validate_nested_pair_decisions`
    semantics (including the Stage 12 shared-representative rule). The
    output schema is unchanged: decisions stay in `nested_pair_decisions`.
  - Safety rule. An overlap pair is `near_identical` when the ends are
    within `AUDIT_SAME_END_TOLERANCE_MS` (short 3000, mini 5000) or the
    overlap is at least `AUDIT_NEAR_IDENTICAL_SHORTER_FRACTION` = 9/10 of
    the shorter candidate. Such a pair may not keep both members
    `selected`/`manual_review`.
  - Why this rule instead of "unless the reason names the distinct
    objective": a free-text reason cannot be checked deterministically, and
    any keyword test would be gameable and language-dependent. Two retained
    same-Profile clips sharing ≥90% of the shorter one (or the same ending)
    are near-identical media, so the simplest sound rule is never to keep
    both. The audit keeps one representative, or rejects/blocks a member on
    its own merits.
  - Representative rule. An overlap `duplicate` must leave the resolved
    representative `selected` or `manual_review`, so deduplication never
    deletes the last retained version of that media. Nested-pair semantics
    are deliberately unchanged ("preserve existing guarantees"; a test pins
    this).
  - Known limit: a representative that deterministic routing later blocks
    (gated flags) takes its duplicate with it, because Python never
    promotes.
- `global_audit.md` (both Profiles; minimal and general): the "Nested
  pairs" paragraph became "Listed pairs" (both kinds, `audit_pairs`), plus
  the near-identical rule, the retained-representative rule and the
  tie-break "keep the shortest independently complete version; material
  only one version adds beyond the shared objective is a reason to reject
  that version".
- Prompt hashes:
  - Changed: Global Audit short `746b625e589b…` → `48d61543a335…`, mini
    `cb115e030631…` → `1c710835f281…`.
  - Unchanged: Discovery family, Boundary Review (`3119f245c2cd`,
    `62fedbec56dc`), Global Review (`1faa9412f673`, `aea87440f0ab`) and
    variant link (`def25b05bd98`).
  - No cache-key derivation change, and `DUAL_PROFILE_ALGORITHM_VERSION` is
    unchanged (the prompt hash already re-keys the audit).
- Offline evidence (all against `cp -Rp` copies of
  `data/evaluations/dual-profile-cache-20261030-claude-warm-28` in the
  session scratchpad; nothing was written under `data/`; the harness, a
  sentinel provider with the warm-28 provider identity, first reproduced
  warm-28 at `a7088c4` with 233 hits, 0 calls and a byte-identical
  `final-validated.json`):
  - Fix 1 alone (before Fix 2 was wired): Discovery, Boundary Review,
    Global Review and both Global Audits all hit. The only model call is
    variant link (1), which cannot hit: its payload lists the final
    `selected`/`manual_review` candidates, and Fix 1 changes them. With an
    offline variant-link stub that reuses the warm-28 group labels (232
    hits, 1 stubbed call), 8 rows move `manual_review` → `blocked`
    (`audit_sh0009_throat_tight_strong_mix_diagnosis`,
    `audit_sh0006_breathy_mix_intro_vs_weak_mix`,
    `sh0018_nasal_highnote_core`, `sh0018_nasal_highnote_diag`,
    `sh_0016_vocal_cord_issue_check_first`, `ml_0018_tangtang_nasal_diagnosis`,
    `precision_ml_0018_tangtang_nasal_correction_loop`, and
    `ml14_nasal_problem_full` through the twin union). Other already-blocked
    rows gain flags.
  - Strict evaluator on that offline result (scratchpad output): **FAIL
    93.0**; hard failure `irrelevant_padding` only (`ml0007…core`, Fix 2's
    target); `negative_anchor_output` is gone; short 8/8, mini 5/6 (L07
    still missed), R01 blocked, R02 `manual_review`, no PASS blockers, no
    lost hit. The 2-point drop from 95.0 is the audit item `call_data`:
    the offline replay records no tokens. It is not a routing effect.
  - Final code: the sentinel allows only `global_audit` and `variant_link`
    (offline placeholders used only to get past them). 230 hits and exactly
    **3** model calls: Global Audit short, Global Audit mini, variant link.
    Discovery, Boundary Review and Global Review all hit.
    - The warm-28 audit entries simply miss under the new prompt hash; they
      are not failed closed.
    - The new audits receive short 4 nested + 2 overlap pairs (0
      near-identical) and mini 44 nested + 13 overlap pairs. The 3 mini
      near-identical pairs include `ml0007…core` / `audit_ml0008…` (93%).
    - A real rerun from the warm-28 cache would therefore make about 3
      calls plus any repairs.
- Tests (mock/fixture only):
  - Unit, Fix 1 (10): unchanged/extended intervals keep the flag;
    start-later, end-earlier and start-later-with-extended-end clear it;
    advisory flags are unaffected; only downgrades (selected → blocked
    without raising; rejected/blocked unchanged); order of persistence,
    twin union and Top-N; helper semantics.
  - Unit, Fix 2 (9): named constants; pair generation at exactly 50%
    (listed) and just below (not listed); containment and rejected rows are
    not listed; nested pairs first and unchanged; same-end tolerance per
    Profile at the boundary (3/4 s short, 5/6 s mini); 90% boundary; safety
    and representative rules; nested semantics unchanged.
  - Integration (6): the service persists a Discovery flag unless Boundary
    Review trims (both cases); the audit must decide an overlap pair (an
    omitted decision is repaired); a near-identical pair kept as distinct is
    repaired to one representative; an old audit without overlap decisions
    (pre-overlap prompt identity) simply misses and is regenerated with the
    planted entry untouched; the same old-contract audit under the current
    identity and payload fails closed.
  - Updated: the payload key and monkeypatch target (`audit_pairs`,
    `audit_candidate_pairs`), the audit prompt wording checks, and the
    routing-policy marker (v4 accepted, v1–v3 still load).
- `docs/PRODUCT_SPEC.md`: Stage 13 amendment.
- Unchanged: benchmark JSON/MD, evaluator thresholds, guard patterns,
  frozen `tools/loop_engineering`, Discovery/Boundary Review/Global Review
  prompts.

## Stage 12c fallback provenance and manifest cross-checks (2026-10-30) — ACCEPTED at b5da41c

- **Status: ACCEPTED** (2026-10-30). Code commit
  `4a3049732c3bed64b2387c24e99943195403bc46`, verified at the tip
  `b5da41c7a60dec2f8e05417e64505cafe7dd5547` together with Stage 13 (see
  the tester and reviewer bullets in the Stage 13 section; the reviewer's
  deliberate-behavior P3 on stale marked entries is recorded there). On
  local branch `claude/liveclip-stage8-routing` (code commit after the docs
  commit that accepted Stage 12b at `a7088c4`). Not pushed or merged.
  (History: first recorded as implemented, pending independent tester and
  reviewer.)
- Origin: the Stage 12b reviewer P2-A, P2-B and P3s at `a7088c4`.
- P2-A (fallback provenance on a warm hit). Design: the cache keeps the
  **raw** model output (the regenerated output that still failed only the
  opening invariant), plus a marker field `conservative_fallback`
  (`{"stage": "boundary_review", "candidate_ids": [...]}`) that is written
  only on fallback entries. On a hit, a marked entry is re-resolved with the
  same deterministic `apply_boundary_opening_fallback`, re-validated and
  recorded again in `boundary_opening_fallbacks`, so a warm rerun
  reproduces the cold final output **and** the manifest record. Why a
  marker in addition to raw output (deviation from "raw only"): a raw
  output that violates the opening invariant is ambiguous. It is either a
  cold-run fallback (repair and regeneration already exhausted) or a
  stale/planted entry, which the Stage 9/12b contract must fail closed by
  default and repair only under `--refresh-stale-cache` (an existing test
  plants exactly such an entry). Re-applying the fallback to every
  violating hit would silently bypass that contract and skip the
  repair-and-regeneration precondition. The marker is verified, never
  trusted: it must name this stage and exactly the candidates the fallback
  downgrades now, the raw output must fail current validation and the
  downgraded output must pass; otherwise the run fails closed ("fallback
  marker is invalid") in both refresh modes. Unmarked entries keep exactly
  the bytes earlier code wrote. No cache-key change: the key is derived
  from the request, not from file content, so cold-27 and warm-28 entries
  still hit (offline replay of a warm-28 cache copy at this code: 233 hits,
  0 calls, `final-validated.json` byte-identical to warm-28).
- P2-B (manifest cross-checks). `BoundaryOpeningFallback` now requires a
  Boundary Review subject (`<profile>.boundary.<NNN>`) and unique
  candidate IDs; the manifest requires unique (Profile, candidate) pairs
  and unique batches across fallback records, and every stale resolution
  must name a `superseding_cache_key` different from its `cache_key`.
  `validate_against(result, boundaries=...)` additionally checks that
  every fallback ID belongs to an executed Profile, exists in the run's
  final arrays (which are exactly the Boundary Review rows) and is never
  `selected`; when the run's Boundary Review output is supplied (the
  evaluation service passes it), each fallback row must exist there with
  `opening_complete=false`. The delivery export, which has no Boundary
  Review output, keeps calling `validate_against(final)` and gets every
  check except that last one.
- P3s: `reused=True` is recorded only after the superseding entry passed
  its identity check and parsed. New tests cover mis-keyed, garbage-JSON
  and symlinked cache entries for Discovery, Boundary Review and Global
  Audit with refresh off and on (all raise), and an untrusted superseding
  entry (never recorded as reused).
- No prompt, prompt hash, cache-key derivation, Discovery cache,
  `DUAL_PROFILE_ALGORITHM_VERSION`, benchmark JSON/MD, evaluator threshold,
  guard pattern or frozen `tools/loop_engineering` change.
- Tests (mock/fixture only): cold → warm fallback round trip with a
  provider that fails on any call (refresh off and on; final, Boundary and
  Global Review artifacts byte-identical; the manifest record reproduced;
  the cache untouched); five tampered-marker cases × two refresh modes;
  18 untrusted-entry cases; 3 untrusted-superseding cases; manifest
  cross-check unit tests.
- `docs/PRODUCT_SPEC.md`: Stage 12c amendment.

## warm-28 real Claude CLI warm diagnostic at a7088c4 (2026-10-30) — strict FAIL 95.0 (diagnostic only)

Evidence categories stay distinct: this run is real-model inference evidence
(warm, diagnostic, not an acceptance run); the strict evaluator result is
deterministic validation of that output; rendering plus human
editorial/audio review is a separate acceptance activity and is **not**
claimed here.

- Code: HEAD `a7088c490468cb36e48fc60fd512bf6923140593` (Stage 12b, accepted
  below). Frozen Claude CLI 2.1.308 binary, subscription login.
- Roots: `data/evaluations/dual-profile-benchmark-20261030-claude-warm-28`
  and cache `data/evaluations/dual-profile-cache-20261030-claude-warm-28`.
  The cache was copied with `cp -Rp` from the cold-27 cache (233 files,
  byte-verified). Attempt start epoch 1793383796.
- Eval rc 0 in 2510 s.
- Calls and cost: 160 cache hits (Discovery family only); 73 new calls
  (Boundary Review 52, Global Review 18, Global Audit 2, variant link 1)
  plus 4 repairs, 77 provider records; 0 retries; no 429, 529 or
  usage-limit errors. Tokens: input 7,336,802, output 740,519.
- Cache provenance: 73 new cache files, all with mtime at or after the
  attempt start; 0 of the 233 pre-existing files changed;
  `stale_cache_resolution_count` 0; `boundary_opening_fallbacks` `[]`.
- Strict result: **FAIL 95.0**, evaluator rc 1, no PASS blockers. Durable
  output: `data/evaluations/dual-profile-strict-eval-20261030-claude-warm-28`
  (evidence in its `evidence/` subfolder).
  - Short 8/8. S06 matched by `sh0009_balanced_mix_step5` (selected,
    −2300/+2860 ms).
  - Mini 5/6. L07 missed: the exact `precision_yuge…` candidate (cues
    2855–2974) was rejected as the nested duplicate of `confirm_6001180…`,
    which starts at cue 2854, −30540 ms from the anchor.
  - R01 `blocked`, R02 `manual_review`.
  - Hard failures, both on negative anchor N07 (2284100–2404200, chat,
    devices and fragments; must not pad L03):
    1. `negative_anchor_output`: `audit_sh0009_throat_tight_strong_mix_diagnosis`
       (short, `manual_review`, 2295000–2351600).
    2. `irrelevant_padding`: `ml0007_strong_mix_vs_yanyin_core` (mini,
       `manual_review`, 2369520–2538460; 34,680 ms of N07 outside L04).
- Renders: 14 clips into `<run>/renders/`, rc 0 in 253 s, all automatic
  checks pass. Human visual/audio review is PENDING.
- Read-only root-cause analysis:
  - The divergence from cold-27 happened at Boundary Review. On identical
    Discovery inputs, warm-28 Boundary Review cleared Discovery's gated
    flags without removing cues: `audit_sh0009` cleared
    `topic_switch_inside` on an unchanged interval; `ml0007_core` trimmed
    its start to cue 1036 and cleared `material_interruption` and
    `device_or_waiting_padding`. cold-27 Boundary Review kept them; Global
    Review and the Global Audit followed Boundary Review in both runs.
  - This is a pre-existing gap exposed by sampling, not a Stage 12
    regression. Ruled out: (b) both rows were unflagged after Boundary
    Review, so the gated (not advisory) flag contract never applied; (c)
    neither row was in a repaired Boundary Review batch and there were no
    fallbacks.
  - History: N07 caused a hard FAIL in 2 of 5 Claude-era runs (warm-22,
    warm-28). The warm-26 PASS survived only because its audit happened to
    deduplicate.
  - The Global Audit adjudicates only nested pairs, so the 93%-overlapping,
    non-nested pair `ml0007_core` / `audit_ml0008` (the L04 match) was never
    compared.
  - L07 was also missed in cold-27 and warm-24. The cause is a conflict
    between the Boundary Review untranscribed-gap clause and the
    song-selection trim clause. Human listening of 01:40:07.5–01:40:35.0 is
    still pending with the user.
- **User decisions (2026-10-30, binding):**
  - Fix 1: keep Discovery gated flags unless Boundary Review actually trims
    the interval.
  - Fix 2: the Global Audit also adjudicates same-Profile overlapping pairs
    whose overlap is at least 50% of the shorter candidate.
  - Both are scheduled as Stage 13; the reviewer P2s/P3s of Stage 12b are
    Stage 12c.

## Stage 12b dual-profile review fixes (2026-10-29) — ACCEPTED at a7088c4

- **Status: ACCEPTED** (2026-10-30) at
  `a7088c490468cb36e48fc60fd512bf6923140593` on local branch
  `claude/liveclip-stage8-routing` (code commit after the docs commit that
  accepted Stages 11b and 12 at `88c97e9`). Not pushed or merged.
  (History: first recorded as implemented, pending independent tester and
  reviewer.)
- Tester: **PASS** at `a7088c4`. `make lint` rc 0; backend 2893 passed in
  1675.40 s; vitest 14 files / 80; e2e 4; targeted 102. No sleep in the
  10:34–11:09 window on 2026-10-30. The machine was under high load from an
  unrelated project; there were no failures.
- Reviewer: **ACCEPT** at `a7088c4`, no P0/P1. P2-A (the Boundary Review
  opening fallback provenance is lost on a warm cache hit, because the
  fallback output is cached as if it were model output) and P2-B (the
  manifest does not cross-check `boundary_opening_fallbacks` or the stale
  resolutions) go to Stage 12c. P3s: no repo tests for mis-keyed or
  untrusted cache entries in either refresh mode, and `reused=True` is
  recorded before the superseding entry's identity check.
- Origin: the Stage 12 reviewer P2s at `88c97e9`.
- P2-1 (Controller decision): the Stage 9 fail-closed contract is the
  default again. A cached dual-profile output that fails current
  validation re-raises its validation error, exactly as before Stage 12.
  Stale-cache repair/regeneration is now opt-in through
  `liveclip dual-profile-eval --refresh-stale-cache` (service argument
  `refresh_stale_cache=False` by default). When opted in, every stale
  resolution is recorded in `run-manifest.json`:
  `stale_cache_resolutions` (stage, Profile, stale `cache_key`,
  `superseding_cache_key`, `error_summary`, `reused`),
  `stale_cache_resolution_count` and `stale_cache_refresh_enabled`. A
  later opted-in run that reuses an existing superseding entry records it
  with `reused: true`. Without the option a stale primary entry still fails
  closed even if a superseding entry exists. The manifest validator
  requires the count to match and forbids resolutions without the option.
  The new manifest fields have defaults, so earlier manifests still load.
- P2-2: the Boundary Review invariant error
  (`BoundaryOpeningInvariantError`) now lists every violating candidate ID
  in one message and is raised only after every other check passed, so
  any other failure keeps its own plain error. When the repair and the
  regeneration are exhausted and that invariant is the only remaining
  failure, `apply_boundary_opening_fallback` sets `opening_complete=false`
  on exactly those rows (only a downgrade; the flag stays), the output is
  re-validated, the IDs are recorded in the manifest's
  `boundary_opening_fallbacks`, and the run continues. Any other failure
  still fails as before.
- P2-4: the opt-in test asserts that a third run reuses the superseding
  audit entry with 0 calls.
- P2-5: the docs now say the superseding key adds the sha256 of the stale
  output's canonical JSON (`model_dump`, sorted keys), not of its bytes.
- No prompt, prompt hash, `DUAL_PROFILE_ALGORITHM_VERSION`, Discovery
  prompt, benchmark JSON/MD, evaluator threshold, guard pattern or frozen
  `tools/loop_engineering` change. The Boundary Review, Global Review and
  Global Audit prompt hashes are identical to `88c97e9`, so the warm-rerun
  estimate from the cold-27 cache (about 73 new calls, 160 hits) still
  holds; that estimate needs no `--refresh-stale-cache` because the
  re-keyed stages have no stale entries.
- Tests (mock/fixture only): restored Stage 9 test (a stale cached audit
  fails closed by default and leaves the cache unchanged); opt-in test
  (one repair, entry byte-identical, manifest records the resolution, a
  third run reuses the superseding entry with 0 calls, a run without the
  option still fails closed); the Boundary Review stale test now checks
  both default and opt-in; all-IDs message and no masking of other
  failures; invariant-only fallback and its manifest record; a fallback
  that never masks another failure; manifest audit consistency; CLI opt-in
  flag.
- Coder verification (mock/fixture only, under `caffeinate -dims` on an
  awake machine): all dual-profile and benchmark test files plus the
  affected CLI files (`tests/integration/test_dual_profile_evaluation.py`,
  `tests/unit/test_dual_profile*.py`, both benchmark-evaluator files, the
  Claude CLI provider, Codex rate-limit message, CLI retry and doctor
  files) 286 passed in 21.46 s; `PYTHONDONTWRITEBYTECODE=1
  NODE_LTS_BIN=/opt/homebrew/opt/node@22/bin make lint` rc 0. A broader
  run over every test file importing `liveclip.cli` (778 tests) had two
  `test_persistent_mock_pipeline.py` failures with `proxy_render`
  `LEASE_EXPIRED` and one transient Claude CLI fake-subprocess failure
  while the machine was sleeping or overloaded. The `LEASE_EXPIRED`
  failure reproduced on the clean baseline `f7c98dd`, so it is
  environmental. Awake reruns passed: both persistent-mock tests 2 passed,
  and the Claude CLI provider file 58 passed. (At the time, full `make
  test`, the independent tester and the reviewer were pending; all passed
  at `a7088c4`, see above.)

## Stage 12 dual-profile flag contract alignment (2026-10-29) — ACCEPTED at 88c97e9; REAL RUN PENDING

- **Status: ACCEPTED** (2026-10-29) at
  `88c97e950bd981fe5f63a9c90753b2eb39cb0f60` on local branch
  `claude/liveclip-stage8-routing`; real run pending. Not pushed or merged.
  (History: first recorded as implemented, pending independent tester and
  reviewer.)
- Tester: **PASS** at `88c97e9` (covers Stage 11b `31e6712` and Stage 12
  `88c97e9`). `make lint` rc 0; backend 2886 passed in 1681.85 s; vitest
  14 files / 80; e2e 4 passed; targeted 159 passed. No sleep in the
  18:34–19:11 window on 2026-10-29.
- Reviewer: **ACCEPT** at `88c97e9`, no P0/P1, five P2s (taken up as
  Stage 12b below).
- Origin: the read-only S06/L07 variance analysis (Stage 11 section). The
  change is general: no anchor times, IDs or wording are used anywhere.
- Prompts match the code (`clipping_skills/dual_profile_v1/stages/`):
  - `global_review.md` and `global_audit.md` no longer claim that Python
    enforces every unresolved flag. Both list the exact classes. Gated
    flags (Python forces `blocked`; the members of
    `MANUAL_REVIEW_BLOCKING_QUALITY_FLAGS`): `padded_with_irrelevant_content`,
    `sales_or_cta_padding`, `device_or_waiting_padding`,
    `material_interruption`, `topic_switch_inside`, `topic_not_closed`,
    `asr_uncertain_blocks_meaning`. Advisory flags (Python only forbids
    `selected`): `context_dependent_opening`,
    `missing_required_prior_steps`, `source_title_mismatch`. A candidate
    the reviewer judges coherent and self-contained with only advisory
    flags is `manual_review`, with the disagreement in `review_reason`.
    Rules A/B2/C/D, the equipment carve-out and all other text are kept.
  - `global_audit.md` also states that a listed pair whose members are
    both duplicates of the same third representative is `duplicate`.
  - `boundary_review.md` (one sentence): a review item that keeps
    `context_dependent_opening` must set `opening_complete` to false.
  - Discovery-family prompts and `variant_link` are byte-identical.
  - `tests/unit/test_dual_profile_flag_contract.py` parses both flag lists
    from both prompts for both Profiles and asserts they equal the code
    sets, so they cannot drift.
- Boundary Review invariant: `validate_boundary_review_output` raises a
  validation error (routed to the existing repair) when a row carries
  `context_dependent_opening` with `opening_complete=true`.
- Stale cache entries (`services/dual_profile_evaluation.py::_resolve_call`;
  **changed by Stage 12b**: this path is now opt-in through
  `--refresh-stale-cache`, the default fails closed again, and the
  superseding key adds the sha256 of the stale output's canonical JSON):
  Stage 9 made cache hits fully validated, but a failing cached output
  crashed the run. Now a cached output that fails the current validation
  is stale, not fatal: the entry is left untouched, its output goes through
  the ordinary repair path (repair, then one deterministic regeneration),
  and the result is cached under a key whose settings add
  `supersedes_cache_output_sha256` (bounded chain of 4). A later run finds
  the superseding entry as a normal hit. This applies to every
  dual-profile stage; the Stage 9 cached-audit test now asserts the stale
  audit is refused and repaired instead of failing the run. Untrusted or
  mis-keyed cache files still raise.
- Nested pairs: `validate_nested_pair_decisions` accepts `duplicate` when
  both members are rejected/blocked duplicates that resolve (cycle-safe) to
  the same third representative, as in a three-way identical cluster.
  Every other guarantee is unchanged (direct-reference duplicates,
  `distinct_objective` forbids a direct reference, exact coverage, no
  unlisted or repeated pairs).
- `DUAL_PROFILE_ALGORITHM_VERSION` is unchanged: the prompt hashes already
  change the affected cache keys, and the stale-entry path covers any
  cache whose prompt did not change.
- Cache impact for a warm rerun from the cold-27 cache: Discovery family
  (160 calls) unchanged and fully cached; Boundary Review prompt hashes
  changed for both Profiles (short `e685d6172f6f` → `3119f245c2cd`, mini
  `9a09affa78a3` → `62fedbec56dc`), so all 52 calls are new; Global Review
  (`832c171685e9` → `1faa9412f673`, `6b14c92b237e` → `aea87440f0ab`) and
  Global Audit (`6aa8a0148446` → `746b625e589b`, `13b53905799a` →
  `cb115e030631`) changed, so all 20 calls are new; the variant-link prompt
  is unchanged but its payload is built from the new final candidates, so
  expect 1 new call. Estimate: about 73 new calls (plus any repairs) and
  160 cache hits.
- `docs/PRODUCT_SPEC.md`: Stage 12 amendment.
- Unchanged: guard patterns, benchmark JSON/MD, evaluator thresholds,
  frozen `tools/loop_engineering`, Discovery prompts and hashes.
- Tests (mock/fixture only): flag-contract unit tests (9); Boundary Review
  invariant unit test; three-way cluster nested-pair unit test;
  integration tests for a fresh Boundary Review repaired by the invariant
  (advisory-only candidate stays `manual_review`), a planted violating
  cached Boundary Review repaired with the stale entry untouched and a
  superseding entry reused by a third run with zero calls, and the updated
  Stage 9 cached-audit test.
- Coder verification (mock/fixture only): all dual-profile and benchmark
  test files (`tests/integration/test_dual_profile_evaluation.py`,
  `tests/unit/test_dual_profile*.py`, both benchmark-evaluator files, the
  Claude CLI provider and Codex rate-limit message files) 267 passed in
  20.52 s; `PYTHONDONTWRITEBYTECODE=1
  NODE_LTS_BIN=/opt/homebrew/opt/node@22/bin make lint` rc 0. Full `make
  test`, the independent tester and the reviewer are pending.
- Next: independent tester and reviewer; then a real run (warm from the
  cold-27 cache, or cold) only with the user's go-ahead.

## Stage 11b guard repair fallback and repair message (2026-10-29) — ACCEPTED at 88c97e9

- **Status: ACCEPTED** (2026-10-29). Code commit
  `31e6712a054465142f5d39ad0fc12e60fc2fad4e`, verified at the tip
  `88c97e950bd981fe5f63a9c90753b2eb39cb0f60` together with Stage 12 (see
  the tester and reviewer bullets in the Stage 12 section). Not pushed or
  merged. (History: first recorded as implemented, pending independent
  tester and reviewer.)
- Origin: the Stage 11 reviewer P2s at `ed24a34`, under the binding user
  decision "rewrite first, if still unsafe block that clip, and the rest of
  the run must finish".
- Repair fallback: when the initial Global Review output passed every hard
  validator and only the deferred text guard failed, an unusable repair no
  longer fails the run. If the repair call fails (`StructuredProviderError`)
  or the rewrite fails a hard validator, the rewrite is discarded, the
  initial output is accepted and the same deterministic gate applies
  (V4/V5 and v3 → `blocked` with `deterministic_text_guard_gate`; legacy
  `semantic_global` → `rejected`). A validation event with
  `phase: repair_fallback`, `fallback: initial_output`, a reason ("repair
  output failed validation" or "repair call failed: <code>") and a fixed
  note records it. Sites: the durable executor
  (`pipeline/semantic_executor.py`), the local V4 loop
  (`_run_v4_requests`) and the local `semantic_global` helper
  (`_repair_semantic_global_review`) in `pipeline/stage_handlers.py`.
  - Durable executor: the committed `raw_output` stays the initial output,
    so durable replay revalidates it to the same accepted value; the
    discarded rewrite stays in `agent_outputs` as evidence. On a failed
    repair call `repair_spent` equals whether a repair call record exists,
    which the durable evidence check requires.
  - Local loops cache the initial output, so a later cache hit gates it
    the same way without a new call.
  - A hard-invalid initial output still fails exactly as before (including
    when the repair call fails). Cancellation and configuration errors are
    unchanged.
- Repair message: "Deterministic text guard: " is now followed first by the
  rewrite instruction ("rewrite each listed field as plain prose with the
  same meaning; no command words, file paths or shell syntax.") and then,
  per failing field, `candidate <id> <field>[ (first N chars)] matched
  "<token>"` (or `fails the EditPlan text limits` when no executable
  pattern matched). The prefix and instruction take 135 characters, so the
  legacy 240-character truncation keeps the instruction, and for the
  cold-27 shape also the field and the matched "make". The token comes from
  the new read-only `executable_text_match` in `domain/edit_plan.py`, which
  reuses the unchanged patterns in the same order; it quotes at most 40
  characters of the model's own field text and nothing else.
- v3 `suspicious_exact_top_n` is recomputed after a demotion. The
  validator sets it when the discovery count and the eligible count both
  equal the Top-N ceiling, so it was true only with eligible == discovery
  count; the gate keeps it true only while that still holds (any demotion
  clears it; a false flag can never become true).
- `docs/PRODUCT_SPEC.md`: Stage 11b amendment after the Stage 11 one.
- Unchanged: guard patterns, shared validators, dual-profile prompts and
  cache keys, benchmark JSON/MD, evaluator thresholds, frozen
  `tools/loop_engineering`.
- Tests (mock/fixture only):
  - `tests/unit/test_edit_text_guard.py` (13 → 21): message field/token
    naming and legacy truncation, non-pattern limits, matcher parity with
    the guard, v3 counter recomputation, executor fallback on a
    hard-invalid rewrite and on a failed repair call (recorded and
    unrecorded), hard-invalid initial plus failed repair still fails.
  - `tests/integration/test_edit_text_guard_pipeline.py` (37 → 58):
    deferred initial then hard-invalid or failed repair → fallback to the
    initial output and block, at every loop (V8 local V4, V9/V11/V13
    durable with replay after the EditPlan commit, `semantic_windowed` v3
    and legacy `semantic_global`, local and bounded); schema repair already
    spent → block in the local V4 and both local `semantic_global` loops;
    legacy cache retry (local and bounded).
- Coder verification (mock/fixture only): targeted pytest over the two
  Stage 11 test files plus the semantic executor, semantic lineage
  runtime, EditPlan, stage handlers, semantic profiles, structured
  transport budget, semantic unit recovery, lineage runtime pipeline,
  persistent mock pipeline, transport budget pipeline, all dual-profile and
  both benchmark-evaluator test files: 663 passed in 527.30 s;
  `PYTHONDONTWRITEBYTECODE=1 NODE_LTS_BIN=/opt/homebrew/opt/node@22/bin
  make lint` rc 0. (At the time, full `make test`, the independent tester
  and the reviewer were pending; all passed at `88c97e9`.)

## Stage 11 guard-safe text in persisted pipeline edit stages (2026-10-29) — ACCEPTED at ed24a34

- **Status: ACCEPTED** (2026-10-29) on local branch
  `claude/liveclip-stage8-routing`. Not pushed or merged. Code commit
  `ed24a346fe0d908dcecdec56ff87d250675a759b` (directly after the docs
  commit `d6b90c6`). (History: this section was first recorded as
  implemented, pending independent tester and reviewer.)
- Tester: **PASS** at `ed24a34`. `make lint` rc 0. `make test`: backend
  2844 passed, 0 failed, 0 skipped in 1629.85 s; vitest 14 files / 80
  passed; e2e 4 passed (mock review-delivery 1, real review-delivery 1,
  completion-goal-real 2); targeted 61 passed; `make test` wall time
  1851 s. No sleep in the 17:29–18:03 PDT 2026-10-29 window.
- Reviewer: **ACCEPT** at `ed24a34`, no P0/P1. The reviewer independently
  ran the backend suite (2844 passed). Its P2 findings (repair fallback
  when the guard repair returns hard-invalid output, the truncated repair
  message, test gaps, the v3 `suspicious_exact_top_n` counter) are taken up
  as Stage 11b below.
- Origin: the Stage 10 reviewer P1. In
  `src/liveclip/pipeline/stage_handlers.py` the V5 mini-lesson edit, the
  legacy mini-lesson edit, the `semantic_global`/`semantic_windowed`
  `_edit` and the V5 persisted-plan replay copied the model title, hook
  and `review_reason[:240]` straight into EditPlan. In these paths the
  model text is real product content (web review, release description,
  review package, burned title), so harmless prose that trips the
  unchanged `reject_executable_text` guard ("X make Y", a title such as
  "ffmpeg 入门") made the edit stage raise and failed the whole
  generation.
- **User decision (binding):** first ask the model to rewrite the text
  through the existing Global Review repair loop; if the rewrite still
  trips the guard, block only that clip with a deterministic flag/reason
  and let the rest of the run finish. The guard is not narrowed.
- Implementation:
  - New `src/liveclip/pipeline/edit_text_guard.py`: one EditPlan builder
    (`build_ai_edit_plan`, `profile_v4_edit_plan`) used by every build site
    and by the V5 replay, so plan construction cannot drift and is
    byte-identical for guard-passing text; `edit_plan_text_errors` probes
    each text field through the real `EditPlan` model on the same truncated
    value (so it mirrors stripping, length, display normalization and the
    guard exactly); deterministic downgrade functions.
  - The stage validators (not the shared
    `validate_profile_global_review_v4` / `validate_global_review_v3` /
    `validate_global_review`, which dual-profile evaluation and benchmarks
    share) raise `DeferredValidationError` (new, in
    `pipeline/semantic_executor.py`) after every shared validator passed.
    All repair loops (`_run_v4_requests`, the durable semantic-unit
    executor, the local `_edit` loop) spend their sole repair on it with
    an error prefixed "Deterministic text guard: " naming the field.
  - When no repair remains (rewrite still unsafe; the schema repair spent
    it; a semantic-cache hit; a durable semantic-unit outcome replay), the
    output is accepted and only the affected candidate is downgraded: V4/V5
    Profile and v3 rows to `blocked` with validation note
    `deterministic_text_guard_gate`; the legacy `semantic_global` contract
    has no blocked bucket, so its selected/manual row becomes `rejected`
    with `deterministic_text_guard_changed_kept_to_rejected`. Statistics
    stay consistent; Python never rewrites model text and never promotes a
    Top-N-excluded candidate. Hard validation errors still fail as before.
  - No new enum: validation notes are free strings, so schemas, web types
    and the exported EditPlan JSON Schema are unchanged.
  - `docs/PRODUCT_SPEC.md` records the behavior (amendment 2026-10-29).
- Unchanged: guard patterns; dual-profile prompts, cache keys and
  `DUAL_PROFILE_ALGORITHM_VERSION`; benchmark JSON/MD and evaluator
  thresholds; the frozen `tools/loop_engineering` files.
- Tests (mock/fixture only, no model calls):
  - `tests/unit/test_edit_text_guard.py` (13): the isolated plain "make"
    false positive; the "ffmpeg 入门" title; truncation/stripping parity;
    byte-identical plans; V4/v3/legacy downgrades (only the violator,
    statistics, no promotion, identity for passing text); executor repair,
    accepted rewrite, schema-repair-spent and hard-failure paths.
  - `tests/integration/test_edit_text_guard_pipeline.py` (37): full mock
    pipeline runs for mini-lesson configs V8 (legacy), V9, V11 and V13 and
    for `semantic_windowed` v3 and legacy `semantic_global`, each local and
    bounded, with a "make" reason and an "ffmpeg 入门" title that are either
    repaired by the mock rewrite or blocked; lineage runs crash once after
    the EditPlan commit so the replay re-applies the gate; cache and
    durable-outcome retries block without new model calls; every run
    completes.
  - Stage 10 P2 nits: the Agent render test now also runs the plain "make"
    reason alone; a new dual-profile render test covers the
    `manual_review` product strings.
- Coder verification (mock/fixture only): targeted pytest over the 15
  affected files (new tests, stage handlers, semantic executor/unit
  recovery, lineage runtime, persistent mock pipeline, transport budget,
  semantic profiles, EditPlan, dual-profile render, Agent delivery) 468
  passed in 453.38 s; further checks 7 passed (import-only, review-delivery,
  asset-integrity, worker-race integration), 170 passed (dual-profile and
  benchmark unit), 681 passed (semantic global/lineage/validation unit);
  `PYTHONDONTWRITEBYTECODE=1 NODE_LTS_BIN=/opt/homebrew/opt/node@22/bin
  make lint` exit 0. (At the time, full `make test`, the independent tester
  and the reviewer were pending; see the tester and reviewer bullets above.)

## Stage 10 render guard false positive (2026-10-23) — ACCEPTED at 0515ef7

- **Status: ACCEPTED** on local branch `claude/liveclip-stage8-routing`.
  Not pushed or merged. Code commit
  `0515ef75f93b68b1bc57794a0c8f356d7c00023e`.
- Root cause: `render_dual_profile_candidates` copied the model
  `review_reason[:240]` and the title/hook into the guarded EditPlan
  fields. The unchanged `reject_executable_text` guard then matched the
  English word "make" in candidate `sh0006_breathy_mix_vs_leak`, and the
  cold-27 render failed closed after 5 of 14 clips.
- Fix: the guarded EditPlan fields (title, hook, reason) now carry
  deterministic product text built from validated enums and the score, in
  both the dual-profile and the Agent render paths. Model prose stays in
  the final JSON, the render manifest and the review package. The guard
  and its patterns are unchanged.
- Tester: PASS at `0515ef7`, no sleep in the window: `make lint` rc 0;
  `make test` rc 0, backend 2792 passed in 1444.08 s, vitest 14 files /
  80 tests, e2e mock 1, real review-delivery 1, completion-goal 2;
  targeted 25 passed.
- Reviewer: ACCEPT. P2 nits: the Agent test mixes "make" with "rm -rf",
  so it does not isolate the plain "make" false positive; the
  `manual_review` strings have no coverage.
- Reviewer P1 (decided by the user, Stage 11 below): the persisted
  pipeline edit stages in `src/liveclip/pipeline/stage_handlers.py` still
  put model `review_reason[:240]` and title/hook straight into EditPlan.

### cold-27 real Claude CLI acceptance attempt (2026-10-23, frozen Claude CLI 2.1.308, subscription login)

This is a fresh, resumable acceptance attempt, not a warm diagnostic.
Evidence categories stay distinct: this run is real-model inference
evidence; the strict evaluator result is deterministic validation of that
output; rendering plus human editorial/audio review is a separate
acceptance activity and is **not** claimed here.

- Code: HEAD `e173c28d9ef076ba2a730f42ca57829a34e01e24` (Stage 9 code).
- Roots: `data/evaluations/dual-profile-benchmark-20261023-claude-cold-27`
  and `data/evaluations/dual-profile-cache-20261023-claude-cold-27`. Both
  were absent at the start and the cache started empty. Doctor and
  `smoke-claude` OK.
- One segment (no cold-27b was needed); no usage limit was hit. Eval rc 0
  in 3756 s.
- Calls: `cache_hits` 0; 233 calls (Discovery 160, Boundary Review 52,
  Global Review/Audit 20, variant link 1); 239 provider records; 6
  repairs; 0 retries; no 429, 529 or usage-limit errors. Tokens: input
  11,460,411, output 1,059,863. Latency per call: median 26.4 s, p95
  98.9 s.
- Provenance: 233 cache files, all with mtime at or after the attempt
  start (epoch 1792779597). None is content-identical to any of the 3972
  key files in 20 earlier roots; 81 file names also appear in earlier
  roots, which is expected because cache keys are deterministic.
- Strict result: **PASS 95.0**, evaluator exit 0, 0 hard failures.
  - Components: short 20, mini 25, risk 10, boundary 15, both Profiles 15,
    audit 10.
  - Short 8/8. S06 matched by `sh0009_balanced_mix_step5` (selected,
    −2300/+2860 ms).
  - Mini 5/6, L01–L05 hit. L07 missed: all three boundary-matching
    candidates carry `context_dependent_opening` (blocked/rejected); the
    kept `precision_yuge_highnote_nasal_rhinitis_closed_loop` starts
    −30540 ms early.
  - R01 blocked; R02 `manual_review`.
  - The second auto-selected clip `audit_sh0011_self_taught_era_intuition`
    lies inside supplemental O01; no gate applies.
  - Twin union: 0 of 23 groups differ on gated flags after the union.
    Nested pairs: short 0; mini 36 (16 `duplicate`, 20
    `distinct_objective`).
  - Durable strict-eval output:
    `data/evaluations/dual-profile-strict-eval-20261029-claude-cold-27`.
    (2026-10-29 update: this output is complete, strict **PASS 95.0**. The
    provenance proof was rebuilt there read-only; its attempt-start epoch
    comes from the runner's report because the original
    `attempt-start.txt` was lost. An earlier version of this record said
    the output was still being written by a runner.)
- Comparison: cold-18 FAIL 90.0 / warm-26 PASS 97.5 (diagnostic) /
  cold-27 PASS 95.0. L07 and S06 vary between runs with the model's
  `context_dependent_opening` judgments.
- S06/L07 variance analysis (2026-10-29, read-only over the ignored run
  artifacts; no model calls):
  - warm-26 and cold-27 had identical prompt hashes and identical
    Discovery inputs, so their differences come purely from model
    sampling. cold-18 used gpt-5.6-sol through `codex_cli` with older
    prompts and is not comparable.
  - S06 (missed in warm-26): Boundary Review kept a Discovery
    `context_dependent_opening` flag on the candidate while also setting
    `opening_complete=true`. Global Review disagreed with the flag but
    chose `blocked` because the review prompts claimed that Python
    enforces every unresolved flag. Python actually gates only
    `MANUAL_REVIEW_BLOCKING_QUALITY_FLAGS`; advisory flags only forbid
    `selected`.
  - L07 (missed in cold-27): the anchor start sits after a 27.46 s
    untranscribed gap (01:40:07.540–01:40:35.000). 3 of 6 Boundary Review
    calls started at setup cue 2854 to capture the gap; the single Global
    Audit then chose the cue-2854 version as the representative, which is
    −30540 ms from the anchor.
  - Human listening of that gap is pending with the user.
  - Follow-up: a general flag-contract alignment that is not tuned to any
    anchor (planned as Stage 12).
- Renders:
  - The first attempt into `<run>/renders/` failed closed after 5 of 14
    clips (the Stage 10 bug). That partial directory has no manifest and
    is kept untouched.
  - The re-render at `0515ef7` into `<run>/renders-r2/` succeeded: rc 0,
    244 s, 14 clips. Automatic checks (decode, black-frame, edge) passed;
    h264_videotoolbox 1080x1920. The sha256 of `final-validated.json` and
    `run-manifest.json` is unchanged by the render.
  - Human visual and audio review is **PENDING**.
- Open follow-ups: Stage 11 (persisted pipeline edit stages; ACCEPTED at
  `ed24a34` on 2026-10-29, see the Stage 11 section above; first recorded
  here as implemented, pending verification);
  human review of the `renders-r2` clips; an optional holdout livestream
  (overfitting risk: the prompts were tuned on one transcript); the
  L07/S06 run-to-run variance (analysed read-only above; human listening
  of the L07 gap pending); push and merge only with explicit user consent.

## Stage 9 dual-profile routing and review-prompt batch (2026-10-22) — ACCEPTED at 56aa93c

- **Status: ACCEPTED** (2026-10-22) on local branch
  `claude/liveclip-stage8-routing`. Not pushed or merged. Code commits:
  - `bfdef3bee12c664bf6b0f21cad86eb656d6a0635`: same-interval gated-flag
    union (a `selected`/`manual_review` twin that inherits a gated flag
    becomes `blocked`, never raising; advisory flags and
    `source_title_mismatch` are not shared); risk records excluded by Top-N
    are retained as `blocked`; final `evidence_cue_ids` are limited to the
    final interval (raw Discovery artifacts keep the originals); a fresh
    Global Audit must also decide nested pairs its own replacements create.
  - `703cfbbf1f3b5815f1db3dca409ae6b2607e8336`: consolidated review-prompt
    batch in `stages/boundary_review.md`, `global_review.md` and
    `global_audit.md` only (rules A, B2, C, D plus the reviewer P2
    wording). Discovery prompts are byte-identical and their hashes stay
    pinned.
  - `56aa93c15b56c9a0f2d226c1203166365dca4b87`: review fix. The Global
    Audit cache-hit leniency is removed, so cache hits are re-validated
    with the same rule as fresh outputs (safe because pre-rule audits
    carry an older audit prompt hash); the equipment/audibility carve-out
    (a speaker's brief explanation of their own equipment or of why moving
    closer helps listeners hear is part of the demonstration; an
    audibility check is asking or answering whether someone can hear;
    "lag" is connection lag); the duration-minimum wording ("no longer
    satisfies the Profile duration minimum"; a closing acknowledgement is
    neither padding nor subtracted); the softened untranscribed-gap rule;
    a comment on why twins share `topic_switch_inside`/`topic_not_closed`.
- Routing-policy marker: `quality-gate-risk-routing-v3` (v1, v2 and a
  missing marker still load). `DUAL_PROFILE_ALGORITHM_VERSION` unchanged.
- Reviewer round 1 at `703cfbb`: CHANGES_REQUIRED. P1: a warm run crashed
  on a cached audit that had decided a pair created by its own
  replacements (the lenient cache-hit validator rejected it as unlisted).
  P2: prompt anchor risks for L01/S04 (equipment/audibility carve-out too
  narrow), S08 (duration-minimum wording) and rule C (untranscribed gaps).
  Re-review: ACCEPT for `4f2c068..56aa93c`.
- Tester: PASS at `56aa93c` on AC, no sleep: `make lint` exit 0; `make
  test` x2 exit 0, backend 2790 passed / 0 failed / 0 skipped each
  (1433.30 s, 1421.72 s), vitest 14 files / 80 tests, e2e 4/4 both runs;
  targeted 182 passed. Logs: `/private/tmp/claude-501/-Users-junhuaxu-autoclip-claude/11442fc6-5e35-49d6-afb1-e25ebe8c47b5/scratchpad/stage9-56aa93c/`.
- Coder evidence (offline, no model calls): replays and cache predictions
  under `/private/tmp/claude-501/-Users-junhuaxu-autoclip-claude/11442fc6-5e35-49d6-afb1-e25ebe8c47b5/scratchpad/stage9-B/`, `/private/tmp/claude-501/-Users-junhuaxu-autoclip-claude/11442fc6-5e35-49d6-afb1-e25ebe8c47b5/scratchpad/stage9-C/` and `/private/tmp/claude-501/-Users-junhuaxu-autoclip-claude/11442fc6-5e35-49d6-afb1-e25ebe8c47b5/scratchpad/stage9-D/`. Against the
  warm-24 cache: all 160 Discovery-family calls hit, 75 misses (Boundary
  54, Global Review 18, Audit 2, Variant 1); warm-24 replay FAIL 92.5 with
  only `audit_squeezed_voice_channel_no_shouting_136_178` moving to
  `blocked`.
- **Never use the scratch caches** under `/private/tmp/claude-501/-Users-junhuaxu-autoclip-claude/11442fc6-5e35-49d6-afb1-e25ebe8c47b5/scratchpad/stage9-C/predict-*` and
  `/private/tmp/claude-501/-Users-junhuaxu-autoclip-claude/11442fc6-5e35-49d6-afb1-e25ebe8c47b5/scratchpad/stage9-D/predict-*` (or the earlier `stage8-f3/predict-*`) as a
  warm-cache source: they contain synthetic, replayed outputs.

### Real Claude runs after Stage 9 (2026-10-22, frozen Claude CLI 2.1.308, subscription login)

Warm runs are **diagnostic only**: their Discovery outputs came from
cold-21/warm-22, and the review prompts were iterated against this same
transcript. They are not acceptance evidence.

- warm-25 (diagnostic, Stage 9 code, cache from warm-24): stopped on the
  subscription usage limit after 2474 s with 73 of the 75 new calls
  cached. Not a quality result. Raw twin disagreement on gated flags was
  6/24 (warm-24: 9/24).
- warm-26 (diagnostic, Stage 9 code, cache from warm-25, `cache_hits` 233,
  2 new calls plus 1 audit repair, 1194 s): strict **PASS 97.5**, no hard
  failures, no PASS blockers.
  - Short 7/8: S03 is now hit; S06 is missed because its only candidate
    `sh0009_step5_balanced_mix` was model-blocked with
    `context_dependent_opening`.
  - Mini 6/6 (L07 is back). R01 and R02 routed (blocked).
  - `sh22_find_voice_from_phonation` (N09) is now blocked; the forbidden
    composite cleared.
  - Informational: N08 manual review; title/hook faithfulness.
  - Post-union twin disagreement on gated flags: 0/24.
  - 13 renders passed automatic checks (S06 not rendered); human visual
    and audio review is pending.
- (Historical; cold-27 ran, see the Stage 10 section above.) **Next step:** a fresh acceptance run (method pending a user decision
  because of the subscription quota), then human editorial/audio review,
  then push/merge only with explicit operator consent.

## Stage 8 dual-profile routing and review-stage fixes (2026-10-22) — ACCEPTED at 4f2c068

- **Status: ACCEPTED** (2026-10-22) on local branch
  `claude/liveclip-stage8-routing` (from `b3a4fbe`). Not pushed or merged.
  Code commits:
  - F1 `28c9ca1d8d342a4a097a904ec9ac943be867be8d`: final status agrees with
    the merged quality flags. A `manual_review` row whose merged Boundary ∪
    Global Review flags include `padded_with_irrelevant_content`,
    `sales_or_cta_padding`, `device_or_waiting_padding`,
    `material_interruption`, `topic_switch_inside`, `topic_not_closed` or
    `asr_uncertain_blocks_meaning` becomes `blocked` ("Deterministic quality
    gate: …"). `context_dependent_opening` and
    `missing_required_prior_steps` stay advisory. Python only downgrades.
  - F2 `1b18ec14010ef53b4f705cbd5a1120675f219688`: a `rejected` record of the
    dedicated risk-discovery pass is retained as `blocked` ("Deterministic
    risk routing: …"), keeping its duplicate reference and evidence. The
    set `risk_record_ids` is derived structurally from the risk pass
    outputs, never from ID prefixes. **User decision:** this
    rejected → blocked exception is approved; `docs/PRODUCT_SPEC.md` records
    it next to "never … upgrades a model rejection".
  - F3–F5 `4f2c06821777bbb93dc95605554f1aa1e865f0e0`:
    - F3a: the Boundary evidence-cue lock applies only to risk-pass
      records; risk tags stay cumulative for every candidate.
    - F3b: Boundary and Global Review payloads carry a structural
      `discovery_pass`; the boundary prompt keys risk handling on it.
    - F3c: boundary edge audit (setup versus premise; CTA, device, chat and
      filler edges are padding regardless of duration needs).
    - F4: the `nested_pair_decisions` contract (below).
    - F5: `context_dependent_opening` only when the opening cannot be
      recovered inside the interval; same-concept application is payoff;
      Boundary flags are cumulative and enforced by Python. **User
      decision:** context-only candidates stay blocked (no deterministic
      broadening).
  - Only `stages/boundary_review.md`, `stages/global_review.md` and
    `stages/global_audit.md` changed among the prompts; Discovery prompts,
    schema, `main.md`, profiles, `repair.md` and
    `DUAL_PROFILE_ALGORITHM_VERSION` are unchanged, and a test pins the
    Discovery-family prompt hashes so the Discovery cache stays valid.
- Routing-policy marker: `DualProfileFinalResult.routing_policy_version`
  is optional. `manual-review-quality-gate-v1` (F1) and
  `quality-gate-risk-routing-v2` (F1+F2, written by new runs) both load, and
  older artifacts without the field load as `None`.
- `nested_pair_decisions` contract (F4): Python lists, from the initial
  Global Review, every same-Profile pair of `selected`/`manual_review`
  candidates that share a start or end cue (so one contains the other) and
  sends it as `nested_pairs` to the Global Audit. The required
  `ProfileGlobalAuditOutput.nested_pair_decisions` must decide each listed
  pair exactly once as `duplicate` (one row `rejected`, or `blocked` for a
  risk-pass record, with `duplicate_of_candidate_id` naming the other) or
  `distinct_objective` (neither references the other), each with a reason.
  Containment alone never decides duplication. Failures use the existing
  repair path; old cached audit outputs cannot be reused because the audit
  prompt hash and payload both changed.
- Tester: PASS at `4f2c068` on AC, no sleep: `make lint` exit 0; `make test`
  x2 exit 0, backend 2778 passed / 0 failed / 0 skipped each (1425.50 s,
  1442.41 s), vitest 14 files / 80 tests, e2e 4/4 both runs; targeted 170
  passed. Logs: `/private/tmp/claude-501/-Users-junhuaxu-autoclip-claude/11442fc6-5e35-49d6-afb1-e25ebe8c47b5/scratchpad/stage8-4f2c068/`.
- Reviewer: ACCEPT at `4f2c068`, no P0/P1, six P2s. The code P2s (Top-N
  risk routing, final evidence filtering, post-audit nested pairs) and the
  prompt-wording P2s are scheduled in Stage 9. Two doc P2s from the
  earlier `b3a4fbe` review (frozen-canary wording, email residual context)
  are fixed in the Stage 7 runbook section below.
- Coder evidence (offline, no model calls): replay logs under
  `/private/tmp/claude-501/-Users-junhuaxu-autoclip-claude/11442fc6-5e35-49d6-afb1-e25ebe8c47b5/scratchpad/stage8-f1/`, `/private/tmp/claude-501/-Users-junhuaxu-autoclip-claude/11442fc6-5e35-49d6-afb1-e25ebe8c47b5/scratchpad/stage8-f2/` and `/private/tmp/claude-501/-Users-junhuaxu-autoclip-claude/11442fc6-5e35-49d6-afb1-e25ebe8c47b5/scratchpad/stage8-f3/`, including the
  cache prediction against the warm-22 cache (all 160 Discovery-family
  calls hit; 75 misses: Boundary 54, Global Review 18, Audit 2, Variant 1).

### Real Claude runs (2026-10-22, frozen Claude CLI 2.1.308, subscription login)

Evidence categories stay separate: these are real model runs scored by the
strict (Stage 4) evaluator. Warm runs reuse a cache and are **diagnostic
only**; acceptance needs a fresh cold run (`cache_hits=0`, about 230 calls).

- cold-21 (`data/evaluations/dual-profile-benchmark-20261022-claude-cold-21`):
  stopped on the subscription usage limit after 1576 s with 115 calls
  cached. Not a quality result.
- warm-22 (diagnostic, Stage 7 code, `cache_hits` 115, 120 new calls):
  strict **FAIL 90.0**; short 6/8, mini 6/6; R01 misrouted (its full-coverage
  candidates were rejected as duplicates of a blocked row); padding x2;
  forbidden composite interval.
- warm-22 offline replay with F1+F2 (no model calls): strict **FAIL 95.0**;
  R01 matched by `risk_two_faults_vocal_closure_parent` (blocked); remaining
  hard failure `irrelevant_padding`.
- warm-23: stopped on the subscription usage limit (73 of the 75 new calls
  cached). Not a quality result.
- warm-24 (diagnostic, Stage 8 code at `4f2c068`, `cache_hits` 233, 2 new
  calls plus 1 repair, 653 s): strict **FAIL 92.5**, no PASS blockers.
  - Short 7/8 (S03 blocked); mini 5/6 (L07 lost); R01 and R02 routed.
  - Hard failures: `negative_anchor_output` (`sh22_find_voice_from_phonation`
    in N09) and `forbidden_composite_interval`
    (`audit_squeezed_voice_channel_no_shouting_136_178`).
  - Renders of the 12 matched clips passed automatic checks; human
    editorial/audio review is pending.
- Subscription quota is a real constraint: cold-21 and warm-23 both hit the
  usage limit. Start the cold acceptance run right after a limit reset.
- (Historical; Stage 9 is ACCEPTED, see above.) **Next step:** Stage 9 (same-interval flag union, Top-N risk routing,
  final evidence filtering, post-audit nested pairs, consolidated review
  prompt batch), then warm-25 as a diagnostic, then the cold acceptance
  run.

## Integration of Stages 6 and 7 on accepted Stage 4 (2026-10-22) — Stages 6 and 7 ACCEPTED at 996962b

- Branch `claude/liveclip-stage7-claude-cli` now holds, in order: Stage 4
  (ACCEPTED at `8b14aa3`, acceptance docs `0bb4af4`), Stage 6 rebased onto
  `0bb4af4`, and Stage 7 rebased onto the Stage 6 tip. Local only; not
  pushed or merged.
- Rebased SHAs (old -> new):
  - Stage 6: `a22f9d3` -> `cef7d4b`, `670478e` -> `9a9cfc8`, `039c998` ->
    `a7bbbf0`, `fc06b3e` -> `84dd4a8`, `7de4760` -> `5a7641e`, `f824df0` ->
    `437ebb8`; plus new message-only test commit `fc13163` (reviewer P2 #2:
    the `_wait_for_polls` timeout reports observes, heartbeats, thread
    liveness and `lost_lease`).
  - Stage 7: `84fe07e` -> `9eb7a38`, `7340355` -> `e744935`, `fe4350a` ->
    `850e0af`, `8ca7bba` -> `2865336`, `ad30372` -> `4e2bf8f`, `a010714` ->
    `db2bc32`.
- Code identity: the non-doc diff (excluding `STATUS.md`, `docs/**`,
  `tasks/**`) of each rebased branch against its new base is byte-identical
  to the reviewed diff against its old base (`cmp` exit 0 for both; sha256
  `d0873f86...` for Stage 6 and `176bd64d...` for Stage 7). Only doc files
  conflicted; every section was kept (Stage 7 above Stage 6 above Stage 4).
- The frozen Claude CLI 2.1.308 binary is in the ignored
  `.cache/claude-cli/2.1.308/claude` (mode 0555, sha256
  `ca923c86ac84b30574a82331a05b6e066c27477a926ceaffe46a845a33e4dd37`).
- (History: Stages 6 and 7 awaited the integrated test and review round on
  this tip; Stage 7 round 3 (`4e2bf8f`, `db2bc32`) was reviewed with it.)
- **Stage 6 ACCEPTED** (code `a22f9d3` rebased to `cef7d4b`..`437ebb8`, plus
  diagnostics commit `fc13163`) and **Stage 7 ACCEPTED** (code through
  `4e2bf8f`, docs `db2bc32`), both verified at the integrated tip
  `996962b1041181317430ad9463cf6042aac01786` (2026-10-22). Local only; not
  pushed or merged.
  - Tester: PASS at `996962b`, on AC power, with 0 sleep/wake entries in
    every window:
    - `make lint` exit 0;
    - `make test` twice, both exit 0: backend 2752 passed, 0 failed,
      0 skipped each (1411.10 s and 1413.74 s); vitest 14 files / 80 tests;
      e2e 4/4 in both runs;
    - lease and suspend set 51 passed x 3;
    - provider tests 76 passed; benchmark tests 130 passed;
    - `liveclip doctor` `claude_cli` pass with the frozen path:
      `reviewed_version` 2.1.308, `auth_method` `claude.ai`,
      `subscription` true, contract
      `claude-cli-editorial-v1.2.1.308.d65edfc7c242edac24dbf6180a38d31f9df396615005e549f168da7e73e9bbbe`;
      0 email matches in the saved output;
    - 1323 pre-existing `playwright-report` files hash-identical.

    Logs: `/private/tmp/claude-501/-Users-junhuaxu-autoclip-claude/11442fc6-5e35-49d6-afb1-e25ebe8c47b5/scratchpad/integrated-996962b/`.
  - Reviewer: ACCEPT at `996962b`. The code is byte-identical to the
    reviewed commits and there is no Stage 6 x Stage 7 interaction. Three
    doc P2s were fixed in the docs-only commit that follows `996962b`:
    1. the Stage 4 branch-tip rule now names the range `8b14aa3..0bb4af4`;
    2. the authorization rationale above names the Claude CLI engine and
       the subscription-only login;
    3. the isolation canary was re-run against the frozen binary (see the
       Stage 7 runbook).
  - Evidence categories: deterministic validation plus real subscription
    smoke and canary calls. No benchmark run, rendering or human review is
    part of this acceptance.
- (Historical; superseded by the Stage 8 section above.) **Next step:** the real Claude benchmark cold-21 via the Stage 7 runbook:
  new evaluation and cache roots, the frozen binary
  (`LIVECLIP_CLAUDE_EXECUTABLE` = the absolute `.cache/claude-cli/2.1.308/claude`
  path, `LIVECLIP_STRUCTURED_PROVIDER=claude-cli`), doctor plus one
  `smoke-claude` first, `dual-profile-eval --discovery-concurrency 3`, then
  the strict (Stage 4) evaluator. Compare with cold-18, which is a strict
  FAIL 90.0.

## Stage 7 Claude CLI structured provider (2026-10-21) — ACCEPTED (code through 4e2bf8f, docs db2bc32)

- **Status: ACCEPTED** (2026-10-22): code through
  `4e2bf8f616fdb5018df9f92cad2a0c633699fe43`, docs
  `db2bc3259167c8d9baca3ce9e137f1319459ba9b`, verified at the integrated
  tip `996962b`. Tester PASS and reviewer ACCEPT; evidence in the
  integration section above. Not pushed or merged.
- Previous status (kept for history): IN PROGRESS, pending tester and
  reviewer acceptance, on local
  branch `claude/liveclip-stage7-claude-cli`, created from `ca80fb7` (Stage 4
  docs tip). Code commit: `84fe07efda188fcf49008908129f93571a74f0cd`. Not pushed or merged.
- Operator directive (2026-10-21): the dual-profile understanding engine
  switches to the local Claude Code CLI. Reason: the real benchmark runs
  cold-19 and cold-20 failed within about 7 s. The Codex ChatGPT login
  returned 429 Too Many Requests on the concurrent Discovery burst, and the
  pipeline reported only "structured model output could not be validated".
  Real Claude CLI calls are authorized through the subscription login only,
  never an API key.
- What changed:
  - New `ClaudeCliStructuredLLMProvider` (`src/liveclip/providers/llm/claude_cli.py`).
    It mirrors the Codex structured provider: the same prompts and payloads,
    the same strict schema, the single schema repair, and the same
    `provider-calls.json` and `run-manifest.json` records with
    `provider=claude_cli`.
  - Selection: `LIVECLIP_STRUCTURED_PROVIDER=auto|codex-cli|claude-cli`
    (default `auto`, which keeps the historical Codex mapping). A separate
    setting is used because `LIVECLIP_AI_PROVIDER` also selects ASR and is
    persisted in pipeline run identity.
  - Settings: `LIVECLIP_CLAUDE_EXECUTABLE` (default `claude`),
    `LIVECLIP_CLAUDE_MODEL` (default `claude-opus-5-5`), a 900 s timeout,
    and retry settings (5 attempts, 5 s base, 60 s per-wait cap, 300 s
    total-wait cap).
  - Efforts map one-to-one: medium for Discovery, high for boundary and
    global review.
  - Version pin: CLI `2.1.307` only. The contract identity
    `claude-cli-editorial-v1.<version>.<sha256>` binds the executable hash,
    the version, the security profile and an argv-template hash. Cache keys
    therefore never mix Codex and Claude results.
  - Rate limits: 429, 529, 5xx and connection errors get exponential
    backoff with equal jitter. Retries are counted in the call record's
    `request_count`/`retry_count`. On exhaustion the error names the cause,
    for example "Claude CLI rate limited (429) after 5 attempts". A
    subscription usage cap and schema failures are never retried as rate
    limits.
  - Codex (small): a 429 now surfaces as "Codex CLI rate limited (429 Too
    Many Requests) after N attempt(s)". A zero-exit run with no final message
    but a 429 error event no longer consumes the schema repair. Codex retries
    were not added.
  - `liveclip doctor` gains a `claude_cli` check (version, contract, logged
    in, auth method type, subscription yes/no). New `liveclip smoke-claude`
    and `make smoke-claude`. `run_cancellable_process` gains an optional
    `cwd`.
- Isolation and auth design, verified with real calls:
  - argv: `--print --output-format json --json-schema <schema> --model
    --effort --no-session-persistence --tools= --disallowed-tools <list>
    --permission-mode dontAsk --permission-prompts none
    --disable-slash-commands --strict-mcp-config --mcp-config
    {"mcpServers":{}} --setting-sources= --safe-mode --system-prompt
    <minimal>`. The LiveClip prompt goes on stdin unchanged, with cwd set to
    a fresh empty temp directory.
  - `--bare` is not used. Its help says OAuth and keychain are never read; a
    real `--bare` probe without an API key returned "Not logged in".
  - The child env is an allowlist (HOME, PATH, USER, LOGNAME, TMPDIR, LANG,
    LC_ALL, SSL_CERT_FILE, SSL_CERT_DIR). `ANTHROPIC_*`, `CLAUDE_CODE_*` and
    `CLAUDECODE` are never passed. The run factory refuses any login whose
    `claude auth status` method is not `claude.ai` with provider
    `firstParty`.
  - Real probe in a canary directory with a planted `CLAUDE.md` and project
    hooks: no CLAUDE.md, memory, skills, MCP servers, plugins or hooks were
    seen, and the hook did not fire. The only tool was the built-in
    `StructuredOutput`. A control run with default flags did see the
    canary, the skills and the MCP servers.
  - Residual context that cannot be removed without `--bare`: an
    environment block (temp cwd, platform, date, model name) and an
    auto-attached account-email reminder. Neither is a credential.
  - No new `~/.claude/projects` or `~/.claude.json` project entries appeared.
- Real-call evidence (authorized, subscription login, auth method
  `claude.ai`):
  - `smoke-claude`: succeeded, 4542 ms, 1 request, schema valid.
  - Real dual-profile Discovery on the committed fixture
    `tests/fixtures/8-30-full-transcript.srt`, `claude-opus-5-5`, effort
    medium. All three calls passed schema and deterministic validation with
    no repair and no retry:
    - `short_highlight` window 0: 6.6 s, 0 candidates;
    - `short_highlight` window 5: 37.0 s, 5 candidates;
    - `mini_lesson` window 2: 31.0 s, 3 candidates (the last two ran
      concurrently).
  - The full 75-minute benchmark was **not** run; the Controller dispatches
    it separately.
- Coder checks: see the Stage 7 Progress entry in
  `docs/exec-plans/liveclip-agent-runtime-v2.md`. Logs:
  `/private/tmp/claude-501/-Users-junhuaxu-autoclip-claude/11442fc6-5e35-49d6-afb1-e25ebe8c47b5/scratchpad/stage7-coder/`.
- Caveats: deterministic tests use fake `claude` executables. Real calls
  prove only the smoke and three Discovery windows, not benchmark quality.
  `provider-calls.json` carries transport retries per call. The manifest
  `retry_count` still counts only the semantic retries made by
  `dual_profile_evaluation`.

- **Review round 1 at `7340355`: CHANGES_REQUIRED (2 P1, 7 P2).** Fixes are
  in code commit `fe4350a7ed8b553a9aca980bf78238f42fe6a3ed`, pending tester
  and reviewer. Not pushed.
  - P1-1 (auth gate only once per run): `require_claude_subscription` now
    runs in the provider constructor and before every inference call, next
    to the contract re-check. If the login changes to an API key, a Console
    account or a managed `apiKeyHelper`, the next call is refused before
    launch.
  - P1-2 (stale pin): the installed CLI auto-updated to 2.1.308. The full
    re-review found no drift:
    - the `--help` and `auth status --help` texts are byte-identical to
      2.1.307;
    - the production-argv canary (planted CLAUDE.md plus project hooks)
      showed no CLAUDE.md, memory, skills, MCP or plugins, and the hook did
      not fire; the only tool was `StructuredOutput`;
    - the default-flag control saw the canary, 48 tools and 36 skills, and
      fired the hook;
    - `--bare` without a key returned "Not logged in";
    - auth status reported `claude.ai` / `firstParty`;
    - `smoke-claude` succeeded (4543 ms, 1 request).

    The constant is now `2.1.308`, with a reviewed bump procedure in the
    code comment: diff the help texts, run the canary plus control, run the
    bare and auth probes, run one real smoke, and stop on any drift.
  - Auto-update: `DISABLE_AUTOUPDATER=1` is forced into every child,
    including the version and auth probes. The user's global Claude
    settings are unchanged. An interactive Claude session that auto-updates
    the binary mid-run changes the executable hash and version, so the next
    call aborts fail-closed. The operator can disable auto-update during
    benchmarks.
  - P2s:
    - Codex: quota and usage-cap markers are classified before the bare-429
      rule, and a zero-exit quota event also skips the schema repair. In
      full, round 1 widened 429 detection and added a zero-exit path;
      round 2 added the cap-first ordering.
    - Tool activity is checked first.
    - The account email from the auth probe stays in memory only
      (`repr=False`). An answer containing it, case-insensitively, is
      `STRUCTURED_OUTPUT_INVALID`, and its output is dropped from the repair
      payload, diagnostics and messages.
    - `LIVECLIP_CLAUDE_MODEL` must be a full `claude-` ID; aliases are
      rejected.
    - The contract identity binds the env allowlist and the forced env
      values.
    - New tests cover:
      - malformed auth probes;
      - probe env;
      - cancellation during backoff;
      - the `_resolve_call` exhaustion message;
      - the auth flip between calls.
  - Controller decisions:
    - the pin stays a code constant;
    - the email is accepted as residual context, with the guard;
    - no manifest schema change;
    - the code default concurrency stays 5, and **the first Claude benchmark
      uses `--discovery-concurrency 3`**.
  - Round 2 checks:
    - ruff, format, mypy and schema exit 0;
    - targeted pytest 670 passed, exit 0;
    - the full suite was left to the tester, as directed.

    Logs: `/private/tmp/claude-501/-Users-junhuaxu-autoclip-claude/11442fc6-5e35-49d6-afb1-e25ebe8c47b5/scratchpad/stage7-coder/round2/`.
  - Probe hygiene: the default-flag control and the `--bare` probe each
    created a `~/.claude/projects` entry (a memory directory and a session
    file). The coder removed both. Production-argv runs created none.

- **Review round 2 at `8ca7bba`: ACCEPT with 3 non-blocking P2s.** Round 3
  code commit `ad3037213fdfc1cf3090adc2a034b8cdbab2ffef`. Not pushed.
  - The subscription login is re-checked after each backoff sleep, before
    the relaunch.
  - `liveclip doctor` warns (does not fail) when `claude auth status`
    reports no account email, because the output identity guard is then
    inactive. Only the boolean `account_identity_guard` is reported.
  - `.env.example` states that `LIVECLIP_CLAUDE_MODEL` must be a full
    `claude-` model ID.
  - Round 3 checks:
    - ruff, format, mypy and schema exit 0;
    - `test_claude_cli_provider.py`, `test_codex_rate_limit_message.py` and
      `test_dual_profile_evaluation.py`: 76 passed, exit 0.

    Logs: `/private/tmp/claude-501/-Users-junhuaxu-autoclip-claude/11442fc6-5e35-49d6-afb1-e25ebe8c47b5/scratchpad/stage7-coder/round3/`.
- **Benchmark runbook: freeze the reviewed Claude CLI binary.** The
  interactive Claude Code install can update or re-touch
  `/opt/homebrew/lib/node_modules/@anthropic-ai/claude-code/bin/claude.exe`
  mid-run. The contract identity hashes the executable, so the run would
  abort fail-closed. Before a Claude benchmark, in the worktree that runs
  it:
  1. Confirm `claude --version` is the reviewed version (2.1.308).
  2. Copy it, keeping mode, to the ignored path
     `.cache/claude-cli/2.1.308/claude`. `.cache/` is already in
     `.gitignore`; check with `git check-ignore -v`, and never commit the
     roughly 275 MB file.
  3. Make the copy read-only (`chmod 0555`) and check that its sha256
     equals the installed binary's.
  4. Set `LIVECLIP_CLAUDE_EXECUTABLE=<absolute path of the copy>` and
     `LIVECLIP_STRUCTURED_PROVIDER=claude-cli`.
  5. Run `liveclip doctor` (`claude_cli` must pass with `reviewed_version`
     2.1.308 and `subscription` true) and one `liveclip smoke-claude`.
  6. Run `dual-profile-eval --discovery-concurrency 3`.

  Verified 2026-10-21 in the Stage 7 worktree:
  - The copy's sha256
    `ca923c86ac84b30574a82331a05b6e066c27477a926ceaffe46a845a33e4dd37`
    equals the installed binary's, with the same Anthropic code signature.
  - Doctor `claude_cli` passed: 2.1.308, `claude.ai`, subscription true,
    identity guard active.
  - Real `smoke-claude` succeeded in 4578 ms (7.3 s wall under a 300 s
    guard), with no keychain prompt or hang.
  - The frozen copy's contract differs from the installed path's only
    because the identity includes the executable path. Use one path for
    the whole run.
  - Global Claude settings were not changed. The copy also never
    self-updates, because the child env forces `DISABLE_AUTOUPDATER=1`.

  Frozen-path isolation canary (2026-10-22, main worktree at `996962b`;
  reviewer P2 #3). The round-2 canary ran against the global install,
  before the copy existed; it was re-run with the frozen copy as the
  executable so that the isolation evidence covers the exact binary and
  path the benchmark uses:
  - Pre-checks: `.cache/claude-cli/2.1.308/claude` mode 0555, sha256
    `ca923c86ac84b30574a82331a05b6e066c27477a926ceaffe46a845a33e4dd37`,
    `--version` 2.1.308, ignored by `.gitignore` (`.cache/`).
  - Contract identity of the frozen path:
    `claude-cli-editorial-v1.2.1.308.d65edfc7c242edac24dbf6180a38d31f9df396615005e549f168da7e73e9bbbe`
    (the same identity the integrated doctor reported).
  - Canary directory with a planted `CLAUDE.md` (canary token) and project
    hooks (`SessionStart`, `UserPromptSubmit`) in `.claude/settings.json`.
  - Production argv and env (`claude_cli_argv`, `claude_cli_environment`,
    so the env allowlist plus `DISABLE_AUTOUPDATER=1`), model
    `claude-opus-5-5`: exit 0, 6352 ms, not an error. No canary token, no
    project instructions, no memory, no skills, no MCP tools; the only tool
    was `StructuredOutput`; neither hook fired; no permission denials.
    Residual context as before: an environment block (cwd, platform, OS,
    model, date). This time the run also reported Claude Code's built-in
    note that downloaded files are untrusted data. Round 2 on the same
    version did not report it; the cause is unconfirmed (self-report
    variance or server-side text) and it is not an isolation drift. It is
    harness text, not user or project context, and not a credential.
    (Corrected 2026-10-22 from "it now also contains", reviewer P2.)
  - The account-email reminder residual context was not probed by this
    frozen canary; the in-memory email output guard still applies.
  - Default-flag control (same binary, env and cwd; only
    `--no-session-persistence` added to avoid a session file): saw the
    canary token and project instructions, 48 tools (19 MCP) and 36
    skills, and both hooks fired. This matches round 2.
  - Real `smoke-claude` with `LIVECLIP_STRUCTURED_PROVIDER=claude-cli` and
    `LIVECLIP_CLAUDE_EXECUTABLE` set to the frozen path: succeeded, 4190 ms
    over 1 request (6.2 s wall under a 300 s guard), auth method
    `claude.ai`, the same contract as above.
  - No new `~/.claude/projects` or `~/.claude.json` project entries from
    the production run or the smoke. The control created an empty memory
    directory entry for the canary path (not the repo); it was removed with
    `rmdir`, and the listing then matched the pre-run listing.
  - No drift. Only extracted, email-scrubbed fields were saved (0 email
    matches). Logs: `/private/tmp/claude-501/-Users-junhuaxu-autoclip-claude/11442fc6-5e35-49d6-afb1-e25ebe8c47b5/scratchpad/frozen-canary/logs/`.

## Stage 6 engineering follow-ups (2026-10-21) — ACCEPTED (code cef7d4b..437ebb8 plus fc13163)

- **Status: ACCEPTED** (2026-10-22): code `a22f9d3` rebased to
  `cef7d4b`..`437ebb8`, plus diagnostics commit
  `fc13163ff1d90a93319723f00d723164666a6cad`, verified at the integrated
  tip `996962b`. Tester PASS and reviewer ACCEPT; evidence in the
  integration section above. Not pushed or merged.
- Previous status (kept for history): IN PROGRESS, pending tester and
  reviewer acceptance, on local
  branch `claude/liveclip-stage6-followups`, based on the Stage 4 docs tip
  `ca80fb7d88e7f8620ef9053347f7598604918ad2`. Not pushed or merged. The
  Controller may rebase it onto later Stage 4 docs; this section is
  self-contained.
- Code commit: `a22f9d36e59b6022a6b9c39c8847de428b92ed14`.
- Scope: the consolidated engineering follow-ups from the Stage 1 and
  Stage 3 sections (repeated in the Stage 4 section).
  1. **`LeaseMonitor` suspend recovery** (Stage 3 follow-up; product change in
     `src/liveclip/application/lease_monitor.py`).
     - Root cause: leases expire on the shared wall clock
       (`datetime.now(UTC)` in `SQLiteTaskQueue`), but the monitor scheduled
       heartbeats on `time.monotonic`, which pauses while the host sleeps.
       After a sleep longer than `lease - heartbeat` (about 90 s with the
       120 s / 30 s defaults) the next heartbeat came after expiry, so a
       still-valid holder lost its lease on wake and the stage cost a retry.
     - Fix: on every poll the monitor compares how far wall time and
       monotonic time advanced since the previous poll. If wall time advanced
       more than 1 s further (`_WALL_CLOCK_JUMP_SECONDS`), the host was
       suspended or the clock stepped forward, and the heartbeat is made due
       immediately instead of one monotonic interval later. A false positive
       costs one extra heartbeat. Defaults, settings and the constructor are
       unchanged.
     - Fencing is unchanged: the immediate renewal goes through the same
       `heartbeat`, whose SQL still requires the caller's `lease_token` and
       `lease_expires_at > now`. An expired lease is refused, the monitor
       reports `lost_lease` and stops, and the stored expiry is not touched.
       A recovered task has a new token, so the old holder cannot extend it.
     - Tests: new `tests/integration/test_lease_monitor_suspend.py` uses the
       existing `ShiftedWallClock` and a real SQLite queue with the production
       120 s lease and 30 s heartbeat:
       - (a) a 110 s simulated sleep (longer than `lease - heartbeat`, shorter
         than the lease) is renewed immediately, and the next paced heartbeat
         30 s later still finds the lease;
       - (b) a 121 s sleep (longer than the lease) still loses the lease: the
         heartbeat returns `None`, the stored expiry is unchanged and a later
         heartbeat is still refused;
       - (c) without a jump, and with a 0.5 s sub-threshold step, there is no
         heartbeat, the lease is kept and the expiry is unchanged.
       - Mutation check: with the pre-Stage 6 monitor, (a) fails (no renewal
         after the sleep) and (c) passes. (b) also fails there, but only
         because the old monitor fenced through `observe` instead of an
         immediate heartbeat; it lost the lease too.
     - Existing lease tests' assertions are unchanged. The
       `tests/integration/lease_suspend.py` docstring now describes the
       Stage 6 behavior.
  2. **Stage 1 Reviewer P2-b** (`scripts/evaluate_agent_benchmark.py`):
     - The parent chain is created or proven with
       `ensure_directory_no_follow`, so a symlinked `--output-dir` chain is
       refused before anything is written (previously a staging directory
       was created first, through the symlink).
     - The staging directory is created with
       `create_directory_exclusive_no_follow`, which returns its pinned
       device/inode. Both reports are written through a held
       `O_NOFOLLOW|O_DIRECTORY` descriptor (`openat`-style `dir_fd`), after
       checking that descriptor matches the pinned identity.
     - `publish_directory_no_replace_no_follow` is called with
       `expected_identity`, so a swapped staging directory is refused.
     - Cleanup is `remove_tree_no_follow(..., expected_identity=...)`:
       descriptor-based, no-follow, and it removes only the directory this
       call created. It is best-effort and never masks the original error.
  3. **Stage 1 Reviewer P2-c**: new tests in
     `tests/unit/test_agent_benchmark_evaluator.py` with no mock of the
     publication path:
     - `test_agent_publication_rolls_back_after_a_real_rename`: the native
       no-replace rename really publishes the directory; only the post-rename
       verification is made to fail. The real rollback renames it back and
       the cleanup removes it, leaving the parent empty.
     - `test_agent_publication_real_rename_refused_by_late_destination`: a
       destination that appears after staging makes the native rename itself
       fail; the prior evidence is untouched and the staging directory is
       removed.
     - `test_agent_publication_refuses_a_swapped_staging_directory`
       (P2-b regression; fails on the pre-Stage 6 evaluator, which published
       the impostor) and
       `test_agent_publication_refuses_symlinked_output_chain_before_staging`.
  4. **CLI-help symlink restriction**: `--output-dir` help now says the
     directory must not exist (not even empty), every path component must be
     a real directory (not a symlink), `..` is refused, and on macOS
     `/private/tmp/...` must be used instead of `/tmp/...`.
  5. **Stage 1 Earlier P2-5 (risk discovery counts only final candidates):
     not changed; documented.** MD sections 3.8, 6 and 10 require a risk to
     be discovered and then routed to `manual_review`/`blocked`, and FAIL a
     risk candidate that disappears. Agent v2 has no such routing, so a
     retained final candidate is the only proof that the risk did not
     vanish; a raw candidate that the Global Review dropped is exactly the
     disappearance the MD forbids. The acceptance document does not say
     otherwise. Counting superseded raw candidates would loosen a mechanical
     blocker without a spec or operator decision. A code comment at the risk
     assessment records this. **Operator question:** should a raw
     (superseded) candidate with evidence cues count as Agent v2 risk
     discovery? Until answered, the strict reading stays.
- Not addressed (still open): other `lease_seconds=30` integration tests are
  not suspend-tolerant. With Stage 6 they lose a lease only when a suspend
  exceeds the remaining lease, not `lease - heartbeat`. The Stage 2
  path-based retained-read limit and the product cold-18 FAIL are unchanged.
- Coder checks in the isolated worktree (main `.venv`,
  `PYTHONPATH=<worktree>:<worktree>/src`, imports verified to resolve to the
  worktree), under `caffeinate -dims` with `PYTHONDONTWRITEBYTECODE=1`:
  - At `a22f9d3`: ruff check "All checks passed!" (exit 0), ruff format
    "448 files already formatted" (exit 0), mypy "no issues found in 230
    source files" (exit 0), schema check match (exit 0). `tsc` not run: no
    web files touched.
  - Targeted pytest, exit 0: 316 passed in 515.65 s (one Starlette
    deprecation warning). Files: the new suspend tests, every test that
    imports `LeaseMonitor` (`test_lease_monitor.py`,
    `test_delivery_runner.py`, `test_delivery_progress.py`,
    `test_completion_delivery.py`, `test_completion_worker.py`,
    `test_transport_budget_pipeline.py`), `test_worker_foreground_race.py`,
    `test_stage_runner.py`, `test_task_queue.py`, both evaluator test files,
    `test_secure_files.py` and `test_dual_profile_evaluation.py`.
  - The lease monitor unit and suspend tests 10 times in a loop: 6 passed
    each time, all exit 0.
  - Logs:
    `/private/tmp/claude-501/-Users-junhuaxu-autoclip-claude/11442fc6-5e35-49d6-afb1-e25ebe8c47b5/scratchpad/stage6-coder/`.
  - The coder did not run the full backend suite or `make e2e`; the tester
    owns them.
- **Operator note: `scripts/evaluate_agent_benchmark.py --output-dir`
  restrictions (new since Stage 6).**
  - Missing parent directories are created no-follow with mode `0700`, not
    the umask default that `mkdir -p` used before.
  - A path containing `..` is refused, including a relative one.
  - Every path component must be a real directory. On macOS `/tmp/...` is
    refused because `/tmp` is a symlink to `/private/tmp`; use
    `/private/tmp/...`. A symlinked chain is refused before anything is
    written, so no staging directory is left behind.
  - The output directory itself must not exist, not even empty (unchanged).
- Review round 1: reviewer **ACCEPT at `670478e`**, 0 P0/P1, 3 P2. Fix round
  2 (code commit `039c998978ac197b12aef18c9f04ca1e6ad16247`), pending acceptance:
  - P2-1 (flaky test): in `test_suspend_longer_than_lease_still_loses_the_lease`
    the main thread could shift the clock between a poll's wall read and
    `observe`, so the lease was lost through `observe` with no heartbeat.
    Every suspend during monitoring is now applied from inside the monitor
    thread, right after the N-th `observe` returns, so it always lands
    between two polls. The assertions are kept (`heartbeats == [None]`,
    expiry unchanged, a later heartbeat refused).
  - P2-2 (robustness): the jump rule had two false negatives: a renewal
    after a jump that failed transiently (for example SQLite locked when many
    processes wake) was retried only one monotonic interval (30 s) later,
    and a suspend before the monitor's first poll was not seen. The monitor
    now also makes the heartbeat due on every poll while less than half a
    heartbeat interval of wall-clock lease remains
    (`_RENEW_WITHIN_HEARTBEAT_FRACTION = 0.5`, 15 s with the defaults).
    - The remaining lease is measured on the monitor's own wall clock: the
      lease length is `lease_expires_at - heartbeat_at` of the claimed lease,
      and the renewal start is read just before each successful heartbeat.
      An injected queue `now` (as in the completion inspection tests) can
      therefore cause at most one or two early heartbeats at start:
      `reconcile_completion` calls `monitor.refresh()` right after `start()`,
      so the first poll may race it. Both heartbeats are fenced and harmless.
    - Settings require `lease > 2 * heartbeat`, so a paced heartbeat always
      finds more than one interval (90 s with the defaults) remaining, and
      the rule never fires in normal operation.
    - Fencing is unchanged: renewal still goes only through the fenced
      heartbeat SQL; an expired lease is refused and lost.
    - Known limit: after a sleep that leaves more than 15 s, a failed
      renewal is retried once less than 15 s remain (still before expiry),
      not on the very next poll.
    - New deterministic tests: a failed first renewal after a 110 s sleep is
      retried on the next poll; a 110 s suspend before the first poll is
      renewed; a 121 s suspend before the first poll is still lost; 20 s
      remaining with no jump does not renew early; the jump test now covers
      95 s (jump rule only) and 110 s.
    - Mutation checks: with the round-1 monitor (`670478e`) the three new
      rule tests fail and the other five pass; with the pre-Stage 6 monitor
      (`ca80fb7`) six fail and two pass.
  - P2-3 (docs): the operator note above.
  - Coder checks for round 2: at `039c998`, under `caffeinate -dims`:
    ruff check, ruff format ("448 files already formatted"), mypy (230
    source files) and the schema check all exit 0; targeted pytest exit 0,
    333 passed in 562.00 s (the round-1 files plus
    `test_completion_selection.py`, `test_completion_identity.py`,
    `test_import_only_pipeline.py` and `test_stage_asset_integrity.py`,
    without the evaluator and `secure_files` files, which round 2 did not
    touch); the suspend and lease monitor unit tests 20 times in a loop, 11
    passed each time, all exit 0.
  - Round 2 logs:
    `/private/tmp/claude-501/-Users-junhuaxu-autoclip-claude/11442fc6-5e35-49d6-afb1-e25ebe8c47b5/scratchpad/stage6-coder/round2/`.
- Review round 2: reviewer **ACCEPT at `fc06b3e`**, one P2 and one nit. Fix
  round 3 (code commit `7de47601a39852aafd2ed93061c11e53a16a7ebc`), pending acceptance:
  - P2 (flaky assert): `assert len(held.observes) == 1` depended on how fast
    the main thread stopped the monitor. The test helper now records
    `(observe calls, heartbeat calls)` inside the monitor thread when the
    first renewal succeeds (`first_renewal`), and the renewal tests assert
    that value: `(1, 1)` after a suspend, `(1, 2)` for a failed renewal and
    its retry, `(0, 1)` for a suspend before the first poll. The other count
    assertions were checked; they are read after the monitor thread exits or
    cover a window with no possible further heartbeat. Test wait bounds were
    raised from 5 s to 30 s (`WAIT_SECONDS`); they are only upper bounds.
  - Found while looping under load (load average 70--110): a monitor thread
    descheduled between its wall and monotonic reads made both clocks
    advance together but looked like a jump, causing one unneeded heartbeat
    (reproduced: a 2.57 s apparent jump at the first poll in
    `test_more_than_half_an_interval_remaining_does_not_renew_early`). In
    production this costs one fenced heartbeat; in the tests it was a flake.
    Fix in `lease_monitor.py`: each wall read is bracketed by monotonic reads
    and the jump is the lower bound
    `(wall - last_wall) - (monotonic_after - last_monotonic_before)`, so a
    stall never inflates it, while a real suspend still shows almost in full.
    New deterministic regression
    `test_a_stall_between_clock_reads_is_not_a_jump` injects a 3 s stall
    right after the first wall read; it fails with the round-2 monitor
    (`fc06b3e`) and passes now. The threshold test's slack was also raised
    from 5 s to 10 s.
  - Nit: the injected-`now` note now says "at most one or two early
    heartbeats at start" (`reconcile_completion` calls `monitor.refresh()`
    right after `start()`, so the first poll may race it).
  - Coder checks for round 3, at `7de4760`, under `caffeinate -dims`:
    - ruff check, ruff format ("448 files already formatted"), mypy (230
      source files) and the schema check: all exit 0.
    - Under heavy host load (load average 57--111 on 10 cores, from other
      concurrent runs): the suspend and lease monitor unit tests 20 times,
      19 exit 0 and 1 exit 1. The failure was a 30 s
      `monitor did not poll` timeout in the stall test (the whole run took
      31.85 s), i.e. the test process was starved, not a wrong heartbeat.
      The targeted suites in the same window: exit 1, 327 passed, 7 failed,
      all in `test_delivery_progress.py` with `lost_lease` from a render
      lease of 30 s (heartbeat 5 s), which is consistent with the same
      starvation expiring the lease. Re-run alone during that window,
      `test_delivery_progress.py` passed 22/22 (exit 0).
    - Re-run at load average 21--27: the 20x loop, 12 passed each time, all
      exit 0; targeted suites exit 0, 334 passed in 583.58 s (the round-2
      file set).
    - Round 2's first under-load loop also had one failure (1 failed, 10
      passed, 6.29 s). Its log was deleted by the coder's cleanup before it
      was read, so its cause is unknown; the 40-run reproduction found the
      false-jump flake fixed above.
  - Round 3 logs:
    `/private/tmp/claude-501/-Users-junhuaxu-autoclip-claude/11442fc6-5e35-49d6-afb1-e25ebe8c47b5/scratchpad/stage6-coder/round3/`.
- Caveats: deterministic validation only; mock/fixture tests. No rendering
  acceptance, human editorial/audio review or model inference.

## Stage 4 benchmark evaluator rules (2026-10-21) — ACCEPTED at 8b14aa3

- **Status: ACCEPTED** at code commit
  `8b14aa39420ecfffc4ad54c6d76d8433affd15b6`, verified at tip
  `ca80fb7d88e7f8620ef9053347f7598604918ad2` (2026-10-22). Local branch
  `claude/liveclip-stage4-evaluator-rules`; not pushed or merged.
  - Tester r1: `make lint` 0; 126 benchmark tests passed; the cold-18
    re-score reproduced FAIL 90.0 exactly with hash-identical inputs.
    `make test` run #1 passed (2668 backend). Run #2 was invalidated by a
    clamshell sleep on battery, not by a code failure.
  - Tester r2, on AC power: two `make test` runs, both exit 0, each with
    2668 backend passed, vitest 80/80 and e2e 4/4. The lease set passed 39
    x 3. 0 sleep events. 1143 report files hashed identically.
  - Reviewer: ACCEPT at `ca80fb7`, no findings. The rebase is
    byte-identical to the reviewed code.
  - The Stage 3 P2 commit `f51f696` was verified in this round.
- Previous status (kept for history): IN PROGRESS, pending tester and
  reviewer acceptance on local branch `claude/liveclip-stage4-evaluator-rules`,
  rebased onto the Stage 3 tip `427e80cd3e65bfe9e25a7c9044e960f09c5a0c21`.
- Code commits, after rebase (identical code diffs to the reviewed commits):
  - `2c4de9afb8c05e6ef30d3fb3e46bea0a181e07f0` (was `30dc26b`): decisions A
    and B;
  - `0440c179cf919d408abd474d6d4188dc55ffb449` (was `2abec1b`): review round
    2;
  - `8b14aa39420ecfffc4ad54c6d76d8433affd15b6` (was `052cd46`): comment-only
    confirmation.
- The Stage 3 P2 test-only commit `f51f696` is verified as part of this
  round.
- Operator decisions, both confirmed by the operator on 2026-10-21. They are
  recorded in the Decision Log of
  `docs/exec-plans/liveclip-dual-profile-benchmark-v1.md`.
  - **A:** an exact boundary hit is tolerance-only: both edges within 3000 ms
    (short) or 5000 ms (long), inward or outward. This supersedes the earlier
    Controller full-cue-coverage interpretation.
  - **B:** negative-only outputs are classified as `negative_anchor_output`, a
    direct FAIL in both evaluators, with a per-anchor MD section 7 policy:
    - N01--N07, N10 and N11 hard-fail for `selected` and `manual_review`
      (the operator confirmed this default);
    - N08 hard-fails only automatic outputs; a `manual_review` output goes to
      `human_required`;
    - N09 allows only the S08 clean sub-interval.

    Mixed candidates stay `irrelevant_padding`. The policy table fails closed
    on any `benchmark_id`, `reason` or interval mismatch.
- Reviews:
  - `30dc26b`: CHANGES_REQUIRED (P1: the "entirely negative" loophole);
  - `2abec1b`: ACCEPT;
  - `052cd46`: comment-only.
- Cold-18 history (`data/evaluations/dual-profile-benchmark-20260924-final-cold-18`,
  ignored local evidence, read-only):
  - Baseline evaluator at `7d2689c`: PASS 90.36, reproduced byte-identical.
  - Strict Stage 1 evaluator at `e51e353`: FAIL 80.0. The reviewer showed that
    80.0 depended on the then-unconfirmed full-cue-coverage rule.
  - Stage 4 evaluator: **FAIL 90.0**.
    - Short 6/8: S01 at +3420 ms exceeds the 3000 ms tolerance and goes to
      manual adjudication; S03 is missed.
    - Mini 5/6: L07 is missed because its only exact candidate was blocked.
      The missed required mini-lesson is L07, not L06 (L06 is supplemental).
    - Hard failures:
      - `irrelevant_padding`: `ml_0005_mixed_voice_types_637_746`, with
        13,340 ms of N05;
      - `negative_anchor_output`: the two N09 candidates
        `precision_mini_lesson_0017_c03` and
        `sh_0022_high_note_channel_01`.
    - Eight N08 `manual_review` negative-only candidates are informational
      findings listed in `human_required`.
    - PASS blocker: `short_recall_below_threshold`.
- Coder checks in the isolated worktree: ruff, format, mypy and schema
  exit 0; benchmark tests 126 passed (round 2 and the comment-only commit).
  Logs:
  `/private/tmp/claude-501/-Users-junhuaxu-autoclip-claude/11442fc6-5e35-49d6-afb1-e25ebe8c47b5/scratchpad/stage4-coder/`.
- Open follow-ups (not done):
  - Stage 1: Reviewer P2-b (pin the Agent report staging directory identity;
    fd-based cleanup), Reviewer P2-c (end-to-end rollback test after a real
    rename), and Earlier P2-5 (Agent risk discovery counts only final
    candidates). (2026-10-21: P2-b and P2-c addressed by Stage 6, pending
    acceptance; P2-5 examined by Stage 6 and deliberately kept strict,
    pending an operator answer. See the Stage 6 section.)
  - Stage 2: path-based retained reads cannot detect a swap away and back;
    the per-file manifest hashes still bind the content.
  - Stage 3: `LeaseMonitor` should detect a wall-clock versus monotonic jump
    and refresh immediately while the lease is unexpired. Other
    `lease_seconds=30` integration tests are not yet suspend-tolerant.
    (2026-10-21: the `LeaseMonitor` item is addressed by Stage 6, pending
    acceptance; the `lease_seconds=30` item is still open. 2026-10-22:
    Stage 6 is ACCEPTED at `996962b`.)
  - Product: cold-18 still FAILs at 90.0, because of short recall 6/8
    (S01, S03), L07 being blocked, the `ml_0005` padding and the N09 outputs.
    Improving it needs product work and a fresh real run, which is allowed
    without per-run consent since 2026-10-21.
- Branch-tip rule: `claude/liveclip-stage4-evaluator-rules` is the accepted
  code `8b14aa3` plus docs-only commits up to its tip `0bb4af4`. To verify,
  run `git diff --name-only 8b14aa3..0bb4af4`; it must list only
  `STATUS.md`, `docs/**` and `tasks/**`. (Corrected 2026-10-22: the earlier
  wording `8b14aa3..HEAD` holds only on the Stage 4 branch; on a branch that
  carries later stages, `HEAD` includes their code.)
- Caveats: deterministic validation plus a read-only re-score of existing
  evidence. No new model inference, rendering or human review.

## Stage 3 cleanup (2026-10-21) — ACCEPTED at ce43f5e

- **Status: ACCEPTED** at code commit
  `ce43f5ed23819201a750d4cef0a8a8cbfbed644b`.
  - Tester, at tip `2421df3`: `make lint` 0; `make test` twice under
    `caffeinate`, both exit 0, each with 2627 backend passed, vitest 80/80,
    and e2e mock, legacy, completion and B2 PASS; 0 sleep events; the lease
    and suspend set passed 39 x 3; the new verifier `lstat` test passed;
    846 report files hashed identically.
  - Reviewer: ACCEPT, 0 P0/P1, 3 P2.
  - The 3 P2s are fixed in test-only commit
    `f51f6960f27d298424e968a5a7e329f857c6f201` (details below). That commit
    is verified as part of the Stage 4 round, not this acceptance.
- (History: this section was opened as "IN PROGRESS, pending tester and
  reviewer acceptance".) Opened on local branch `claude/liveclip-stage3-cleanup`, created from
  `e51e353dadbcb1a0315f7c31f3f68a8e0da09ac0` (the Stage 2 docs tip). The
  operator approved Stage 3 on 2026-10-21. Not pushed or merged.
- Operator decision 2026-10-21: the semantic-only no-padding-allowance
  reading is **confirmed**. It is recorded in the Decision Log of
  `docs/exec-plans/liveclip-dual-profile-benchmark-v1.md`. No evaluator code,
  threshold or benchmark JSON/MD changed.
- Scope: the three Stage 2 cleanup follow-ups, all in code commit `ce43f5ed23819201a750d4cef0a8a8cbfbed644b`.
  1. **Single run-directory lstat** (`scripts/verify_completion_retained.py`).
     - One `lstat` of the selected run directory now provides both the
       `S_ISDIR` (not-a-symlink) check and the identity baseline that is
       re-checked after all reads.
     - New test
       `test_retained_verifier_baseline_is_the_same_lstat_as_its_directory_check`
       swaps the run directory right after its first `lstat`. It passes on
       the new code and fails ("DID NOT RAISE") on the old two-`lstat` code.
  2. **Allocation swap test renamed** to
     `test_report_scope_identity_is_read_from_held_handle_not_trusted_by_name`,
     with a comment saying what it proves and what it does not. It proves the
     identity comes from `fstat` on the held `O_NOFOLLOW` handle, so a
     by-name swap after `open` is not trusted. It does not close the
     `mkdir`-to-`open` window, which is an accepted risk. Assertions are
     unchanged.
  3. **Lease tests robust to host suspend.**
     - Root cause:
       - Task leases expire on the shared wall clock: `SQLiteTaskQueue` stores
         `datetime.now(UTC) + lease_seconds`, and `_recover_expired` compares
         it against wall-clock now.
       - `LeaseMonitor` paces heartbeats with `time.monotonic`, which pauses
         while macOS sleeps.
       - After a suspend longer than the lease, the next heartbeat finds the
         lease expired, so the stage ends `LOST_LEASE`. The runner's next
         `claim` then recovers the task: it requeues with `retry_count + 1`
         and executes it again. That explains the r1 failures (retry_count 1;
         PROXY_RENDER 2).
       - Correction (reviewer P2-2, 2026-10-21): the worst case is a suspend
         longer than `lease - heartbeat interval`, not only `lease`. The last
         renewal sets `expiry = renewal + lease`, and the next renewal is due
         one heartbeat of monotonic time later. If the host sleeps just
         before a due heartbeat, the lease expires before it can be renewed.
         With the production defaults (120 s lease, 30 s heartbeat), a sleep
         of about 90 s or more can cost a retry. With `max_stage_retries=3`,
         repeated sleeps can FAIL a stage.
     - Conclusion: this is **correct production behavior**. Wall time is the
       only clock all worker processes share, and a suspended holder cannot be
       told apart from a dead one. No `src/` code changed, and no production
       lease semantics or durations changed. There is no injected-clock seam,
       and adding one across the repository modules would be a broad
       production change.
     - Fix (tests only): the two tests use the existing
       `SQLiteTaskQueue(lease_seconds=...)` parameter with a 24 h
       `SUSPEND_TOLERANT_LEASE_SECONDS`, defined in the new helper
       `tests/integration/lease_suspend.py`. All existing assertions are
       unchanged: `retry_count == 0` and every stage executed exactly once.
       Nothing is marked skip, xfail or retry.
     - Regression tests:
       - `ShiftedWallClock` advances `datetime.now` in every already-imported
         LiveClip module that binds `datetime`, and leaves monotonic time
         alone, as a real suspend does.
       - `test_simulated_suspend_keeps_exactly_once_only_within_the_test_lease`
         jumps wall time 12 h while ingest holds its lease. With the test
         lease, every stage runs exactly once. With the 30 s lease these tests
         previously used, ingest correctly runs twice (production semantics).
       - `test_initial_budget_never_retries_across_a_simulated_host_suspend`
         re-runs the r1 failing parametrization
         (`short_highlight-None-existing-False`) with a 12 h jump after every
         stage claim, and keeps `retry_count == 0`. As a mutation check, with
         the 30 s lease it fails.
         - Reviewer P2-1 fix (`f51f696`): this test now also asserts that
           every claimed lease expires at the shifted "now" plus the test
           lease, which proves the shift reached the queue. Mutation check
           with no module shifted: the old test passed vacuously (exit 0) and
           the new test fails (exit 1). With only the queue unshifted, the
           shifted repository's `not_before` keeps the queue idle, so the run
           never completes; it does not pass.
     - Limits: a suspend longer than 24 h would still, correctly, let a
       holder's lease expire. The other `lease_seconds=30` tests (for example
       `test_actual_planning_and_serial_domain_repair_keep_attempt_audit`) are
       out of this stage's scope and keep 30 s.
- Coder self-checks at `ce43f5ed23819201a750d4cef0a8a8cbfbed644b`, run under `caffeinate -dims` with
  `NODE_LTS_BIN=/opt/homebrew/opt/node@22/bin PYTHONDONTWRITEBYTECODE=1`.
  Mock/fixture only.
  - `make lint` exit 0: ruff "All checks passed!", "447 files already
    formatted", mypy "no issues found in 230 source files", schema match,
    `tsc` clean.
  - `pytest --collect-only tests` exit 0: 2627 tests collected, which
    confirms the `lease_suspend` helper import works under full collection.
  - Touched files (`test_e2e_fixture.py`,
    `test_completion_fixture_verifiers.py`,
    `test_transport_budget_pipeline.py`, `test_worker_foreground_race.py`):
    87 passed.
  - The two lease tests (every parametrization) plus both suspend
    regressions, 5 times in a loop: 39 passed each time, all exit 0.
  - `make e2e` once, exit 0, with 4 x "1 passed":
    - legacy run `eb3031cfa50e4c9194a40d54aef6107a`;
    - completion run `249daf6b7d8345cfac605627cefd099b` (scope
      `2277fd1e...`), retained PASS;
    - B2 run `62079126b46b4e01a15eb6df9a57d7f3` (scope `e530017a...`),
      retained PASS.
  - All 792 pre-existing report files hashed identically afterwards.
  - Logs (session scratchpad, may not persist):
    `/private/tmp/claude-501/-Users-junhuaxu-autoclip-claude/11442fc6-5e35-49d6-afb1-e25ebe8c47b5/scratchpad/stage3-coder/`.
  - The coder did not run the full backend suite; the tester owns it.
- Open follow-up (not done): `LeaseMonitor` should detect a wall-clock
  versus monotonic jump and refresh immediately while the lease is still
  unexpired, so a production sleep shorter than the lease costs no retry.
  (2026-10-21: addressed by Stage 6, pending acceptance.)
- Caveats: deterministic validation only; mock/fixture providers; no
  rendering acceptance, human editorial/audio review or model inference.

## Stage 2 real-browser e2e harness idempotency (2026-10-21) — ACCEPTED at cfcff0d

- **Status: ACCEPTED** at code commit
  `cfcff0dbea66cc291456fcecca800ee9c6313dfe`. It was verified at branch tip
  `58cb055f59d7011ac83c9d798da472ae919f31c9` (tester round r2 PASS; reviewer
  ACCEPT, 0 P0/P1). Branch `claude/liveclip-stage2-e2e-harness`, created
  from `8b4e66c2a339934ff782a8edfc0d8884f9c3ae29`. Local only: not pushed or
  merged.
- Branch tip rule: the branch is `cfcff0d` (the accepted code) plus
  docs-only commits, the first being `58cb055`. To verify, run
  `git diff --name-only cfcff0d..HEAD`; it must list only `STATUS.md`,
  `docs/**` and `tasks/**`.
- (History: this section was opened as "IN PROGRESS, pending tester and
  reviewer acceptance"; the entries below are kept as written, except the
  fix-1 wording corrected in the P2 fix round.)
- Goal: `make test` (and `make e2e`) can run repeatedly in the same worktree
  without moving `apps/web/playwright-report/` aside, while every retained
  package check stays at least as strict.
- Root cause: `scripts/e2e_fixture.py` retained each real-browser package at
  `apps/web/playwright-report/{browser,completion,b2}-packages/<run id>/`,
  and `scripts/verify_completion_retained.py` globbed the whole scenario
  folder and required exactly one manifest. Any package left by an earlier
  invocation therefore failed the next run with `ValueError: exactly one
  retained completion package required`.
- Fix (per-invocation, identity-bound report scope):
  - New `e2e_fixture.py allocate-report-scope --scenario S` creates a fresh
    random hex32 directory below the scenario folder with an exclusive,
    no-follow `mkdir` and prints its path, device and inode. The harness
    calls it once per invocation (legacy, completion, and the chained B2
    each get their own scope), just before package retention.
  - `e2e_fixture.py verify --retain-packages` now requires `--report-scope`,
    `--report-scope-device` and `--report-scope-inode`. Retention opens the
    scope by walking from the repository root with `O_NOFOLLOW`, checks the
    path is a generated hex32 child of this scenario's folder, checks the
    device/inode against the allocation, requires the scope to be empty, and
    creates the single `<run id>/` directory inside it exclusively. A legacy
    scope cannot receive completion/B2 evidence and vice versa.
  - `verify_completion_retained.py` bundle verification now requires
    `--report-scope`, `--expected-scope-device` and `--expected-scope-inode`.
    It rejects a relative, traversing, foreign-folder or non-hex32 scope, any
    symlink along `apps/web/playwright-report/<folder>/<scope>`, and a
    replaced scope (identity mismatch). Inside the scope it still requires
    exactly one `*/manifest.json`, and now also requires that the scope holds
    nothing but that one run directory. All lineage, `--prove-rejection`,
    byte-bound, credential/signed-URL, ZIP and MP4-decode checks are
    unchanged. The PASS JSON adds `report_scope`.
  - Earlier packages (the pre-Stage-2 flat `<folder>/<run id>/` layout and
    earlier scopes) are never read, moved, overwritten or deleted.
- New retained layout: `apps/web/playwright-report/<folder>/<scope
  hex32>/<run id>/manifest.json`.
- Regression tests (fixture-level, no browser):
  - `tests/unit/test_e2e_fixture.py`: fresh scopes preserve prior flat and
    scoped packages; scope rejection of relative, traversing, non-hex32,
    foreign-folder, cross-scenario, symlinked-scope, symlinked-folder and
    replaced scopes; second retention into one scope refused; retention
    without a scope refused for all three scenarios; static check that the
    harness allocates one scope before retention and passes the same triple
    to retention and to the retained verifier.
  - `tests/integration/test_completion_fixture_verifiers.py`: (a) stale
    flat, earlier-scope and B2-folder packages are neither selected nor
    changed; (b) two packages, an extra manifest-less run directory or a
    stray file in this scope fail; (c) an empty scope fails with the
    exactly-one error and a missing scope fails; (d) relative, traversing,
    non-hex32, foreign-folder, run-directory, symlinked, replaced and
    symlinked-folder scopes are rejected.
- The Stage 1 follow-up "harness non-idempotency" is being addressed here,
  pending acceptance.
- Coder self-checks at code commit
  `bae901c22260af49a79c1d15a7ac11ced4856f18`, run in the main worktree with
  `NODE_LTS_BIN=/opt/homebrew/opt/node@22/bin PYTHONDONTWRITEBYTECODE=1`.
  Mock/fixture only.
  - `make lint` exit 0: ruff "All checks passed!", "446 files already
    formatted", mypy "no issues found in 230 source files", schema match,
    `tsc` clean.
  - Targeted pytest (`test_completion_fixture_verifiers.py`,
    `test_e2e_fixture.py`, `test_b2_synthetic_worker.py`): 54 passed.
  - `make e2e` twice back to back, with the Stage 1 packages
    (`completion-packages/9f8bdc31...`, `b2-packages/e9085d40...`,
    `browser-packages/59b12aa9...`) left in place. Both exited 0, each with
    e2e:mock, legacy, completion and B2 passing (4 × "1 passed").
    - Run 1: legacy run `05ad28ab7b5b4c68a919895d2ec94553` (scope
      `7c80c8cc...`); completion run `5f42298e1de54a33aeda7cadcdf604e1`
      (scope `222576bf...`), retained PASS; B2 run
      `dbdff27bfc9c4ad2a14e4a51b146e1af` (scope `f4098b5a...`), retained
      PASS.
    - Run 2: legacy run `dd64a552b0074bc89f813ccffef4a37b` (scope
      `42d20550...`); completion run `0f30ffa50f1f457482c9951c98bfe5c7`
      (scope `0db74c68...`), retained PASS; B2 run
      `cd0955e2b5f3492f954e73b197a89b76` (scope `081aa76c...`), retained
      PASS.
    - Each retained PASS reported `full_mp4_decode` PASS, `fixture_removed`
      true and `wrong_existing_producer_rejected` true.
    - All 54 pre-existing retained package files hashed identically before
      and after both runs.
  - Logs (session scratchpad, may not persist):
    `/private/tmp/claude-501/-Users-junhuaxu-autoclip-claude/11442fc6-5e35-49d6-afb1-e25ebe8c47b5/scratchpad/stage2-coder/`.
  - The full backend suite was not run by the coder; the independent tester
    owns it.
- P2 fix round (2026-10-21), still **pending acceptance** until the new SHA
  is verified (historical; accepted at cfcff0d):
  - Independent evidence at `c391ced5f3983f4b10654074742b7aaf10197f1c`:
    - Tester: `make lint` exit 0; `make test` twice, both exit 0, each with
      2619 backend passed, Web vitest 80/80, and e2e:mock, legacy,
      completion and B2 all PASS in both runs; 198 pre-existing report files
      hashed identically.
    - Reviewer: ACCEPT, 0 P0/P1, 3 P2.
  - Fixes for the 3 P2s, in code commit `cfcff0dbea66cc291456fcecca800ee9c6313dfe`:
    - `allocate_report_scope` now reads the new scope's device/inode with
      `fstat` on a held handle opened `O_NOFOLLOW` after the exclusive
      `mkdir`, rather than with a by-name `stat`. Every descriptor is
      closed on all paths.
      - Correction (2026-10-21): this does **not** close the allocation
        race. A residual window remains between `mkdir` and `open`.
        POSIX cannot close it, because no `mkdirat` returns a handle.
        It is an accepted risk: an attacker able to exploit it could also
        edit the scripts.
    - `verify_bundle` re-validates the report scope (no-symlink chain and
      device/inode) after all inventory, ZIP, decode and rejection-proof work.
      It also checks that the run directory keeps the same identity and is
      still the only entry. A swap between the first check and the reads now
      fails closed (`retained report scope identity` or `retained run
      directory changed during verification`).
    - Tests: retention (legacy and completion) refuses a `playwright-report`
      parent replaced by a symlink after allocation; the allocate-time
      symlink test is kept. A scope or run directory swapped after the
      initial check is rejected. The swap tests fail against the
      `c391ced` scripts.
      - The allocation swap unit test swaps the scope **after** the `open`.
        It therefore proves that the identity comes from the held handle,
        not that the `mkdir`-to-`open` race is closed. (Corrected
        2026-10-21: an earlier wording said a swap "right after
        `mkdir`/open" keeps the original identity.)
    - Coder self-checks at `cfcff0dbea66cc291456fcecca800ee9c6313dfe`
      (`NODE_LTS_BIN=/opt/homebrew/opt/node@22/bin
      PYTHONDONTWRITEBYTECODE=1`, mock/fixture only):
      - `make lint` exit 0.
      - Targeted pytest (`test_e2e_fixture.py`,
        `test_completion_fixture_verifiers.py`,
        `test_b2_synthetic_worker.py`): 59 passed.
      - `make e2e` twice back to back, without moving
        `apps/web/playwright-report/`; both exit 0, with 4 x "1 passed" each.
        - Run 1: completion run `0a4a6d5efcba4243a11d626981959eeb` and B2 run
          `3d817802fa11481c9b40b3fbf56faa12`, both retained PASS.
        - Run 2: completion run `5581e519d57c470ca26714c506e2a9a4` and B2 run
          `792dbd8886be442fa6aa082860633851`, both retained PASS.
      - All 270 pre-existing retained package files hashed identically
        before and after both runs.
      - Logs (session scratchpad, may not persist):
        `/private/tmp/claude-501/-Users-junhuaxu-autoclip-claude/11442fc6-5e35-49d6-afb1-e25ebe8c47b5/scratchpad/stage2-p2-coder/`.
- Acceptance evidence for `cfcff0d` (2026-10-21):
  - Tester round 58cb055 r1: **environment-invalid, not accepted.**
    - `make test` run 1 exited 2 with two failures:
      - `test_transport_budget_pipeline::test_initial_budget_is_durable_deterministic_and_never_retried[short_highlight-None-existing-False]`
        (retry_count 1 != 0);
      - `test_worker_foreground_race::test_foreground_and_worker_share_one_lease_and_execute_each_stage_once`
        (PROXY_RENDER 2 != 1).
    - Both tests ran during a macOS "Clamshell Sleep" on battery
      (09:54:05--10:49:36 per `pmset`). Both use 30 s leases.
    - Run 2 passed. An isolated rerun of those tests under `caffeinate`
      passed 37/37.
  - Tester round 58cb055 r2: **PASS.**
    - `make lint` exit 0.
    - `make test` twice under `caffeinate -dims`, both exit 0. Each run had
      2624 backend passed, Web vitest 80/80, and e2e:mock, legacy,
      completion and B2 all PASS.
    - `pmset` shows 0 sleep/wake events in either run window.
    - 612 pre-existing report files hashed identically, and none were
      removed.
  - Reviewer: ACCEPT at `58cb055`, 0 P0/P1.
- Open follow-ups (not done):
  - `scripts/verify_completion_retained.py` around lines 604--610: use a
    single `lstat` for both the run directory's `S_ISDIR` check and its
    identity baseline. (2026-10-21: addressed by Stage 3, pending
    acceptance.)
  - Rename or comment the allocation swap unit test
    (`tests/unit/test_e2e_fixture.py`, around lines 460--499) to match what
    it actually proves: identity from the held handle, not a closed race.
    (2026-10-21: addressed by Stage 3, pending acceptance.)
  - Inherent limit: path-based reads cannot detect a scope swapped away and
    back between checks. The per-file manifest hashes still bind the
    content.
  - Lease-based integration tests (the two above) fail if the host sleeps
    mid-test. Run the full `make test` under `caffeinate -dims` on AC power,
    and consider making these tests robust to suspend. (2026-10-21:
    addressed by Stage 3, pending acceptance.)
  - Still-open Stage 1 follow-ups carry over (see the Stage 1 section):
    Reviewer P2-b, Reviewer P2-c and Earlier P2-5. (2026-10-21: P2-b and
    P2-c addressed by Stage 6, pending acceptance; P2-5 kept strict pending
    an operator answer.)
  - The semantic-only "no padding allowance" reading is still pending
    operator confirmation. (Resolved 2026-10-21: confirmed by the
    operator.)
- Caveats: deterministic validation only; mock/fixture providers; no
  rendering acceptance, human editorial/audio review or model inference.

## Stage 1 benchmark evaluator strictness (2026-10-20) — ACCEPTED at 6c465b7

- **Status: ACCEPTED** at `6c465b767e3829152d0b07451edbe274980321b1` on
  `claude/liveclip-stage1-evaluator`. The independent tester's full run is
  green and the reviewer verdict is ACCEPT, with no P0/P1 open. The branch is
  local only: not pushed or merged.
- Branch tip: `claude/liveclip-stage1-evaluator` is `6c465b7` (the accepted
  code) plus docs-only commits that record the acceptance, the first being
  `87bd6b2`. To verify, run `git diff --name-only 6c465b7..HEAD`; it must
  list only `STATUS.md`, `docs/**` and `tasks/**`. The branch is local only
  and has no upstream.
- History (base `a449f02b9c5694c258d5b5f47c91b9042073c5a9`):
  - Round 0 `bf83c80a81d1b47fa834a8a149f9866f3b3d89db`: reviewer
    CHANGES_REQUIRED (2 P1).
  - Fix round 1 `d9e9ddec11115195264485bb2005be64790c05c9`: reviewer ACCEPT,
    with Controller follow-ups.
  - Fix round 2 `6c465b767e3829152d0b07451edbe274980321b1`: reviewer ACCEPT.
  - The fix rounds were made on `claude/liveclip-stage1-fix` and integrated
    by the Controller.
- Scope: `scripts/evaluate_benchmark.py` and
  `scripts/evaluate_agent_benchmark.py` share the evaluation-only module
  `scripts/benchmark_gates.py`. Every rule comes from
  `liveclip_dual_profile_benchmark_v1.json`; the JSON and `.md` are unchanged.
  `scripts/__init__.py` makes `scripts` a package, so both evaluators import
  `scripts.benchmark_gates`. They append the repository root to `sys.path`
  only when run directly.
- v1 evaluator:
  - The status is `PASS`, `CONDITIONAL` or `FAIL`.
  - A source-hash mismatch is a hard failure.
  - Semantic equivalence is manual-only and never counts as a hit.
  - Matching is one-to-one exact-boundary, using augmenting paths and
    preferring qualified duplicates.
  - Padding and forbidden composites FAIL for both `selected` and
    `manual_review` (D2). Only exact-boundary matches earn a padding
    allowance: the union of every exact-matched gold or supplemental anchor,
    widened by the tolerance. S08 inside N09 therefore passes, and a
    semantic-only candidate gets no allowance. Findings add
    `outside_nearest_anchor_ms`.
  - RGR-02 fails on any `selected` candidate opening at its start, and on
    any candidate on its interval missing a required flag.
  - CONDITIONAL is applied literally (D3).
  - The boundary score is the qualified fraction of hits; the audit score is
    computed from five items.
  - Risk matches need evidence cues, routing and the anchor's risk tags.
  - A `selected` candidate with a manual/blocking-only risk tag fails.
  - `title_hook_summary_must_be_source_faithful` is listed under
    `human_required`. RGR-03 bad openings are reported as findings only.
- Agent v2 evaluator:
  - The status is only `TECHNICAL_PASS_HUMAN_PENDING`, `TECHNICAL_FAIL` or
    `INVALID_EVIDENCE`. A source-hash mismatch gives `INVALID_EVIDENCE`.
  - The report splits into `mechanical_failures` (the only blockers),
    `not_applicable` and `human_required`.
  - Executed Profiles are the Global Review `requested_profiles` that still
    have at least one final candidate.
  - The raw score is out of 100 with threshold 85 and an applicable maximum
    of 88 (D1).
  - The CLI stages both reports in a private sibling directory. It publishes
    them as one atomic no-replace unit via
    `liveclip.media.secure_files.publish_directory_no_replace_no_follow`. An
    existing directory, even an empty one, is refused, and a failure leaves
    no partial output.
  - `--output-dir` must be an absolute path whose directory chain contains no
    symlinks. For example, macOS `/tmp` is refused; use `/private/tmp/...`.
- D1--D3 are Controller interpretations pending operator confirmation, as is
  "D2 applies to semantic-only candidates; no semantic allowance". See the
  Decision Log in `docs/exec-plans/liveclip-dual-profile-benchmark-v1.md`.
  - Update 2026-10-21: the operator **confirmed D1, D2 and D3**. The
    semantic-only reading ("D2 applies to semantic-only candidates; no
    semantic padding allowance") remains **pending operator confirmation**.
  - Update 2026-10-21 (later): the operator **confirmed** the semantic-only
    reading as well.
- Independent tester evidence at `6c465b7`. Mock/fixture only, run with
  `NODE_LTS_BIN=/opt/homebrew/opt/node@22/bin PYTHONDONTWRITEBYTECODE=1`.
  - `make lint` exit 0:
    - ruff "All checks passed!" and "446 files already formatted";
    - mypy "no issues found in 230 source files";
    - schema match;
    - `tsc` clean.
  - Targeted tests (evaluators, `dual_profile`, `secure_files`): 116 passed.
  - `make test` exit 0:
    - backend 2612 passed, 15 warnings (deprecations only), 1384.97s;
    - Web vitest 14 files / 80 tests;
    - e2e:mock 1 passed;
    - e2e:real legacy 1 passed, "Required browser scenario execution: PASS";
    - e2e:real completion 1 passed: retained-package status PASS, run
      `9f8bdc31ac4c45fb8e79b76ccbd6d3b4`, `full_mp4_decode` PASS,
      `fixture_removed` true;
    - e2e:real B2 1 passed: retained-package status PASS, run
      `e9085d40edfe411d819bf443ece89183`, `full_mp4_decode` PASS.
- Coder self-checks, each labelled with the SHA and round it ran on:
  - Round 0 at `bf83c80`, main worktree:
    - `make lint` exit 0;
    - evaluator and `dual_profile` tests: 68 passed;
    - `test_b2_synthetic_worker.py` and `test_e2e_fixture.py` together with
      them: 111 passed.
  - Fix round 1 at `d9e9dde`, isolated worktree with the main `.venv`:
    - ruff check, ruff format --check (446 files) and mypy (230 files):
      exit 0;
    - evaluator and `dual_profile` tests: 81 passed;
    - b2/e2e fixture tests: 43 passed.
  - Fix round 2 at `6c465b7`, isolated worktree:
    - ruff, format and mypy: exit 0;
    - evaluator, `dual_profile` and `secure_files` tests: 116 passed (85
      without `secure_files`, 31 for `secure_files` alone);
    - b2/e2e fixture tests: 43 passed.
- Earlier tester evidence:
  - The baseline at `7d2689c` was fully green (backend 2545 passed).
  - At `bf83c80`, `make test` exited 2 only at the e2e:real completion
    retained-package check (`ValueError: exactly one retained completion
    package required`), and B2 was not reached.
  - Cause: a leftover package in the ignored
    `apps/web/playwright-report/completion-packages/`, left by the earlier
    baseline run in the same worktree. The Controller moved that ignored
    folder (it was not deleted) to the session scratchpad archive before the
    `6c465b7` run.
- Reviewer verdicts: `bf83c80` CHANGES_REQUIRED (2 P1); `d9e9dde` ACCEPT;
  `6c465b7` ACCEPT. No P0/P1 are open.
- Known harness non-idempotency (predates Stage 1; candidate for a later
  stage): a second `make test` in the same worktree fails unless
  `apps/web/playwright-report/{completion,b2}-packages` hold no prior
  package.
  - Update 2026-10-21: being addressed by Stage 2 on
    `claude/liveclip-stage2-e2e-harness` (pending acceptance); see the
    Stage 2 section above.
  - Resolved 2026-10-21 by Stage 2, ACCEPTED at `cfcff0d`.
- Open follow-ups (not done):
  - Reviewer P2-b: pin the staging directory identity (`expected_identity`)
    in the Agent report publication and make cleanup fd-based. (2026-10-21:
    addressed by Stage 6, pending acceptance.)
  - Reviewer P2-c: add an end-to-end rollback test after a real rename.
    (2026-10-21: addressed by Stage 6, pending acceptance.)
  - Earlier P2-5: Agent risk discovery counts only final candidates. This is
    stricter than necessary, because superseded raw candidates could also
    prove discovery. (2026-10-21: examined by Stage 6 and not changed: the
    MD treats a dropped risk candidate as a disappearance, so the strict
    reading stays pending an operator answer. See the Stage 6 section.)
  - The e2e harness non-idempotency above (2026-10-21: being addressed by
    Stage 2, pending acceptance). **Resolved** by Stage 2, accepted at
    `cfcff0d`.
- Caveats:
  - This is deterministic validation only. There was no rendering
    acceptance, no human editorial/audio review and no model inference.
  - The retained cold-18 PASS 90.36 came from the earlier, looser evaluator.
    It has not been re-scored under the strict evaluator and must not be
    cited as a strict PASS. Re-scoring needs operator authority because the
    evidence is outside this worktree.
  - D1--D3 and the semantic-only padding reading are pending operator
    confirmation. (2026-10-21: D1--D3 confirmed by the operator; the
    semantic-only padding reading is still pending.)
- Path lists not updated:
  - The frozen `tools/loop_engineering/m3s_v40/v44/v45_source_freeze.py`
    list `scripts/evaluate_agent_benchmark.py` as a path. They were left
    byte-identical as historical records; those files were not edited.
  - Neither those lists nor the acceptance-v3 Coder allowlist include
    `scripts/benchmark_gates.py` or `scripts/__init__.py`. This is recorded
    for future formal-loop runs only.
- Next: await operator confirmation of D1--D3 and the Stage 2 choice. Do not
  push.
  - Update 2026-10-21: the operator confirmed D1--D3 and chose Stage 2
    (real-browser e2e harness idempotency; see the Stage 2 section above).
    The semantic-only padding reading is still pending operator
    confirmation.
  - Update 2026-10-21 (later): the operator confirmed the semantic-only
    no-padding-allowance reading. No Stage 1 interpretation remains pending.

## Local asset boundary corrected in the current Git tree (2026-10-20)

- `/input`, `data/models`, `data/evaluations`, and `data/deliveries` are all
  local-only asset categories and must not enter Git. At checkpoint HEAD
  `1e8bb7b9bde0d86188c5f9cbecf462f255815b7f`, the first three categories had
  zero tracked paths.
- Source/evidence commit `96b704d70b320ecff01e588c866aee6191ec7ecb`
  published 83 `data/deliveries` files totaling 51,057,160 bytes. This
  correction removes those paths from the current Git tree while preserving
  every local file and its bytes. The new explicit `data/deliveries/` ignore
  rule prevents ordinary restaging.
- This ordinary follow-up does not erase the delivery files from prior Git
  history. Rewriting history or force-pushing requires separate explicit
  operator authority and is outside this checkpoint.
- All validation, publication, authentication, and fresh-AI boundaries below
  remain unchanged. In particular, M3A-v8 was never executed and remains
  stale/forbidden; any later authentication requires a fresh M3A-v9-or-later
  design and authority.

## Agent v2 publication complete (2026-10-19)

- Branch `main` published the source/evidence checkpoint as commit
  `96b704d70b320ecff01e588c866aee6191ec7ecb`. The single authorized push of
  `main` to `origin/main` succeeded; the immediate post-push state was clean
  with HEAD/upstream divergence `0/0`.
- The final audited publication contained 202 files / 62,739,131 bytes: 183
  added and 19 modified, with 230,535 insertions and 1,279 deletions. The
  largest file was 7,481,527 bytes; no file was at least 100 MB. Staged
  `git diff --check` passed, and the audit found no forbidden paths, real
  credential-shaped findings, or nonempty sensitive `.env.example` values.
  Before that final audit, trailing whitespace and a new blank EOF were
  normalized in one newly added delivery report.
- Ignored local state was excluded, not deleted: credentials/private HOME,
  `data/evaluations/agent-v2-oauth-full-v4-20260928`,
  `apps/web/playwright-report`, `apps/web/node_modules`, `/input` source media,
  and other ignored local state.
- Validation truth remains: lint PASS; retained backend evidence of 2,545
  passed / 15 warnings in 1,329.79s; Web unit 14 files / 80 tests PASS; and
  mock, real review/API/leased Worker/FFmpeg, completion/recovery, and B2
  browser-render evidence PASS. No human editorial/audio review and no new
  model inference/evaluation occurred.
- M3A-v8 was never executed and remains stale and forbidden. Any future
  authentication work requires a fresh M3A-v9-or-later design and exact new
  authority. Never reuse V48/M3A-v8 IDs, roots, attempts, envelopes,
  candidates, or run IDs.
- Fresh-AI read order: `AGENTS.md`, this `STATUS.md`, then
  `docs/exec-plans/liveclip-agent-runtime-v2.md`; verify HEAD/upstream before
  work. On this host use `NODE_LTS_BIN=/opt/homebrew/bin`. The evidence-backed
  Agent v2 publication checkpoint is complete; further product work starts as
  a new bounded milestone.

## Publication validation evidence closed (2026-10-19)

- Exact lint gate PASS:
  `PYTHONDONTWRITEBYTECODE=1 NODE_LTS_BIN=/opt/homebrew/bin make lint`. Ruff
  check PASS; Ruff format reports 444 files; mypy PASS over 228 files; Schema
  PASS; Web typecheck PASS. This host requires
  `NODE_LTS_BIN=/opt/homebrew/bin` because the Makefile default `/usr/local`
  Node is x64.
- Backend pytest remains retained evidence: 2,545 passed, 15 warnings in
  1,329.79s. It ran before only later non-behavioral import/string wrapping and
  Makefile/docs/config corrections. There is no post-edit full `make test`
  PASS claim.
- Web unit: 14 files / 80 tests passed in 4.13s. Final browser environment was
  `NODE_LTS_BIN=/opt/homebrew/bin` plus
  `PLAYWRIGHT_BROWSERS_PATH=/Users/junhuaxu/autoclip/.cache/playwright`.
- Mock browser: 1 passed. Real review/API/leased Worker/FFmpeg: 1 passed in
  22.1s, retained run `400df65cf47a4e3bb4cb54df4dded658`, source SHA-256
  `8d928ac18f630529f7f812c59978fd00998e3435cf95a3e857855814fdd76c54`.
- Completion/recovery: 1 passed in 1.2m, retained run
  `96f57243c99844a68502c1863ade98f9`, ZIP SHA-256
  `90333087db9de0658fdaa6fb94d28c3163215054d28f66f505dffac5ddfbd5dc`,
  full MP4 decode PASS. B2: 1 passed in 1.3m, retained run
  `53efb912534b47d1bc716b81116a7243`, ZIP SHA-256
  `4e6095172c50516802e9302b856490aaf7a6b1f6c8930843b673cb3099d741a5`,
  full MP4 decode PASS.
- Retained environmental stops: x64 `/usr/local` Node lacked Rollup x64 for
  the arm64 dependency tree, so no product assertion ran; the first real E2E
  lacked the Playwright cache variable after Mock had passed. Both were fixed
  through environment selection without source or dependency mutation.
- Engineering tests and real local media/browser rendering now have evidence.
  Human editorial/audio review and new model inference/evaluation did not run.
- Next action: trusted publication of reviewed safe nonignored paths, excluding
  credentials/private HOME, ignored old evaluation, ignored Playwright reports,
  and source media. Secret-scan the exact staged inventory before commit; push
  only under separate authority.
- M3A-v8 was never executed and remains stale/forbidden. A later AI starts with
  `AGENTS.md` and `STATUS.md` and must design M3A-v9+ fresh if authentication
  resumes; never reuse V48 IDs, roots, attempts, envelopes, or run IDs.

## Publication preparation; V8 handoff abandoned (2026-10-19)

- Branch is `main`; pre-publication base HEAD is
  `2f361fcddc0e63ae62ee62826e27b54bb8204c53`. No commit or push occurred in
  this cycle.
- The M3A-v8 opaque handoff was **NEVER executed**. Its frozen authorization
  envelope and argv are abandoned, stale, and forbidden because these
  publication edits change delivery inventory and a later publication commit
  changes HEAD. Any future authentication requires a fresh M3A-v9-or-later
  design and exact authority. Never reuse V48 IDs, roots, attempts, envelopes,
  candidates, or run IDs.
- Accepted historical evidence remains `candidate.8H1oW7vy`, run
  `20261019T185413Z-870d2c8c`, and immutable M3A-v8 final index
  `2921786b01bb789a7577e7296d03c5d6987b3b77e0d3c5511ca164c0c9e9eb9d`.
- Backend engineering tests completed with 2,545 passed and 15 warnings in
  1,329.79 seconds. Overall `make test` remains non-PASS because local
  `apps/web/node_modules` lacks `@rollup/rollup-darwin-x64`. This cycle did not
  render real media, perform human editorial/audio review, or run inference.
- Initial full Ruff reported 2,258 errors: overwhelmingly immutable
  source-freeze byte-format/upgrade noise plus three ordinary findings. The
  frozen `m3a_v*` / `m3s_v*` scripts remain byte-identical; narrow per-file
  ignores cover only `E501`, `E701`, `E702`, `I001`, `RUF059`, `RUF100`,
  `UP012`, `UP022`, and `UP035`. The three ordinary findings are repaired
  without behavior change. Independent QA then found the Makefile formatter,
  not Ruff checking, still tried to rewrite all 25 frozen scripts. Only that
  formatter line now excludes the two exact frozen glob families; the Ruff
  checker is unchanged. In the exact final `make lint`, Ruff check passes and
  the formatter reports 444 files already formatted; mypy then reports 199
  existing errors in the same 25 immutable scripts and stops the target before
  Schema/Web checks. That stop is retained. A separately authorized narrow
  mypy fence now excludes only
  `^tools/loop_engineering/(m3a|m3s)_v[0-9]+_source_freeze\.py$`; product,
  scripts, and ordinary loop-engineering sources remain typed. The final exact
  `make lint` passes: Ruff PASS, 444 files formatted, mypy PASS over 228 source
  files, EditPlan Schema current, and Web typecheck PASS. No frozen byte
  changed. Final `git diff --check` passes.
- Publication intent includes safe nonignored source, configuration,
  migrations, docs, tests, and evidence. Credentials, private HOME, ignored old
  evaluation artifacts, source/generated media, databases, caches, and retained
  external roots/runs remain excluded.
- Fresh-developer read order: `AGENTS.md`, `docs/PRODUCT_SPEC.md`,
  `docs/SOLUTION.md`, `.agent/PLANS.md`,
  `docs/exec-plans/liveclip-v2-loop-engineering.md`, the Living ExecPlan, then
  this file.
- Next action under separate authority: inspect and secret-scan the exact staged
  safe inventory, create one reviewable publication commit, and push only when
  authorized. Restore the missing Web dependency in a clean published checkout
  and rerun `make test`. If authentication is later needed, design M3A-v9 or
  later from that published state; never replay V48/M3A-v8.

## M3A-v8 root accepted; opaque handoff frozen (2026-10-19)

- Transport session `96386`, PID `56949`, exited zero in
  0.5446155829704367s with stdout 50 /
  `3e5ce8fec522d09703275bf0f3243aed9ee5cfa5c23e3d5bbbc4146790d1e930`,
  empty stderr, and `M3A_V8_ROOT_TRANSPORT / PASS`. It created only driver
  31,746 /
  `2a76b7ee7a492e7a7528f181056bce028cb619d07284b1c68025c7ece0fb5110`,
  acceptance 1,230 /
  `0b5d19b426003a6e6ce1bce68eae6d928d53758f4bb18b8641a97409d2aeac07`,
  and source receipt 432 /
  `c9d12f10f9efebe149305af47e31a5dd2a2a344150501f3e75510a93a1b97582`.
- Self-check session `97376`, chunks `7e6179` / `8c2561`, PID `63366`, exited
  zero in 0.6598972500069067s. Stdout was 51 /
  `36bed147dcd8cb14df63b66a318cbb9158aa74b502b00d9e1053c3279e8860c6`;
  stderr was empty. It added only writer test 84 /
  `7d4ee38032bc59806c6a9c35e74ed68ded7be53710ce3c9bca3940250e8118c4`
  and self-check 993 /
  `73cab89384563c7729c20b1d49c6cafd3812288391f7fd4beaa34ec6bcb2b3f0`.
- Finalize session `8056`, chunks `0d1786` / `992f8f`, PID `67968`, exited
  zero in 0.6044017089880072s. Stdout was 79 /
  `f91eae3fc446d941e2a7673d29c963f10ef256b749ade78033a3816bc77b83b7`;
  stderr was empty. It added only final index 475 /
  `2921786b01bb789a7577e7296d03c5d6987b3b77e0d3c5511ca164c0c9e9eb9d`,
  verdict `M3A_V8_READY_FOR_CONTROLLER_REVIEW`.
- Root directories remain uid 501 mode `0700`, root files uid 501 mode
  `0600`, root-private `home`/`tmp` empty, and the five-file receipt domain
  exact. Auth result is absent; no process, credential, or login child ran.
- Root-bound historical documents remain ExecPlan
  `61a5964cb870c13bdff8b073403533dd30c6c2ca64920c9f8d979e0192a50ec3`
  and STATUS
  `7fcbc38b72121e0be5dfb8cb1c101c02a434e2ecc83f75d91076b5012f25b259`;
  helper/contract remain
  `636431e804c084e3beb409c19453dfb712e228fe97736f96fc0efccf75c2373e` /
  `0f82c48df15e38c662497df52ffcb941c305497fc420f6b36502f329f0d1f68f`.
- Delivery remains 0/15/183; candidate remains 0/15/74; candidate count is
  29; `candidate.8H1oW7vy` / `20261019T185413Z-870d2c8c` remains pristine
  received at 0/0; accepted V48 final provenance is unchanged.
- Transport, self-check, and finalize budgets are consumed. Handoff,
  exclusive destination/result, formal/model, publication, and downstream
  budgets remain unconsumed. Root acceptance is not authentication authority;
  authentication is not formal authority.
- One later 17-string opaque handoff command and compact authorization
  envelope are frozen against the final post-root documents and sealed root.
  It uses the candidate repository, `/dev/null`, exact eight-name clean
  environment, 120-second outer / 30-second login bounds, DEVNULL child
  channels, 4,096-byte sanitized stdout, 65,536-byte diagnostics, and only
  the exact eight-field sanitized result. Raw credential bytes/metadata may
  never be observed, emitted, hashed, serialized, logged, receipted, or
  committed.
- Next boundary: independent reconstruction followed by fresh exact operator
  authority citing the reported canonical authorization-envelope SHA-256 for
  one opaque V8 handoff only. Do not hand off, run login status, start
  roles/models, use `--last`, or run `resume_liveclip.sh`.

## V48 final provenance accepted; M3A-v8 source frozen (2026-10-19)

- The sole V48 final-controller acceptance used session `20939`, chunks
  `629028` / `5e8922`, PID `20568`, and exited zero in
  7.639066500007175 seconds. Stdout was 751 /
  `27ab811220202b40ef6886fd5ff9686face24b850d620004fb2fac6d0332d65b`;
  stderr was empty; preflight snapshot was 1,838 /
  `dcd09de2f6bbd0909a908f85f2d458f6e9fa6492c62ee887cef3a93bb62a48b8`;
  verdict is `M3S_V48_FINAL_PROVENANCE_READY_FOR_CONTROLLER_REVIEW`.
- Five mode-`0600` outputs are accepted: final acceptance 5,132 /
  `7d50309503a1fa5ccdb40f1036c2902d624978505865027a456b55764ef2c1cb`,
  transport 1,383 /
  `520281505508fef8bb8428a9dfc82e339f8ec3da7f3bc3e23ac783997ff35baa`,
  repository manifest 6,146,580 /
  `251b988f9a090b3afeedb6e40b2a7828bcffbdc8650ed4685fe47742a8554c47`,
  attempt manifest 12,184,575 /
  `9fdf7bfcbbf5967d80f4672a470d28da8ff689932b1cf0a0e72c53bc9ac3a46f`,
  and final index 2,731 /
  `f883864347d69e1011fdd2d7f77bbcf8688b806583a4c1ce8dcb3d364455e403`.
  Completed tree is 44,358 paths / 968,178,470 bytes /
  `9fdcea266b847db25389f1412d819ca89e2824f6c4c202350518a619c6eb0d1f`;
  42 receipts are bound and `secret_material_accessed` is false.
- `candidate.8H1oW7vy` / run `20261019T185413Z-870d2c8c` remains pristine
  received at 0/0. State/events are
  `e00eb8d809c55bd767280a4b1bda8d63f265ffa4528e7259e16951e77d36b2a7` /
  `08877d5d9c90a30e5a9f5859c48cfaacf86f6262158dc6b7d961cd46a99efe5f`.
  Target inventory is 0/15/74; delivery becomes 0/15/183 solely from the new
  helper; candidate count is 29. Root final/auth results remain absent.
- V7 remains immutable and non-reusable. Its retained handoff stopped before
  credential access with `ROOT_ACCEPTANCE_SCHEMA_MISMATCH`: the producer used
  extra `writer` and omitted `source`, while its index omitted required
  `root_argv_sha256` / `source_sha256`. V8 uses one shared exact root schema
  validator and rejects both stale V7 forms plus missing/extra/altered fields.
- New `tools/loop_engineering/m3a_v8_source_freeze.py` derives V8 from the
  exact V7 driver while preserving opaque-copy, termination, pinned login
  status, DEVNULL child channels, and eight-field sanitized receipt behavior.
  It binds accepted V48 provenance, policy/toolchain/trusted context, exact
  branch/HEAD, inventories, 29 candidates, and pristine run. Fixed no-replace
  `m3-authentication-handoff-v8` root/result are absent and no credential path
  was probed.
- Future phases are separately authorized `M3A_V8_ROOT_TRANSPORT`,
  `M3A_V8_ROOT_SELF_CHECK`, and `M3A_V8_ROOT_FINALIZE`; finalize stops at
  `M3A_V8_READY_FOR_CONTROLLER_REVIEW`. Each uses immutable seed cwd,
  `/dev/null`, exact eight-name clean environment, 120 seconds, 65,536-byte
  diagnostics, empty stderr, exclusive writes, retention, and no retry.
- A still-later 17-string opaque handoff argv is statically frozen against the
  final documents and future sealed root. It alone may copy opaquely and run
  pinned login status for 30 seconds with all child channels DEVNULL. Raw
  credential bytes/metadata are never observed, printed, logged, hashed,
  serialized, receipted, or committed. Authentication is not formal model
  authority.
- Final acceptance and its destination budgets are consumed. V8 root,
  handoff/destination/result, formal/model, publication, and downstream
  budgets remain unconsumed. The next boundary is independent reconstruction
  and one explicit authorization for `M3A_V8_ROOT_TRANSPORT` only; do not
  self-check/finalize/handoff, use `--last`, or run `resume_liveclip.sh`.

## V48 preparation accepted; final-controller acceptance frozen (2026-10-19)

- The sole V48 verifier PASS remains immutable: session `29932`, PID `62758`,
  exit 0 in 69.892868792 seconds, stdout 5,103 /
  `8ef2eeafebfb872ec7ec509edf6a16afd29e479db64b9b47f65c2f6dd513119f`,
  empty stderr, semantic `M3S_V48_POST_ROOT_VERIFY_PREPARE / PASS / 76`, and
  byte-identical protected snapshot 2,447 /
  `4c1def0cf6a3ae74c54d3ed141834e1dacb34d8a3d06c809eb8ee8c23ad9dc22`.
- The sole prepare used session `27936`, PID `71625`, launch/terminal chunks
  `9ef846` / `acfd99`, and exited zero after 206.52516108303098 seconds;
  wrapper elapsed was 206.449953 seconds with no timeout, truncation,
  overflow, credential variable, or wrapper error. Stdout was 160 /
  `bdc97dd5acd7b91bcd99c6c84399adb75046ca3e333e6d2cbcd499d11127b20f`;
  stderr was empty.
- Root result is 23,851 /
  `6d54a37978db7d5bc37ff131ba9156f28317c1b460204412e4b7d459bae2914d`.
  Exactly one candidate `candidate.8H1oW7vy` and pristine run
  `20261019T185413Z-870d2c8c` were created. State/events are 12,796 /
  `e00eb8d809c55bd767280a4b1bda8d63f265ffa4528e7259e16951e77d36b2a7`
  and 144 /
  `08877d5d9c90a30e5a9f5859c48cfaacf86f6262158dc6b7d961cd46a99efe5f`;
  the run remains received at 0/0 with no Coder/error/artifacts/results.
- All 38 receipts sealed without error. Final index is 18,096 /
  `f72bf846f30ca9f86254c966d84b00bb5f73fd837c9e0045cca47b6282151982`
  with verdict `M3_SUCCESSOR_PREPARATION_V48_AWAITING_CONTROLLER_ACCEPTANCE`.
  Readiness, 103-link/zero-unsafe post-setup, terminated rc-0 doctor, one
  loop-init, policy/toolchain/trusted-context bindings, and preservation all
  pass. Repository/attempt manifests are 6,146,377 /
  `c0578ec62ddeab5b680ea6941d102ebe6a34bb103b779a58625c128f7bf98384`
  and 12,183,529 /
  `a15e6257c7695c5d347f181cad1d6945fe855449029dc38333e400280e28a66d`;
  completed tree is 44,353 paths / 949,838,069 bytes /
  `26c358b03743ccb5bf934cdba4f1484af3bb30a13038dd3432f0063bc80267b5`.
- Historical root-bound documents remain
  `19a6df38d8568c4cec3469a931293f032da079dde308d2717e843690e7d51d65` /
  `e20bc8f5bbb4669cc650d08347981c9ccd050f7cb3339b90cc3464a14f73fb3a`;
  offer-bound preparation documents remain
  `e9054b2eaa5e9abdf510812e60b03e9ac3cf6abd71c47ca82ab4a2e5d67ee7c8` /
  `ea8c0f771496a5209dae18421134b3a5733e8274d149f8e9dfadd6e2dcc16506`.
  Delivery is 0/15/182, candidate is 0/15/74, candidate count is 29, no
  process remains, and all seven final/auth destinations are absent.
- Canonical external acceptance is 5,131 no-LF bytes /
  `a862f0173bd1850f0161a4d9b3e1d6a491952077b780b5bfbddc6ea4b5e211c4`
  and 5,132 plus-LF bytes /
  `7d50309503a1fa5ccdb40f1036c2902d624978505865027a456b55764ef2c1cb`.
  The frozen direct `accept-final` command is 17-string Python argv,
  32-string clean vector, quoted no-LF payload, and four-string outer zsh
  argv from `candidate.8H1oW7vy/repo`, `/dev/null` stdin, 120-second driver
  and outer bounds, and 65,536-byte diagnostics. Exact final identities are
  reported after both documents close.
- Verifier, prepare/result, suffix, and loop-init budgets are consumed.
  Final acceptance and five destinations are unconsumed; authentication,
  formal/model, publication, and downstream remain separate and
  unauthorized. The next safe action is independent reconstruction followed
  only on exact match by fresh authority for one direct V48 `accept-final`.
  Never retry/reuse, authenticate, invoke roles/models, use `--last`, or run
  `resume_liveclip.sh`.

## V48 root accepted; allocation-free verifier frozen (2026-10-19)

- The separately authorized V48 transport, self-check, and finalize phases
  each completed once and are independently accepted. Transport used
  preflight session `44055`, execution session `40054`, PID `31761`, and
  exited zero in 114.967978958 seconds. Self-check used session `10114`, PID
  `43438`, and exited zero in 55.755630750 seconds. Finalize used session
  `36042`, PID `46491`, and exited zero in 57.993949833 seconds. Exact stdout
  identities are 51 /
  `22f52d4f0e508bb81b62ee80efe2a530161f0d31e5a67d7b6ceec7f0edb0cd5b`,
  52 / `ef538ae7ee89168efafc38175b14498aa12a96b3994631c7bf32eaa0c990d224`,
  and 398 /
  `3642bbaf23a8afc3672e4fe43666fbbabb93cfc8a99d77de064a94d963a5bba1`;
  stderr was empty throughout.
- The fixed uid-501 mode-`0700` root has exact entries
  `candidate-driver.py`, empty `home`, `receipts`, and empty `tmp`. Its six
  uid-501 mode-`0600` files are driver 577,054 /
  `cf6000818bc06823e3ae7464f6e7218365b06dcfaa8bf0fb95d11ddcb317ec30`,
  controller acceptance 16,999 /
  `e46d3f0cef022139e8a1bcfe888a49985bd1e4ea06fa2d24d10303eeba6c060b`,
  source 381 /
  `34b070a94466dfe17a0c37cdeced3383d14a702f85379068ee1833a8307d26ce`,
  writer 53 /
  `3c31afa2642bd63ff436297754cf593ca0cb9d3c14924c3abfdc4e7358f498d8`,
  self-check 4,320 /
  `597581fc98d40596f4b30b5a7ca07244704d3ea4b41e3d367eb92524c48068df`,
  and final index 800 /
  `c5d453ab94cb71f564a72517242fc692c8af0d3842101bf08ff092746a775fb0`.
  Verdict is `M3S_V48_READY_FOR_CONTROLLER_REVIEW`.
- The shared flat final-index schema passed producer/consumer validation and
  rejects the stale nested form plus missing, extra, or altered bindings.
  Historical root-bound document hashes remain ExecPlan
  `19a6df38d8568c4cec3469a931293f032da079dde308d2717e843690e7d51d65`
  and STATUS
  `e20bc8f5bbb4669cc650d08347981c9ccd050f7cb3339b90cc3464a14f73fb3a`;
  current post-root document hashes are reported after this closure.
- Delivery remains 0/15/182 with Git-status SHA-256
  `0322968cb252e9674f7905ce84f3d067da33310a184f64343e425f0d5b7e62b5`;
  the exact 28 candidates remain at digest
  `ca8f3f7675393b11c2612a212b7439cf95d1c8ba9bf0c1506b246c95029e3f32`.
  All three reserved results are absent and no V48 process remains.
- Root/transport/self-check/finalize budgets are consumed and non-retryable.
  Verifier, prepare/result, suffix, loop-init, final acceptance, fresh M3A-v8
  authentication, formal/model, publication, and downstream budgets remain
  unconsumed and unauthorized.
- The next boundary is one allocation-free `verify-prepare` invocation bound
  to the externally reported final document hashes: 25-string Python argv,
  39-string clean vector, quoted no-LF payload, and four-string outer zsh argv
  from immutable `candidate.OlsWg1/repo`, `/dev/null` stdin, 120-second driver
  and 150-second outer bounds, and 65,536-byte diagnostics. Expected output is
  exact `M3S_V48_POST_ROOT_VERIFY_PREPARE / PASS / 76` JSON and empty stderr,
  with byte-identical pre/post state. Verifier PASS is not prepare authority.
- The later 25-string prepare argv and 17-string bounded-wrapper vector are
  separately frozen at 2,730/2,760 seconds but remain unexecuted and
  unauthorized. No document edit may occur between accepted verifier PASS
  and a later prepare launch.
- Resume prompt: independently reconstruct the final ExecPlan/STATUS, sealed
  V48 root, inventory/candidates/absences/process state, and externally
  reported verifier argv/vector/payload/outer/expected-stdout identities.
  Only on complete PASS may the controller authorize exactly one allocation-
  free V48 verifier. Do not prepare, allocate, authenticate, invoke
  roles/models, use `--last`, or run `resume_liveclip.sh`.

## V47 verifier closed; V48 source frozen (2026-10-19)

- The sole V47 verifier is consumed failure evidence: chunk `4e41ba`, no
  session, PID 57359, child/supervisor exits 1/97, 0.26535320800030604s
  child elapsed, empty stdout, and 979-byte stderr SHA-256
  `6cc9de8f52a304fc056d605adc744e48def679e4f1cab157c852e9342b5d6dd4`.
  Postflight snapshot remained 3,058 bytes /
  `47430f6e28c29f52e31db1a22254ec2d3c422bd5cee47b54c6d5d2cf47a8511c`.
- Exact cause is sealed V47 driver lines 8233/8283 reading stale nested
  `controller_acceptance.sha256`; immutable `final-index.json` contains only
  flat `controller_acceptance_sha256` with value
  `c1d0aedabd70f6d567240c8336494ad60fe137ff2d292d8d3581d4080bea4785`.
  The reconstructed Python 3.12 traceback matches retained stderr exactly.
- V47 root and all six artifacts remain immutable; all reserved results are
  absent. V47 verifier is consumed and its prepare/result, suffix, loop-init,
  acceptance, and later budgets are abandoned with V47 and never reused.
- New `tools/loop_engineering/m3s_v48_source_freeze.py` derives only from the
  exact V47 helper/driver and binds its complete root/failure closure. One
  exact flat root-index validator is used by root-finalize production and by
  both verifier/prepare consumers. Positive producer agreement and eleven
  schema negatives pass; cached historical validation remains 76 gates.
- V48 preserves 28 predecessors, 13-path Coder scope, 103 safe links, v1 and
  dual-profile paths, one future unpredictable suffix/loop-init, isolated
  Coder, read-only roles, Runner/Gateway, and one-writer publication.
  Delivery closes at 0/15/182; fixed V48 root/results/candidate/run remain
  absent. No credential, role, model, test, render, evaluation, publication,
  or product action ran.
- Next safe boundary after independent reconstruction is one credential-free
  V48 root `transport` only, using the final canonical bundle, immutable seed
  cwd, exact eight-name clean environment, `/dev/null`, 120 seconds, and
  65,536 diagnostics. Self-check/finalize and all post-root work remain
  separately unauthorized.

## V47 root accepted; allocation-free verifier frozen (2026-10-19)

- The separately authorized V47 transport, self-check, and finalize phases
  completed once and are independently accepted. Their exact compact stdout
  identities are 51 /
  `443b6687c675ff68052d835452088aab7cad0372370867242d070252aec9d2da`,
  52 / `59b3fde0024b8d52c6f40aa8db95f1ccb971d1cf4ffdd448bb765bfc803a62ff`,
  and 398 /
  `66481e8a572cd74543849004f4970ac9af5acc24349016e7c7b4f544ee10583e`;
  stderr was empty for every phase.
- The fixed uid-501 mode-`0700` root has exact entries
  `candidate-driver.py`, empty `home`, `receipts`, and empty `tmp`. Its six
  mode-`0600` files are driver 563,598 /
  `849686aa1d05585a2fdc995db5802653f861a732f74cf1092bea681c83058115`,
  controller acceptance 14,704 /
  `c1d0aedabd70f6d567240c8336494ad60fe137ff2d292d8d3581d4080bea4785`,
  source 381 /
  `5e0afde94bf4249298e9666780afc0cbd71f9552494a12f5193548b617973f66`,
  writer 53 /
  `30ad1ab8d5a9932d1ac7222938f86c2e176a57e0f0703cf2b908dc4a239b8e5b`,
  self-check 3,925 /
  `3c2be8021896107348906d6e06cdfd2836451cd7860dce4645a4f705ff08fc07`,
  and final index 800 /
  `238d01798251a909ce67317dfbc21ed315ef435f5278908307459ed632c5c33c`.
  Verdict is `M3S_V47_READY_FOR_CONTROLLER_REVIEW`; self-check records all
  76 gates PASS.
- The accepted gap audit preserved a 3,058-byte protected snapshot
  `028d1898e0bbefbd6be671be3f515a2b63220c98f66225f7651855af4b0d7f98`.
  Delivery remains 0/15/181 with Git-status SHA-256
  `618ca653d0924f0db34cd029cca0cd05e9a51b5d7e7b4509619eefe32e6b68ef`;
  the exact 28 candidates remain, no V47 driver process exists, and all
  three reserved V47 results are absent.
- Root creation/transport/self-check/finalize budgets are consumed and
  non-retryable. Verifier, prepare/result, suffix, loop-init, final
  acceptance, M3A-v8 authentication, formal/model, and downstream budgets
  remain unconsumed and unauthorized.
- The next boundary is one direct allocation-free `verify-prepare`: exact
  25-string Python argv, 39-string clean vector, quoted no-LF payload, and
  four-string outer zsh argv bound to the final document hashes reported
  after this closure. It uses immutable `candidate.OlsWg1/repo`, `/dev/null`,
  120-second driver / 150-second outer bounds, and 65,536-byte diagnostics.
  Expected output is one compact `M3S_V47_POST_ROOT_VERIFY_PREPARE / PASS /
  76` JSON line and empty stderr, with byte-identical pre/post state.
  Verifier PASS is not prepare authority; prepare is separately frozen at
  2,730/2,760 seconds but remains unexecuted and unauthorized.
- Resume prompt: independently reconstruct the final ExecPlan/STATUS, sealed
  V47 root, exact inventory/candidates/absences/process state, and externally
  reported verifier argv/vector/payload/outer identities. Only on complete
  PASS may the controller authorize exactly one allocation-free V47 verifier.
  Do not prepare, allocate, authenticate, invoke roles/models, use `--last`,
  or run `resume_liveclip.sh`.

## V46 timeout closed; V47 cached-audit source frozen (2026-10-17)

- V46 preflight passed canonical comparison, ten negatives, all 74 gates,
  and no-write snapshot 1,121 bytes /
  `22a9224e4d0beb6bd6034dabaabbbb5417bb59de30fb4e7cb476d1ec6cacc7d4`.
  Sole transport session `86208` (chunks `93018f`/`4ded26`/`ad1c6f`/
  `4f074f`/`f84a37`/`557631`, PID `42457`) timed out at
  120.00495970802149 seconds: child `-9`, supervisor `247`, empty stdout and
  stderr, no overflow, and no root/artifact/result/process. V46 transport is
  consumed and abandoned; all later budgets remain unconsumed.
- Read-only profiling localized the defect to redundant hashing: 29 complete
  manifests, 684,934 file records, and 598,712 regular-file hashes drove a
  134.33583987498423-second profiled 74-gate audit. No semantic gate failed.
- Fresh `tools/loop_engineering/m3s_v47_source_freeze.py` preserves every
  gate and adds only a process-local, seven-field identity-revalidated hash
  cache plus an exact eight-thread in-process pool for independent historical
  manifests. Every tree remains fully traversed and hashed. Exact identity,
  seven mutation, and TOCTOU fixtures pass; no external cache is trusted or
  persisted. The derived graph has 76 gates and binds the complete V46 stop.
- V47 retains exact 28 predecessors, 13-path scope, 103 safe links, one future
  `mktemp`, one future `loop-init`, isolated roles/Runner, accepted v1 and
  dual-profile paths, and one-writer publication. Delivery closes at
  0/15/181; fixed V47 root/results/candidate/run are absent. Authentication,
  formal/model, and downstream actions did not run.
- Next safe boundary, after controller review, is one credential-free V47
  root transport under the unchanged 120-second/65,536-byte bounds;
  self-check and finalize remain separately authorized later phases.

## V45 pre-Popen stop closed; V46 source frozen (2026-10-17)

- V45 preflight session `41498` (`7c3894`/`066d01`) exited zero with all 73
  gates PASS and protected snapshot 1,098 bytes /
  `d97150050b3cc78bc6574e60aa84c1d9dc91b5475c47995f929d8b87f01cf95e`.
  Final guard session `19177` (`a8f01e`/`49058e`) exited 1 after about 8.716
  seconds with `RuntimeError: status identity mismatch`; stderr was 113 bytes
  / `c4810d4a5973d27962d91a79b60474facdfa230ed201f315ee5267d80359bd60`.
  No child PID, `Popen`, root, artifact, phase, or protected mutation occurred.
- Immediate correlation proved STATUS, ExecPlan, helper, inventory, candidate
  set, and snapshot unchanged. The defect was the ad hoc supervisor's
  duplicate handwritten comparison. V45 is nevertheless closed and never
  retried or reused; its un-crossed root budget is abandoned with that
  boundary.
- Fresh `tools/loop_engineering/m3s_v46_source_freeze.py` derives from exact
  V45 source/driver bytes, binds accepted V44/V7 and the V45 pre-Popen stop,
  and makes one canonical bundle the sole source for artifacts, phase
  commands, and launch comparisons. Ten mutation negatives reject every
  identity class before `mkdir`.
- V46 preserves exact 28 predecessors, 13-path Coder scope, v1/dual-profile
  paths, 103 safe links/zero unsafe, one future `mktemp`, one future official
  `loop-init`, fresh suffix/HOME/TMPDIR/run requirements, private-HOME
  non-traversal, deterministic Runner, and one-writer publication.
- Delivery closes at 0/15/180; retained candidate inventories are unchanged.
  The fixed V46 root, all V46 results, future candidate/run/session,
  authentication, formal/model, and downstream phases remain absent. Next is
  separately authorized credential-free V46 transport only.

## V7 consumed failure closed; V45 source frozen (2026-10-17)

- The sole V7 handoff launch (chunk `20f0c4`, PID `37540`, no session) ended
  driver 1 / wrapper 96 in 0.08915825001895428 seconds. Stdout/stderr were
  both empty with canonical empty SHA-256; no sanitized result exists.
  Invocation/credential authority is consumed and non-retryable, result is
  unconsumed but abandoned, and destination is sealed possibly consumed.
- Pure pre-credential replay proved the exact cause:
  `ROOT_ACCEPTANCE_SCHEMA_MISMATCH`. Controller acceptance has extra `writer`
  and lacks `source`; final index has extra `phase_argv_sha256`/
  `writer_sha256` and lacks `root_argv_sha256`/`source_sha256`. No private
  runtime, credential endpoint, login child, role, or model was touched.
- Fresh `tools/loop_engineering/m3s_v45_source_freeze.py` derives only from
  sealed V44. It binds 28 retained candidates, complete V44 postacceptance
  evidence, pristine `candidate.3Wlu7MyG` run, and V7 stop without traversing
  candidate-private HOME. Actual graph: 73 gates; one future `mktemp`; one
  future `loop-init`; exact 13-path scope; 103 safe links and zero unsafe.
- Delivery closes at 0/15/179 after the one new helper; retained target stays
  0/15/74. V45 fixed root and every V45 result/candidate/run are absent.
- Next and only safe boundary is separately authorized credential-free V45
  root transport, then self-check, then finalize. Verify, prepare, final
  acceptance, fresh M3A-v8 authentication, formal/model, and downstream work
  remain distinct and unauthorized.

## Accepted M3A-v7 root and frozen handoff envelope (2026-10-15)

- Credential-blind preflight passed 32 gates with no-write snapshot
  `45c8f3072d9e894f9085ede75fddcccded8a223065b1f66a19203c020fbf3de0`.
  Root task chunk `28b6d5` had no session and exited zero in 2.558917625
  seconds. Transport/self-check/finalize PIDs `32809`/`32820`/`32831` exited
  zero in 0.510305458/0.523869750/0.546039125 seconds with expected 50/51/79
  byte stdout and empty stderr.
- Fixed V7 root and subdirectories are uid 501 mode `0700`; home/tmp are
  empty. Driver, controller acceptance, source, writer, self-check, and final
  index are 31,666 / `d4a0fb12e65ebdfdad8295cac03eb8468c3a7569b517bdb309a40006b2bb64cb`,
  1,230 / `561b5729698cf91cf93440d3b927500bd2bfb9aef9c65a03cc7f96f7c9dbb1b1`,
  432 / `894b598cae2418cc1a3ebf0bc7427182f71f9562d27a084a8b82e56d0f5396f6`,
  84 / `156b8186ccfc23de06d15001820172ec43cb3cf0ddc389bcb28c79c7d5dc6370`,
  1,201 / `3c2c31b860ede8f40b3980e9a3ed6b6b8b84e5a9c982b49a6d7b13b90c49d099`,
  and 669 / `9bd7be45d263b950b11018e10604246a04a6c2ca35efe133542fa5e850b0bc26`;
  all files are uid 501 mode `0600`. Verdict is
  `M3A_V7_READY_FOR_CONTROLLER_REVIEW`.
- Independent postflight chunk `b027d8` exited zero in 0.056370542 seconds.
  Protected evidence remained
  `8508016e818a4970e31a2c3d819105fe97c42cda146d5c527e41706d131ea227`;
  delivery is 0/15/178, target 0/15/74, candidate count 28, run pristine,
  matching processes zero, and reserved result absent.
- Root transport/self-check/finalize/invocation budgets are consumed. Opaque
  handoff/destination/result, formal/model, and downstream budgets are
  unconsumed. The exclusive destination is not probed outside the driver.
- Sealed driver `SHAPE` is 15 strings; complete Python argv is 17. The clean
  vector is 27 strings with the exact eight-name environment; payload uses
  the quoted-token rule and `/dev/null`; outer argv is four strings. Final
  identities and the canonical non-secret authorization-envelope hash are
  reported after these documents close.
- Success permits only the exact eight-field sanitized receipt, empty stderr,
  and DEVNULL child channels. Every failure retains and stops without retry,
  repair, replay, replacement, cleanup, alternate source, or second receipt.
  Authentication remains distinct from formal/model authority.
- No credential path or metadata was probed, no handoff/login child ran, and
  no role, model, test, render, evaluation, publication, commit, push,
  cleanup, or media action ran. Next is fresh exact operator authority citing
  the reported authorization-envelope SHA-256.

## Accepted V44 final provenance and M3A-v7 source freeze (2026-10-15)

- The sole actual V44 `accept-final` launch used chunk `337504`, PID `25030`,
  exited 0 in 8.393104666960426 process seconds, and produced 751-byte stdout
  `6bb4b735a7492a6833b10321ece40275e6ad4d7f26698965cb33945b61df23a9`
  with empty stderr. Semantic result is
  `M3S_V44_FINAL_CONTROLLER_ACCEPTANCE` /
  `M3S_V44_FINAL_PROVENANCE_READY_FOR_CONTROLLER_REVIEW`. Read-only chunk
  `e7f592` was a harmless prelaunch requirement-literal false positive with
  no PID, invocation, or write.
- The five accepted uid-501 mode-`0600` outputs are final acceptance 5,132 /
  `0baec92ac199860c9811b9516e8edc3a2ea11ffd73a8dce175ab832cc2dc67f4`,
  transport 1,383 /
  `b8a7d265dd77eb1171c97e3fd270bd000d09992169e6340788c5b16e8a433b28`,
  repository manifest 6,146,003 /
  `373c4fd19ff20ca1932222a8cb26cbb3e726fea441444ea91a27cf15cf6a1f93`,
  attempt manifest 12,183,983 /
  `f476ba94207b25161551f773a90436d4d6c325d6dcd238c63b3ec108c870fe0d`,
  and final index 2,731 /
  `10591eed8097571f8662b9a3ad05aeb0164aeebf2682610b4bd72bd317b07150`.
  Completed tree is 44,355 paths / 967,904,492 bytes /
  `aca8090a0b4da7967fc57e8b210400a064eec6e3bc7e67f44d0f00399412f14d`;
  receipt count is 42 and `secret_material_accessed` is false.
- `candidate.3Wlu7MyG` / `20261016T010806Z-b7f48207` remains pristine
  received 0/0 at state/events
  `88f7be523d08def41b8abf3ff6be418b90d4955c1c9c1edf8a29396a0a739af2` /
  `f3b0b329f25891455f9e00377e8eaa02f185fa569131cc347de0fa54b7e43439`.
  Candidate count is 28; delivery is 0/15/178 after only the V7 helper;
  candidate inventory remains 0/15/74. V44 final acceptance is consumed;
  authentication/formal/downstream authority is unconsumed.
- Fresh `tools/loop_engineering/m3a_v7_source_freeze.py` derives only from
  the accepted V44 postacceptance closure and exact sealed M3A-v6 security
  functions. V6 root/result/destination/authority are immutable historical
  evidence and non-reusable. Fixed no-replace
  `m3-authentication-handoff-v7` root and reserved sanitized result are
  absent.
- V7 root-only is split into credential-blind `M3A_V7_ROOT_TRANSPORT`,
  `M3A_V7_ROOT_SELF_CHECK`, and `M3A_V7_ROOT_FINALIZE`. Their helper argv
  schemas contain 15/15/19 strings; complete Python argv contain 19/19/23.
  They share immutable seed cwd, exact ordered eight-name clean environment,
  `/dev/null` stdin, 120-second outer bounds, 65,536-byte diagnostics, empty
  success stderr, exclusive writes, retention, and no-retry semantics.
- The later handoff alone may perform exclusive no-follow opaque copy, fsync,
  and pinned 30-second Codex login status with all child channels DEVNULL.
  Authentication bytes or metadata are never printed, logged, hashed,
  serialized, persisted outside the eight sanitized fields, or committed.
  Successful authentication is not formal authority. Exact helper/writer/driver/
  contract/acceptance and phase-command identities are reported after close.
- All V7 root/handoff/result/destination/formal/model budgets remain
  unconsumed. No V7 phase, credential access, login child, formal role, or
  inference ran. Next is independent review and explicit authority for only
  the three ordered root-only commands.

## M3S-v44 accept-final prelaunch correction and refreeze (2026-10-15)

- The first V44 `accept-final` authorization stopped before launch: read-only
  preflight chunk `9348b1` exited 1 and correlation chunk `78fe12` exited zero.
  No target PID/session or driver invocation existed, so final-acceptance
  authority remains one and unconsumed.
- The controller-facing preparation-result hash had only 63 hexadecimal
  characters because its terminal `e` was omitted. The unchanged result is
  exactly 23,851 bytes / SHA-256
  `ba1b1878ad5e940ac145aa14b48e5621ea4b824dc73b6d8fccd6913a90c8546e`.
  This is a transcription correction, not evidence drift, repair, retry, or
  replay; the 63-character form is an explicit rejection fixture.
- All seven acceptance/auth destinations remain absent, no matching process
  exists, and candidate `candidate.3Wlu7MyG`, pristine run
  `20261016T010806Z-b7f48207`, all sealed receipts/manifests/tree/bindings,
  exact 28-candidate set, delivery 0/15/177, and candidate 0/15/74 remain
  unchanged.
- Canonical external acceptance remains byte-identical at 5,131 no-LF bytes /
  `273b863aade8209fe0a4e8ad05c28fac2ff54eb568708ee9aec0671bdb3b76b2`;
  its one-LF transport remains 5,132 /
  `0baec92ac199860c9811b9516e8edc3a2ea11ffd73a8dce175ab832cc2dc67f4`.
  The same 17-string Python argv / 32-string clean vector / 32-token payload /
  four-string outer argv contract is rebound only to these final document
  hashes; exact post-close identities are reported outside the documents.
- Root, verifier, prepare/result, suffix, and init budgets remain consumed.
  Final acceptance remains unconsumed; authentication, formal/model, and
  downstream budgets remain distinct and unconsumed. Next is independent
  reconstruction and fresh exact authority for the refrozen direct V44
  `accept-final`; this correction cycle executes no driver.

## M3S-v44 accepted preparation and final-acceptance freeze (2026-10-15)

- The accepted verifier is session `36775`, PID `34645`, exit 0 after
  104.10001462500077 seconds, with 5,104-byte stdout
  `eaf4394ca991ee3d6718aed1094569ef6c8f27d2d868d6247b0aecbc48631b03`,
  empty stderr, semantic `M3S_V44_POST_ROOT_VERIFY_PREPARE` / PASS / 71,
  and byte-identical protected snapshot
  `8f5363c326349636b6759ddbf060cfa7e86900347be3aef083a3f602468b1517`.
- The accepted sole prepare is session `53408`, PID `46820`, wrapper/outer
  elapsed 285.146604/285.2092920000432 seconds, return 0, and no timeout,
  truncation, overflow, wrapper error, session ID, credential variable, or
  stderr. Root result is 23,851 /
  `ba1b1878ad5e940ac145aa14b48e5621ea4b824dc73b6d8fccd6913a90c8546e`;
  embedded output is 20,478 /
  `248903a2dca99f26c79a5661e49ad4aa655ee58f1f37aab208c05dcd31c02a23`.
- Candidate `candidate.3Wlu7MyG` and run `20261016T010806Z-b7f48207` are
  retained. Run state/events are 12,796 /
  `88f7be523d08def41b8abf3ff6be418b90d4955c1c9c1edf8a29396a0a739af2`
  and 144 /
  `f3b0b329f25891455f9e00377e8eaa02f185fa569131cc347de0fa54b7e43439`;
  state is pristine received 0/0 with null Coder/error and empty evidence.
- All 38 receipts seal without error. Preflight is 385,364 /
  `c63abfd304f7ddee9cf37db9f5c6a12f885dca5834ff78c8c975cbe223125da7`
  with 76 checks; post-setup is 4,224 /
  `b55599ef291cf5d214e02927763951db530a0b9a949c3b701fa178e29090ce5b`
  with 103 safe links; readiness, doctor, init, transport, policy, toolchain,
  trusted context, bindings, offer, preservation, and final index match the
  accepted identities. Final index is 18,096 /
  `4afaf3c7819498433cb5263c0c60ab6c97c1ca6f3c731c2fd73c90cad4051fbc`.
- Repository/attempt manifests are 6,145,800 /
  `4a2c4c95977fc311657bc4ce154a5b894aa1621ad78eac22429b6611734a45e2`
  and 12,182,937 /
  `9b641b1c0ba60eedb055ca35451dc6c0a5d207acf5ddf6a3efbad7ad6b92da4c`.
  Completed tree is 44,350 paths / 949,565,260 bytes /
  `dfa2769db4279b9e3aa675ab87e5b67d70ffd897d06dba1d2cd8311d9ce5f605`.
  Verdict is `M3_SUCCESSOR_PREPARATION_V44_AWAITING_CONTROLLER_ACCEPTANCE`.
- Delivery remains 0/15/177 at
  `ef1fee17a4b12b062c30971526d6593e9957ec92084bc1805d546af2a98ed082`;
  candidate is 0/15/74 at
  `4270aac58c82d5b1e74ae0412cd36622869c9b2385281a67ec507007d0a3744e`;
  candidate count is 28. Root final/auth results and all five candidate-side
  final destinations are absent; no V44 process remains.
- Read-only audit false positives were harmless and explicit: the verifier
  audit matched its own process-search source; prepare correlation corrected
  empty-object, nested-gate, and driver-identity schema assumptions. All made
  no write and corrected full correlation passed.
- Accepted categories end at credential-free preacceptance sealing. Final
  acceptance, authentication, formal/model work, deterministic Runner,
  Gateway, tests, rendering, evaluation, publication, delivery, commit, and
  push are unperformed and unaccepted.
- The canonical external acceptance is exactly 5,131 no-LF bytes /
  `273b863aade8209fe0a4e8ad05c28fac2ff54eb568708ee9aec0671bdb3b76b2`;
  transport adds one LF for 5,132 /
  `0baec92ac199860c9811b9516e8edc3a2ea11ffd73a8dce175ab832cc2dc67f4`.
  It binds candidate/run, offer, preparation-time documents, V39/V43/13-path
  trusted record, policy, toolchain, root acceptance transport, and future
  dispatch. Final current documents are independently bound in argv.
- The sealed `accept-final` schema is 15 driver strings / 17 complete Python
  argv strings. The clean vector is 32 strings and includes root-private
  HOME/TMPDIR, immutable seed `CANDIDATE_REPO`, absent root result fence,
  phase `M3S_V44_FINAL_CONTROLLER_ACCEPTANCE`, timeout 120, canonical argv,
  and the 17 Python strings. Payload uses the established quoted-token rule;
  outer argv is `/bin/zsh -f -c <payload>`. Cwd is the accepted candidate
  repo, stdin `/dev/null`, driver/outer bounds 120/120 seconds, diagnostics
  65,536 bytes. Exact final hashes are reported after document closure.
- Only five candidate-side files may be created: final acceptance, transport,
  postacceptance repository/attempt manifests, and final index. Root final
  result stays absent. Noncanonical/substituted/stale evidence, process or
  inventory drift, existing destination, timeout, unexpected output, partial
  write, or nonzero exit retains and stops without retry/repair/replay.
- Root, verifier, prepare/result, suffix, and init budgets are consumed. Final
  acceptance is one and unconsumed; authentication, formal/model, and
  downstream budgets remain distinct and unconsumed. Final acceptance is not
  authentication or formal/model authority. Next is independent reconstruction
  and explicit one-use direct `accept-final` authority only.

## M3S-v44 accepted root and ordered verify/prepare freeze (2026-10-15)

- The sole V44 root-only child PID `21992` exited zero after
  118.304355292 seconds within the 120-second bound, without timeout,
  truncation, or diagnostic overflow. Stdout is 704 /
  `287a25e8fc72335db0123311afdcb2f6d97683311c9add38ef4644592cb583a3`;
  stderr is empty; semantic is `M3S_V44_ROOT_ONLY` /
  `M3S_V44_READY_FOR_CONTROLLER_REVIEW`.
- The initial prelaunch outer-object comparison was a harmless read-only false
  positive: it stopped before mutation and launched nothing. Explicit
  field-by-field reconstruction and all 71 pre-root gates then passed with
  no-write proof before the sole root launch.
- Root, empty home/tmp, and receipts are uid 501 mode `0700`; files are uid
  501 mode `0600`. Driver/controller/source/writer/self-check/final index are
  538,746 / `d6d2141d37275259491ea79bbef10d12d1cd02d4152bf6505a3c273986ccf850`,
  18,147 / `c573fcdb80d07d9bd320cfd0ad0141206675b2b6ced3b34e55212ab50ba76626`,
  524 / `6ca3814d8490701e8105a021301644e139872d06bad0eebb7c247e7bc698831d`,
  72 / `2152b25df8eb1201f681037632107a92a665d81b1c9b47058ca81148930298cd`,
  7,012 / `a14df6d41caf7d062258efc873f4c666f68a4e5be842e5d4a0a1b64778f785ac`,
  and 2,000 / `1f44d31dec228076da80768ec87d493860c82bfc14248db678d2e4a1a9df6ca5`.
- Controller is accepted; source/writer/self-check PASS; self-check has 71
  gates and no-write PASS. Final index binds root argv
  `40282f063b5df17fe7f061cce4cdc3eff6ea0facc67ec54ce19e0fcf4f590e4b`.
  Candidate count is 27, delivery is 0/15/177 at
  `ef1fee17a4b12b062c30971526d6593e9957ec92084bc1805d546af2a98ed082`,
  and all three reserved results are absent.
- Two commands bind one final document generation. First is a direct
  allocation-free verifier: 25-string Python argv, 39-string clean vector,
  120/150-second driver/outer bounds, 65,536-byte diagnostics, expected
  `M3S_V44_POST_ROOT_VERIFY_PREPARE` / PASS / 71, empty stderr, and strict
  no-write/no-allocation proof. Launch consumes its one verifier budget.
- Second is a separately gated bounded-wrapper prepare: 25-string Python argv
  represented by a 17-string wrapper vector, inner/outer 2,730/2,760 seconds,
  1,048,576-byte wrapper output, and 65,536-byte diagnostics. It remains
  unauthorized until independent acceptance of verifier PASS with unchanged
  documents/protected state. PASS alone is not prepare authority.
- Prepare repeats all 71 gates before its sole optional `mktemp`; it may then
  run only materialization, overlay, dry-run, setup, 103-link proof,
  readiness, credential-free staging, doctor termination, one loop-init,
  complete trusted-record/policy/toolchain binding, preservation, and
  preacceptance sealing. Success stops at
  `M3_SUCCESSOR_PREPARATION_V44_AWAITING_CONTROLLER_ACCEPTANCE`.
- Root/root-invocation budgets are consumed. Verifier, prepare/result, suffix,
  init, final acceptance, authentication, formal, and downstream budgets are
  unconsumed. Every stop is retained with no retry/repair/replay/replacement.
  Exact command identities bind final document bytes and are reported after
  closure. Next is separately authorized verifier only.

## V43 formal stop and M3S-v44 trust-record recovery design (2026-10-15)

- The only V43 formal invocation is immutable consumed evidence: session
  `53627`, PID `80564`, chunks `3fa762` / `f69db8` / `59b1f8` / `5b5c07` /
  `8c9a69` / `13dbcf` / `75c517` / `087e07`, exit 2 after
  214.122168416 seconds, no timeout/truncation, stdout 12,992 /
  `6dccd2f0a0caa4247ea904799ae2817a23295c6ba32754601e2e3af6353c0459`,
  and stderr 29 /
  `6c061b4cc7a28f0ded4346994615b1c0f93dfb978ad9d40db3578a6196a2c822`.
- Run `20261015T231933Z-6eee7fff` in `candidate.CbYcDirN` is retained
  `blocked` at cycle/code-cycle 2/0 with null Coder session, no command
  results, and `plan repair budget exhausted`. State/events are 12,992 /
  `f61c8a6eb0eacf2e6f04a05d46f7c77d8c61565582ae7a7f913f7cc2aec02c4b`
  and 2,056 /
  `bb172c73a5bd151e2b6b71c990d388460f225ecc2ae17ae3bb1b67715cd4d4c1`.
- Planner artifacts `001` and `002` are 11,143 /
  `efd893e7287a3c78426096279e066d9ef85619f1d95e47950b03b80f7fb7465c`
  and 12,005 /
  `76b6f040f9a993a3fdd65f8519d9301aeef1a21ec66b801c88ff632f2a2f5869`;
  both are `NEEDS_INPUT`. No Coder, Reviewer, Tester, Runner, or Gateway
  artifact exists. The formal invocation may never be retried or resumed.
- Exact defect: candidate-local trusted record 3,485 /
  `698e1a6d7be3d8d886aabb3a1b8c0c326d268ef319cd3d48e5ec8ea8ef466983`
  names the older V40 blocked predecessor and lacks the complete V39 terminal
  closure, the exact expanded thirteen-path Coder allowlist, and externally
  accepted policy plus sealed-toolchain bindings. Authentication and V43
  dispatch authority do not cure this provenance gap.
- Fresh V44 derives only from sealed V43. Its new candidate-local record must
  transport complete V39 closure, immediate V43 formal stop, the exact 13
  product/test paths, and a fail-closed requirement that later external final
  acceptance bind the exact record/receipt, policy snapshot/semantic hash,
  and sealed toolchain receipt/source/snapshot fingerprints. The checked-in
  formal workflow is unchanged. The canonical complete V39 closure is 4,553
  bytes / `3f83f2dbc9c28b115fc8fd26bced888d8e1a0f877e5db3e4e3617aa487dff58f`.
- The 27 retained candidates are the exact preallocation set. Delivery is
  0/15/177 after the one new
  `tools/loop_engineering/m3s_v44_source_freeze.py`; the fixed no-replace
  `m3-successor-preparation-v44` root and all V44 results remain absent.
  Candidate-private HOME is not traversed; V43 is validated only through
  explicit accepted non-secret evidence paths.
- Derived source-freeze validation has 71 actual allocation-free gates,
  positive/current and mutation-negative trust/acceptance fixtures, exact
  command surfaces `23/23/15`, one `mktemp`, one `loop-init`, AST/compile and
  Ruff F/B/S PASS, and byte-identical no-write proof. Final source/helper/
  driver/acceptance and root-command identities are reported after document
  closure.
- Fresh root/root-invocation budgets are one and unconsumed. Prepare, suffix,
  init, final acceptance, authentication, formal, and downstream budgets are
  later and separately gated. Next safe action is independent reconstruction
  and one explicit V44 root-only authority; this cycle executes no phase.

## M3A-v6 accepted handoff and frozen V43 formal dispatch (2026-10-15)

- The sole V6 opaque handoff is independently accepted: chunk `48f286`, no
  session, exit 0, child/tool elapsed 0.485158334/0.731653875 seconds, no
  timeout/truncation, stdout 228 /
  `f4b001a39daadb9d9204ab87568af0276c84e1f46564c736576d9d016b897fdd`,
  empty stderr, semantic `M3A_V6_AUTH_HANDOFF` /
  `READY_FOR_CONTROLLER_REVIEW`.
- The exclusive eight-field sanitized receipt is 261 bytes, uid 501 mode
  `0600`, SHA-256
  `def12fc3c49b6016013291557e8b9c2171b63e97f2c0c5c6bd06556961b94bf4`;
  it records successful copy, mode `0600`, uid 501, version 1,
  `SUPPORTED_AUTHENTICATED`, V6 phase, ready result, and null sanitized error.
  No raw credential content or unsanitized metadata is inspected or exposed.
- Handoff invocation, exclusive-destination, and sanitized-result budgets are
  consumed. Authentication acceptance is not formal-role, model, test,
  engineering-acceptance, publication, or delivery authority.
- `candidate.CbYcDirN` / run `20261015T231933Z-6eee7fff` remains pristine
  received 0/0 with state/events
  `4800a39ea96cda89363b1f9f2e0dda2e7dc093a64ecb2531d98fa07f2848ee6d` /
  `63f229995c4575673e775418f520c76a4951e0a990364a35881f689e4426d79e`.
  Delivery remains 0/15/176, candidate 0/15/74, and candidate count 27.
- V43 final index is
  `a87524d4180ef07115d336b640cb4e3513ad73e92cf5a239e7ebd6e61a6b54c8`.
  Policy/trusted-context/toolchain receipts remain
  `47034cf37bd9e4dd9ce1764c909a36a692d9fee2288006105de99337d1ebd7ab` /
  `a7dfbf10610016990c08fadc091007bae24a8bc4eaa690f984d974a5a2bf3e0c` /
  `1942f05fc5686652004bb18842418ebd337d9dfaf53515319915e00a2782543d`.
- Frozen Make argv is three strings / 63 bytes /
  `bd94dffcabc59697f4720b1742404b03e668658369d077e9d7f185ccb870923a`.
  Clean vector is 12 / 499 /
  `87aed8a4f4a151221d0c8689bf62ae822fa690336fa0d62b83c51e5ac5a15d07`;
  literal envelope is 12 / 513 no-LF /
  `a9e6cf1efcc54ac0c2959a52acf63de0289c29730224c497ffc7437304155f09`;
  outer zsh argv is 4 / 538 /
  `e8751d9e0a99f3983b8303361c8ab085346d395f992685dde579775ac08a1e5c`.
- Future launch uses the accepted candidate repository and private HOME/TMPDIR,
  `/dev/null` stdin, 122,400-second outer allowance, 1,000,000-byte diagnostics,
  and unchanged cost/cycle/role/Runner/Gateway limits. Planner, Reviewer,
  Tester, and Gateway are fresh read-only sessions; Coder is the sole isolated
  writer and may resume only its exact recorded session, never `--last`.
- Formal invocation budget remains one and unconsumed. This freeze grants no
  model authority. Next action requires fresh explicit authority for exactly
  the final reported documents and envelope; every stop is retained with no
  retry, repair, replay, second invocation, or evidence reuse.

## M3A-v6 accepted root and opaque handoff freeze (2026-10-15)

- The sole V6 root-only invocation is accepted immutable evidence: chunk
  `4e4f30`, no session, exit 0, child/tool elapsed
  0.932692750/2.291795 seconds, no timeout/truncation, stdout 964 /
  `29e887bd1e92182608676ecb656d13c36074cae44a3430164d08452f9f71a508`,
  empty stderr, semantic `M3A_V6_ROOT_ONLY` /
  `M3A_V6_READY_FOR_CONTROLLER_REVIEW`, and bound argv
  `d8ee6e1a60bf0543459eeff4e771e3579c6faa26ee7de643f936a3ad3e3a0725`.
- Root/empty home/empty tmp/receipts are uid 501 mode `0700`; files are uid
  501 mode `0600`. Driver, acceptance, source, writer, self-check, and final
  index are respectively 31,499 /
  `20c4c9afcba559625b0185308eb1a88844fc78fbc2bafe4e34adf8540e041a68`,
  1,272 / `73c2c980d7b432b4c8be97ebffdb1ee36e11a683e36cb19ac77a5d24ed174ee5`,
  432 / `57d36f93936ed03cab10bacfdac250ac62c0d5f2e382c1820916deba42508aee`,
  84 / `c239260588d420779d8e22b803779a2784a468d91cab664ab062774aab923d29`,
  2,917 / `a206c1095fd58833f5fab882ecfa21f61684d4a5ea522212ecf2461e11d295ec`,
  and 475 / `6f4a9e53970769876c6576e5d84cf45295e340b8a30661905bfe4302d842faeb`.
- A first read-only postflight used a stale local filename/order expectation;
  it made no write. The corrected exact-root ordering and artifact correlation
  passed. Sanitized result remains absent; candidate/run/provenance,
  27-candidate set, delivery 0/15/176, and candidate 0/15/74 remain unchanged.
- Root/root-invocation budgets are consumed. Frozen handoff construction is
  15 driver arguments / 17 complete Python argv strings / 27 clean-vector
  strings / 27 quoted payload tokens / four outer zsh argv strings. The final
  exact counts, sizes, and hashes bind these documents and are reported after
  closure. Launch uses the accepted candidate repository, candidate-private
  HOME/TMPDIR, `/dev/null` stdin, 120-second outer and 30-second child bounds,
  4,096 sanitized stdout bytes, and 65,536 aggregate diagnostics.
- Static validation treats the sealed driver as data and invokes no handoff or
  login child. It validates exclusive no-follow creation, revalidation/fsync,
  pinned status executable, all child channels `DEVNULL`, exact eight-field
  sanitized receipt, root/V43/run/inventory/process bindings, positive and
  mutation-negative fixtures, and byte-identical no-write scope. It does not
  traverse private HOME or re-probe the private credential destination.
- Authentication content/metadata is never printed, logged, hashed,
  serialized, persisted in receipts/prompts, committed, or exposed. Handoff,
  exclusive-destination, and sanitized-result budgets remain one each and
  unconsumed; every stop is retained with no retry/repair/replay/replacement.
  Formal-loop/model authority remains distinct and unconsumed.
- Next action is independent reconstruction and fresh explicit one-time
  credential authority for exactly the reported V6 opaque envelope. No
  handoff, login, model, role, test, render, evaluation, publication, commit,
  cleanup, media mutation, `--last`, or resume action runs in this cycle.

## M3A-v6 source freeze and root-only design (2026-10-15)

- Fresh fixed no-replace `m3-authentication-handoff-v6` is bound only to
  accepted V43 `candidate.CbYcDirN` / run `20261015T231933Z-6eee7fff`, final
  index `a87524d4180ef07115d336b640cb4e3513ad73e92cf5a239e7ebd6e61a6b54c8`,
  completed tree `268729fa276c2a400bcbabf881491b534ab81926b572a94b080675fc266ceaa3`,
  exact 27 candidates, pristine state/events, final delivery 0/15/176, and
  candidate 0/15/74.
- Trusted Main adds only `tools/loop_engineering/m3a_v6_source_freeze.py` plus
  the two authoritative documents. Helper is 66,201 /
  `7f0ca4c5e13553bee6e02066cb71ae0980bcc4b47233c76889897e1555eaa603`; embedded source 919 /
  `5995ef8f4eac4f8376b2a8771c49c5a4eb58b6a2c29499be34dc3aad6d345bd2`; derived driver 31,499 /
  `20c4c9afcba559625b0185308eb1a88844fc78fbc2bafe4e34adf8540e041a68`; contract 3,594 /
  `ab21ae549b4a6437f0b0ba6f4911d19b074c6c8222510b4e0ce69a8305baf35b`.
- Immutable M3A-v5 remains consumed historical precedent only. Static checks
  bind its accepted helper/root/result and prove its sealed driver cannot name
  the V43 candidate/run. V5 phases, receipt names, candidate/run, inventories,
  destination policy, and authority are negative fixtures; no root/HOME/result
  or credential authority transfers.
- Root-only is strictly credential-blind and no-replace. It may create only the
  fixed private root, derived driver, empty private home/tmp, controller
  acceptance, source receipt, writer self-test, self-check, and final index.
  Sanitized result and destination remain absent. It never launches login
  status or accesses authentication content/metadata.
- The later handoff alone, after separate root acceptance, command freeze, and
  fresh operator authority, may use exclusive opaque no-follow copy,
  revalidation/fsync, pinned login status with all child channels DEVNULL, and
  one exact eight-field sanitized receipt. Authentication success is not
  formal-loop/model authority.
- Frozen root-only construction is 18 helper arguments / 22 complete Python
  argv strings / 32 direct-vector strings / 32 quoted payload tokens / four
  outer zsh argv strings. Exact sizes/hashes bind final document bytes and are
  reported after closure. Cwd is immutable seed repo, stdin `/dev/null`, outer
  bound 120 seconds, diagnostics 65,536 bytes, exact eight-name environment.
- Full static validation has 32 named gates and a byte-identical bounded
  pre/post non-secret snapshot. V6 root/result stay absent. No root/handoff,
  authentication, model, role, test, render, evaluation, publication, commit,
  cleanup, media mutation, `--last`, or resume action runs.
- Next safe boundary is independent reconstruction and one exact V6 root-only
  authority. Actual credential authority remains later and separate.


## Accepted V43 final provenance and M3A-v6 design boundary (2026-10-15)

- The sole V43 final-controller-acceptance invocation is accepted immutable
  evidence: session `17146`, chunks `ae052e` / `35ae02`, exit `0`, observed
  wait `5.631896708` seconds, no timeout/truncation, stdout 751 /
  `1a38c6649ac09ee5073abd77734f2f71499cb1db456c994c27e091a21d4c8376`,
  empty stderr, and semantic
  `M3S_V43_FINAL_CONTROLLER_ACCEPTANCE` /
  `M3S_V43_FINAL_PROVENANCE_READY_FOR_CONTROLLER_REVIEW`.
- Five uid-501 mode-`0600` outputs independently revalidate: final acceptance
  3,913 / `8e92f8d63142313e70be4a15add0538e0e13a9e406cfcfc6f7e792ab5682a42a`;
  transport 1,383 /
  `d5b3b0dd6c66bff23aac430f4a9400c8ce7180c85d927ba72d82cdf38973ee72`;
  repository manifest 6,146,002 /
  `cdf949a84656807f9a538fca3d9fe45647a7fcf26246c651fd8db3a85a9e596e`;
  attempt manifest 12,183,981 /
  `d657dd1f513b3a982fef52517355f845cbc7d6b135700d481e12b5b29ec45031`;
  final index 2,731 /
  `a87524d4180ef07115d336b640cb4e3513ad73e92cf5a239e7ebd6e61a6b54c8`.
- Index/manifest reconstruction passes: repository 27,442 paths /
  581,374,873 regular bytes; pre-index attempt 44,353 / 955,550,191;
  completed tree 44,355 / 967,736,903 /
  `268729fa276c2a400bcbabf881491b534ab81926b572a94b080675fc266ceaa3`.
  Receipt count is 42; transport is PASS with
  `secret_material_accessed: false`.
- Candidate `candidate.CbYcDirN` / run `20261015T231933Z-6eee7fff` remains
  pristine received 0/0. State/events remain 12,796 /
  `4800a39ea96cda89363b1f9f2e0dda2e7dc093a64ecb2531d98fa07f2848ee6d`
  and 144 /
  `63f229995c4575673e775418f520c76a4951e0a990364a35881f689e4426d79e`.
  Delivery is 0/15/175 at
  `44ab43dbcd3279f949014f9c6aad751ae122313d2067375419daba9a18f4c8a2`;
  candidate is 0/15/74 at
  `4270aac58c82d5b1e74ae0412cd36622869c9b2385281a67ec507007d0a3744e`;
  candidate count is 27. Root final-controller and auth results remain absent.
- Root through final-acceptance and all five destination budgets are consumed
  and non-reusable. Authentication, formal-loop, and downstream budgets remain
  unconsumed and unauthorized.
- Fail-closed gap: accepted M3A-v5 is hard-bound to V40,
  `candidate.M4v94Rmv`, run `20261014T214746Z-cd5796b8`, and 24 candidates;
  all of its root/handoff/result/destination budgets are consumed. No V43-
  bound authentication root or sealed driver exists. Therefore an exact
  executable V43 handoff envelope cannot safely be frozen now and is recorded
  as `BLOCKED_FRESH_M3A_V6_ROOT_REQUIRED`, not silently mapped to V5.
- Fresh design is fixed absent no-replace `m3-authentication-handoff-v6`, bound
  only to accepted V43 final provenance, candidate/run, exact 27 candidates,
  pristine state/events, main/HEAD, 0/15/175 and 0/15/74 inventories, and all
  accepted policy/toolchain/trusted-context/requirement/architecture evidence.
  Root-only remains strictly credential-blind and may create only a private
  driver, empty home/tmp, controller acceptance, and supporting root receipts.
- A later accepted V6 driver must preserve the checked-in opaque no-follow
  exclusive-copy, source revalidation/fsync, pinned login-status DEVNULL child,
  termination, and exact eight-field sanitized-receipt pattern. Authentication
  content and metadata must never be observed, printed, logged, hashed,
  serialized, committed, or exposed. Root, handoff, result, and destination
  budgets are one each with retain/no-retry/no-reuse semantics.
- Static validation re-hashed and parsed only non-secret evidence, rebuilt the
  completed-tree digest from sealed manifest records, checked pristine state,
  inventories, candidate set and absences, and did not traverse private HOME
  or access either authentication location. No helper/source defect was found;
  no helper changed.
- Next safe action is a separately authorized M3A-v6 source-freeze/root-only-
  design cycle. It must freeze a credential-blind root-only command and stop
  before root creation. Only after independent root acceptance may a later
  documentation cycle freeze an actual handoff envelope for fresh one-time
  credential authority. Formal-loop/model authority remains separate.

## M3S-v43 accepted preparation and frozen final acceptance (2026-10-15)

- The sole V43 prepare is accepted immutable evidence: session `26299`,
  chunks `ae6956` / `0fa89e` / `56f4fc` / `e39710` / `e1255e` / `12aaa8` /
  `d40300` / `1c6733` / `f7975f` / `b3a722`, wrapper return 0, elapsed
  282.322084 seconds, and no timeout/truncation/wrapper error. Root result is
  23,850 / `7c2cf6fe2bff1be5a6369f79aae65ae85c2e96046d4335d77241c92fc4e8b7b3`;
  embedded output is 20,477 /
  `6103dcb2b71f436fff0c9ec926f8507d1d0db1e3fdd46350bd559ce3cfcf8d0d`.
- Sole candidate `candidate.CbYcDirN` and run
  `20261015T231933Z-6eee7fff` are sealed. Run is pristine `received` 0/0;
  state/events are 12,796 /
  `4800a39ea96cda89363b1f9f2e0dda2e7dc093a64ecb2531d98fa07f2848ee6d`
  and 144 / `63f229995c4575673e775418f520c76a4951e0a990364a35881f689e4426d79e`.
  Candidate count is 27; candidate inventory is 0/15/74 /
  `4270aac58c82d5b1e74ae0412cd36622869c9b2385281a67ec507007d0a3744e`.
- Every frozen stage passed, including setup rc0, exact 103 safe/zero unsafe
  links, readiness, credential-free profile staging, terminated doctor,
  loop-init rc0, bindings, offer, preservation, and sealing. Final index is
  18,095 / `fc54928088059a084f0c998bac7b96addca4713b7c2d41c6cc13eb0c3477b0d3`;
  completed tree is 44,350 paths / 949,398,893 bytes /
  `a336c3852a28e6c533d6675cc1d2c88aecddec9758747e18f720aafd0c8968eb`.
- Receipt counting is explicitly corrected: 38 files means 37 pre-index
  entries plus the final index. The earlier candidate-inventory assumption of
  73 ordinary untracked paths is corrected to the actual 74. Both read-only
  checks failed closed and made no mutation.
- Delivery remains 0/15/175 /
  `44ab43dbcd3279f949014f9c6aad751ae122313d2067375419daba9a18f4c8a2`.
  Prepare result/invocation, suffix, and init budgets are consumed. Root final
  and auth results and all five candidate-side final-acceptance destinations
  remain absent; final acceptance/auth/formal/downstream budgets are unconsumed.
- Canonical external acceptance is 3,912 bytes without LF /
  `3b59973c87b3bc51adef2391b224a458b136caa2db69687ee13649c0d77e6f29`;
  transported form is 3,913 /
  `8e92f8d63142313e70be4a15add0538e0e13a9e406cfcfc6f7e792ab5682a42a`.
  It binds offer 5,032 /
  `95c783319e2f11b2b666d40a93e36ffdba3a484f38ddcc5b8075b9a24615ff48`.
- Frozen direct `accept-final` is 17 argv strings inside a 32-string clean
  vector, candidate-repo cwd, seed `CANDIDATE_REPO`, `/dev/null` stdin,
  120-second driver/outer limits, and 65,536-byte diagnostics. It may create
  only five no-replace candidate-side provenance files and must stop at
  `M3S_V43_FINAL_PROVENANCE_READY_FOR_CONTROLLER_REVIEW`; the root result stays
  absent. Exact identities are reported after final document closure.
- Any stop is retained; no retry/repair/replay/delete/replace/cleanup/reuse.
  Next safe action is independent reconstruction and explicit authority for
  exactly one direct final acceptance. No acceptance/auth/loop/role/model/test/
  render/evaluation/publication/commit/media action executes in this cycle.

## M3S-v43 accepted root and frozen ordered commands (2026-10-15)

- The first/only V43 root-only invocation is accepted immutable evidence:
  session `70445`, chunks `5b9ef3` / `47e257` / `4961fb` / `462df5`, exit 0,
  cumulative observed wait 98.884386624 seconds, no timeout/truncation, stdout
  704 / `3f06c93e92b8765a945d407794eafd53af39c84d56dcf727c6d55d28a7d2d2da`,
  empty stderr, phase/result `M3S_V43_ROOT_ONLY` /
  `M3S_V43_READY_FOR_CONTROLLER_REVIEW`.
- Root/empty home/empty tmp/receipts are uid 501 mode `0700`; files are uid
  501 mode `0600`. Driver, controller, source, writer, self-check, final index
  are 517,933 /
  `fa0f4340fdc5ae7093b807bd43c17d3f9a8c4f8efbe1f0bd57a249bee87814bc`,
  17,249 / `b0ac531ff708d8c117e10efc79e1caa33925c4608a93dbd267e9f665654cde05`,
  524 / `11208485b7c4184eafd32e380080c9efc001cbaaa67ccec7962695e873cbb405`,
  72 / `847b63ac13ae5f1ccae504fe9f244ded36253e9f30a261f34509f38a8f9d69f2`,
  6,546 / `47d7a55206b83e77f0f25871e674904be1a322801f8a1e8a6d0c94b02d31e05f`,
  and 2,000 / `dc1cfdd133dc05e8d197ddc61c653e43e7e8326c9ea920574d26465f3b66e4e4`.
- Controller acceptance is accepted before root creation; source/writer/
  self-check are PASS with all 69 gates and no-write PASS. Final index binds
  root argv `a8cde39cd35c059ce8190f1aba78a0f71c649a32d8cf9909fd563ae8195ead34`.
  Candidate count is 26, delivery is 0/15/175, git-status digest is
  `44ab43dbcd3279f949014f9c6aad751ae122313d2067375419daba9a18f4c8a2`,
  and all three reserved V43 results are absent. Only root budget is consumed.
- Two separately authorized commands are frozen against one final document
  generation. First is a direct allocation-free verifier: 25-string Python
  argv inside a 39-string clean vector, 120/150-second bounds, 65,536-byte
  diagnostics, expected `M3S_V43_POST_ROOT_VERIFY_PREPARE` / PASS / 69,
  empty stderr, and strict no-write/no-allocation proof. Its launch consumes
  its verifier budget and any non-PASS stops permanently.
- Second is a separately gated bounded-wrapper prepare: 25-string Python argv
  inside a 17-string clean vector, 2,730/2,760-second bounds,
  1,048,576/65,536-byte output/diagnostic ceilings, exclusive result, sole
  suffix and loop-init budgets, exact 26-predecessor set, credential omission,
  setup, repaired 103-link/zero-unsafe return, readiness, doctor, preservation,
  sealing, and expected
  `M3_SUCCESSOR_PREPARATION_V43_AWAITING_CONTROLLER_ACCEPTANCE` stop.
- No document or protected byte may change between independently accepted
  verifier PASS and prepare launch. Verifier PASS is not prepare authority.
  Every stop is retained; no retry/repair/replay/cleanup/reuse. Final command
  identities are reported after document closure. The unchanged accepted V43
  helper remains 48,825 /
  `482f3266f0d4775114dd4c496733470b3bf9839bda61a635b96ab810a4f60750`.
- Next safe action is independent reconstruction and explicit authorization
  for exactly one verifier. No verifier/prepare/result/allocation/authentication/
  role/model/test/render/evaluation/publication/commit/cleanup/media mutation,
  `--last`, or `resume_liveclip.sh` executes in this cycle.

## M3S-v42 retained stop and M3S-v43 root-only freeze (2026-10-15)

- The sole V42 prepare is retained immutable evidence: session `20858`,
  chunks `422de7` / `062e03` / `c9c7d2` / `c955ef` / `99ab74`, outer exit 1,
  bounded elapsed 150.497624 seconds, and no timeout, truncation, wrapper
  error, inner session, or credential variable. Result is 14,080 /
  `ce8653e0ea2e02ef939ee78f3b70c219a2b71e907f2b0497bfd73805760037e3`;
  embedded output is 11,277 /
  `48ac90753f925c5cd435f64de56768ab32bff839c8c43803be37547ef43c2e95`.
- The sole suffix is `candidate.bm4AWiof`; candidate count is 26. Its exact
  entries are home/repo/successor-receipts/tmp, inventory 0/15/73, empty home,
  tmp containing only empty `uv-3cd09864a7d8cfb8.lock`, and no initialized
  run. Setup rc0 preceded exact `NameError: name 'links' is not defined`.
  Result/invocation and suffix are consumed; init is unconsumed and abandoned.
- V42 sealing completed without error: stop 237 /
  `b335a72c09c857106357971bbab488da567308ae82899fa2672ce4b33ecdf76c`,
  preservation 354,764 /
  `3556b249e86cff09850a79618f5efa0357a8b476b910a65031b88a55da429248`,
  final index 8,600 /
  `39f2f0e96809c48404397fbae63b99b2c23b3a7829b47666c1483ef140de9f45`.
  Final repository is 27,431 paths / 581,307,836 bytes /
  `f21f0934386666ebc6d539af6a03498370f37a010f5ff81af254afb9d89a94d9`;
  final attempt 27,453 / 589,653,763 /
  `0874bfc3b63c7f7fff53aa6b58f0e7192dd24b43ee25851ae6d14dc1d42e3a7c`;
  completed tree 27,455 / 595,947,585 /
  `622981626b1c22e4f86f9d83a125ade10101c9973aba3f19f65626eed5406357`.
- Diagnosis is exact: V42 assigns the valid `link_safety` model, then returns
  `len(links)` although `links` is undefined. V43 returns only the validated
  model's link count. Runtime-equivalent positive and negative fixtures retain
  exact 103 links / zero unsafe links and AST validation proves the executed
  return has no undefined `links` load.
- V43 derives only from sealed V42 driver 501,094 /
  `6a09e8e515338714e5477c094aa083b9a6f32bd7303a272eaf1965857a5d7a30`,
  binds the full V42 root/result/candidate/sealing closure, and adds
  `candidate.bm4AWiof` as the 26th predecessor with zero protected omission.
  Earlier baselines and omit-before-access rules remain exact.
- Active/current/future metadata is V43/V43/V44. Fixed no-replace
  `m3-successor-preparation-v43` is absent. Final delivery inventory is
  0 staged / 15 modified tracked / 175 ordinary untracked after the one new
  helper. The complete allocation-free pre-root graph has 69 gates and strict
  no-write proof. All V43 budgets are fresh and unconsumed; all V42 budgets and
  evidence are permanently non-reusable.
- Next safe action: independent reconstruction and explicit authority for one
  frozen credential-free V43 root-only invocation. No root execution,
  verifier, prepare, allocation, setup, authentication, role/model, product
  test, render, evaluation, publication, commit, cleanup, media mutation,
  `--last`, or `resume_liveclip.sh` is authorized here.

## M3S-v42 accepted root and frozen ordered commands (2026-10-15)

- The first/only V42 root-only invocation is accepted immutable evidence:
  session `1783`, chunks `a2135e` / `410830` / `e72548` / `35d431`, exit
  `0`, cumulative observed wait `114.983594625` seconds, no timeout or
  truncation, stdout 704 /
  `ed75dc05deb02518be05e29ac27dec5bf21978499fc213b309cf123845f6eb74`,
  and empty stderr. Phase/result is `M3S_V42_ROOT_ONLY` /
  `M3S_V42_READY_FOR_CONTROLLER_REVIEW`.
- Root/empty `home`/empty `tmp`/`receipts` are uid 501 mode `0700`; files are
  uid 501 mode `0600`. Driver/controller/source/writer/self-check/final-index
  are 501,094 /
  `6a09e8e515338714e5477c094aa083b9a6f32bd7303a272eaf1965857a5d7a30`,
  17,037 / `e0da374d8508dc74935b8043b87823cf3eff4b6c800c9264bd4018ae7ab06ccc`,
  524 / `57695cf4dee9c8b1a5c47916b6dcbc7e810cbb36f03b91bab6a30cd6034f9a27`,
  72 / `be8914d7ed140c49e85c7eb35910e83a3606a0021232acdf4e631fdec155b31c`,
  6,139 / `0bfc013a4979caf37d8e4e3610fba36eb2dbc5945479f98bb89f16b8d49a6f72`,
  and 2,000 / `ea9ef09aaafa0ca2cca584b864fc67bd14984ebd05c5ac1bd57b41c3d0a2dcbc`.
- Controller acceptance is `ACCEPTED_BEFORE_ROOT_CREATION`; source/writer/
  self-check are PASS, including the 67-gate no-write audit; final verdict is
  ready for controller review and binds root argv
  `61a9fd067aa7300abab07d8e7c7ea7893dcdd28d8776b3023e40964bbbe03d70`.
  All three results remain absent. Candidate count is 25; delivery is
  0 staged / 15 modified tracked / 174 ordinary untracked. Only the root
  invocation/root budget is consumed.
- Two commands are frozen against the same final documents. First is one
  allocation-free direct `verify-prepare`: 25-string Python argv inside a
  39-string clean vector, 120/150-second driver/outer bounds, 65,536-byte
  diagnostics, expected sole stdout phase/result/gates
  `M3S_V42_POST_ROOT_VERIFY_PREPARE` / PASS / 67, and strict no-write proof.
- Second is a separately authorized bounded-wrapper `prepare`: 25-string
  Python argv inside a 17-string wrapper vector, 2,730/2,760-second bounds,
  1,048,576/65,536-byte output/diagnostic ceilings, no-replace result, one
  suffix, one init, and only the frozen path through repaired 103-link
  post-setup safety and
  `M3_SUCCESSOR_PREPARATION_V42_AWAITING_CONTROLLER_ACCEPTANCE`.
- No documentation or protected-state byte may change between independently
  accepted verifier PASS and prepare launch. Verifier PASS is not prepare
  authority. Non-PASS consumes verifier authority and stops permanently;
  every preparation stop is retained and never repaired, retried, replayed,
  cleaned, or reused.
- Exact final document and command identities are reported only after the
  self-hashed documents close. Next safe boundary is independent controller
  reconstruction and explicit authority for the allocation-free verifier.
  No verifier, prepare, result, allocation, authentication, role/model, test,
  service, render, evaluation, inference, publication, commit, push, cleanup,
  media mutation, `--last`, or `resume_liveclip.sh` action occurs here.

## M3S-v41 retained stop and M3S-v42 root-only freeze (2026-10-15)

- The sole V41 prepare is closed immutable evidence: tool session `47430`,
  child PID `89647`, outer exit `1` after `134.5885662920191` seconds;
  wrapper elapsed `134.507742`, return `1`, no timeout/truncation/wrapper
  error/session/credential variables. Root result is 14,087 /
  `d9d279485b1e12307a2efb34a4262734ed2ceb3b4cf441554a43a1975a0a78f1`;
  embedded output is 11,284 /
  `8ee9276504d8ed400b09fdd4020c53a21d8db504505d838df71f11ac670d7c23`.
- Exactly `candidate.CrvNTqvL` was allocated; candidate count is 25. Setup
  returned zero, then execution stopped before readiness with exact
  `RuntimeError: post-setup link safety mismatch`. No run/offer/profile/
  doctor/loop-init/auth/role exists. Result/invocation and suffix are consumed;
  init and every later budget are unconsumed and abandoned for V41.
- Stop, preservation, and final index are respectively 244 /
  `d26e2d965748b830eb3b3d5ce3178b2f038d30ff5c658c46e6bb1916a7983c30`,
  340,852 /
  `e569c90f1dc3cd742c4696444f41faa38af51ac5fe8be3b02f58103f8e5f5834`,
  and 8,600 /
  `6b2096059aab2506a6340151aa63226265856a6279cbb6f04a6d345ce0ffa7c3`.
  Sealing completed without error. Final repository/attempt manifests are
  6,143,897 /
  `4a20ee5f097ed5d7b9737bcfd8da54fef87ebe63d5685d0f7c889deae3e92b33`
  and 6,285,222 /
  `45cb27122eef1a211b2c63b3c11893dc4ce5fd5231bbff94a0fe6c32d42f5455`;
  completed tree is 27,455 paths / 595,892,935 bytes /
  `2d1e5cad4ee1094bd0a311a58a01dfb8f196afb15546a2cfa2eda9f78aeb82ee`.
- Diagnosis is exact: all 103 retained post-setup symlinks resolve internally
  and unsafe count is zero, but sealed V41 hard-codes 102. Canonical link
  evidence is 13,353 /
  `c7fb588e00d8dea1a960e917fa500f489ded954ca92d64c5badac26ea811fa6c`.
  V42 changes only the expected cardinality to 103 and retains fail-closed
  broken/external rejection. Actual-103 positive and 102/104/broken/external
  negatives are mandatory.
- Fresh V42 derives only from sealed V41, binds the complete V41 stop as the
  25th predecessor, rolls active/current/future metadata to V42/V42/V43, and
  preserves exact v2/v3 transport, credential omission before metadata,
  architecture, candidate-set, one-mktemp/one-loop-init, final-acceptance,
  policy/toolchain, one-writer, retention, and all excluded boundaries.
- Only this file, the Living ExecPlan, and new
  `tools/loop_engineering/m3s_v42_source_freeze.py` change. Final delivery
  inventory is 0 staged / 15 modified tracked / 174 ordinary untracked; the
  fixed V42 root is absent. The full actual pre-root graph must pass 67 gates
  and no-write proof against final documents before any root authorization.
- The next single safe action is independent reconstruction and explicit
  authority for exactly one V42 root-only envelope: immutable B2 cwd,
  `/dev/null`, exact eight-name credential-free environment, 120-second outer
  and 65,536-byte diagnostic bounds. No V42 root/phase, setup, allocation,
  credential access, role/model, product test, render/evaluation, commit,
  push, cleanup, media, `--last`, or `resume_liveclip.sh` action occurs here.

## M3S-v41 accepted root and frozen ordered commands (2026-10-15)

- The first/only V41 root-only invocation is accepted immutable evidence:
  session `54003`, child exit `0`, wall `100.08565725001972` seconds, no
  timeout/truncation, stdout 704 /
  `e93f942fec31fe124dc2288799b8688aaac1deba31d960c2d3f44bf2357bd1d5`,
  and empty stderr. Phase/result is `M3S_V41_ROOT_ONLY` /
  `M3S_V41_READY_FOR_CONTROLLER_REVIEW`; no chunk identifier was exposed.
- Root/empty `home`/empty `tmp`/`receipts` are uid 501 mode `0700`; files are
  uid 501 mode `0600`. Driver/controller/source/writer/self-check/final-index
  are 484,708 /
  `b9dfd77aefd9091fada40f246ff9ebf0b6b650806ed7fcc1a45db5f7701f9fce`,
  17,682 / `07160e7ef979492bf15301563593561218b0dbb1bec8b471fd105966329fc5c1`,
  524 / `5c1ff4f51b09be4ef18db25a4d0defe5f4ab5d4b97a1a5ef3d7ec16af7c49640`,
  72 / `0dc3d6b2af9cf305c70c42a66136561b5147db08dbdb3f7675e5d7acb12eab3c`,
  5,822 / `89622c704c0ce42781d1e0fe1ea993aa2b2bfaecdda44d0c5207280285701f0d`,
  and 2,000 / `435e742ed77c1efdb7b48d79684d4f2cbaaa90aabc2604953755dfb2cd806e7a`.
- Controller acceptance is `ACCEPTED_BEFORE_ROOT_CREATION`; source/writer/
  self-check are PASS; final verdict is ready for controller review and binds
  root argv `0b96cf9b7d1afdf7470704b5e792cb9fc2f67d405df59407eb709f5d3288c0fd`.
  All three results remain absent. Candidate count is 24; delivery is
  0 staged / 15 modified tracked / 173 ordinary untracked. Only the root
  budget is consumed.
- Two commands are frozen against the same final documents. First is one
  allocation-free direct `verify-prepare`: 25-string Python argv inside a
  39-string clean vector, 120/150-second driver/outer bounds, 65,536-byte
  diagnostics, expected sole stdout phase/result/gates
  `M3S_V41_POST_ROOT_VERIFY_PREPARE` / PASS / 65, and strict no-write proof.
- Second is a separately authorized bounded-wrapper `prepare`: 25-string
  Python argv inside a 17-string wrapper vector, 2,730/2,760-second bounds,
  1,048,576/65,536-byte output/diagnostic ceilings, no-replace result, one
  suffix, one init, and only the frozen preparation path through
  `M3_SUCCESSOR_PREPARATION_V41_AWAITING_CONTROLLER_ACCEPTANCE`.
- No document or protected-state byte may change between independently
  accepted verifier PASS and prepare launch. Verifier PASS is not prepare
  authority. Non-PASS consumes verifier authority and stops permanently;
  every preparation stop is retained and never repaired, retried, replayed,
  cleaned, or reused.
- Exact final document and command identities are reported only after the
  self-hashed documents close. Next safe boundary is independent controller
  reconstruction and explicit authority for the allocation-free verifier.
  No verifier, prepare, result, allocation, authentication, role/model, test,
  service, render, evaluation, inference, publication, commit, push, cleanup,
  media mutation, `--last`, or `resume_liveclip.sh` action occurs here.

## V40 formal stop and M3S-v41 transport-repair freeze (2026-10-15)

- The single official V40 formal invocation is retained immutable failure
  evidence: session `26870`, chunks `d138f9` / `74521f` / `70e508`, exit `2`,
  observed wait `55.441192876` seconds, no timeout/truncation. Run
  `20261014T214746Z-cd5796b8` is blocked at 2/0 with null Coder session,
  empty command results, and `plan repair budget exhausted`.
- State/events are 12,992 /
  `ad2ddb96e257db00f419a8a4d6148e54b13df8842062f8ab439c50cc62f8ae9c`
  and 2,056 /
  `53917898bb2fecf7f5a3babd430ec18d9ed4236bd9aea28e5e8c3eed8e3f2bfc`.
  Planner 001/002 are `NEEDS_INPUT`, 4,418 /
  `e97a67e300d07fc501e02a343fd4f8ef48f45d03b92af926c3b32f190228a015`
  and 3,840 /
  `c09ff7eeed6da18e09101cd07b79156a9c64e34f0f29fdc758706228b0a7be69`.
  No Coder, Reviewer, Tester, Runner, Gateway, or product edit exists.
- Root cause is exact source-transport omission. Trusted Main has the
  authoritative v2 requirement at 8,771 /
  `31e967e04b3f9987e5c0a9ac00b809c215aed543f9da035c3a06e73ebc976400`;
  v3 is 12,289 /
  `308fdc96f2c5ddaffb6d01c65ddc089958a5ba883ab2c00c986da38d5483ba00`
  and binds v2. Immutable B2 omitted both; V40 overlaid only v3; its overlay
  and postacceptance manifests therefore omit v2. Both Planners correctly
  stopped. No requirement bytes were fabricated or edited.
- Fresh V41 is derived only from sealed V40. Its repaired overlay transports
  exact v2 and v3 bytes and rejects omission, substitution, hash drift, or an
  extra path. Expected source counts are 2,324 records / 73 ordinary
  untracked before trusted context and 2,325 / 74 afterward.
- `candidate.M4v94Rmv` and its run are immutable 24th predecessor evidence.
  Its credential-blind baseline is 44,420 paths / 968,624,315 regular bytes /
  `ea61d5daf2332341515b66f08782d313809bbdbe92b9dded693485003be73b9a`
  with one protected omission before metadata/content access. Candidate
  inventory remains 0/15/73; candidate count is 24.
- Only `docs/exec-plans/liveclip-agent-runtime-v2.md`, `STATUS.md`, and new
  Trusted-Main helper `tools/loop_engineering/m3s_v41_source_freeze.py` change.
  Delivery inventory is 0 staged / 15 modified tracked / 173 ordinary
  untracked. The fixed V41 root and all V41 results are absent.
- The complete actual V41 pre-root graph must pass 65 allocation-free gates
  with a no-write snapshot before any root `mkdir`. It binds final documents,
  architecture, exact requirements, all 24 candidates, V40 root/preparation/
  final/auth/formal closure, both Planners, historical evidence, process,
  Python/uv/seed, contracts, phase fixtures, and one-mktemp/one-loop-init
  structure.
- The root-only argv has 18 strings; the clean vector and literal envelope
  have 28 tokens with exact eight-name environment. Outer launch is non-login
  `/bin/zsh -f -c`, immutable B2 seed cwd, `/dev/null`, 120 seconds, and
  65,536 diagnostics bytes. Exact identities are reported after document
  closure.
- Next safe boundary: independent controller reconstruction and explicit
  authority for exactly one no-replace V41 root-only invocation. No root,
  result, suffix, candidate, run, credential access, model/role, product test,
  service, render, evaluation, inference, publication, commit, push, cleanup,
  media mutation, `--last`, or `resume_liveclip.sh` action occurs here.

## M3A-v5 accepted authentication and frozen V40 formal boundary (2026-10-14)

- The sole opaque V5 handoff is accepted immutable evidence: no session, chunk
  `84eb9c`, exit `0`, wall `0.666772417` seconds, no timeout/truncation, stdout
  228 / `d0cd306e08f706aad7973815e625ba66353e185e686e9821497256167bec46c4`,
  and empty stderr. The exclusive sanitized receipt is uid 501 mode `0600`,
  261 bytes / `24f0729ab014db86903430394aee6927163063f164ab40d5481fc76cb088ece0`;
  it reports copy success, destination mode `0600`, owner uid 501, format 1,
  `SUPPORTED_AUTHENTICATED`, phase `M3A_V5_AUTH_HANDOFF`, result
  `READY_FOR_CONTROLLER_REVIEW`, and null sanitized error.
- Handoff invocation/result/destination budgets are consumed. Raw credential
  bytes and raw or secret-derived metadata remain opaque and excluded from
  logs, hashes, receipts, prompts, argv, environments, commits, and reports.
  Authentication success is not formal-role, model-inference, engineering-
  acceptance, or publication authority.
- Candidate `candidate.M4v94Rmv` and run
  `20261014T214746Z-cd5796b8` remain pristine `received` at 0/0 with null
  Coder/error and empty artifacts/results. State/events remain 12,796 /
  `3a5517a757be71d40566e5175576b200cef65da8c4b0184e75d6ff880a159ed8`
  and 144 /
  `f1a5ec47ed1051af8f64e2fdf0c105881b6a733c63bbfeedde0bf273e21285a8`.
  Candidate count is 24; delivery is main at
  `2f361fcddc0e63ae62ee62826e27b54bb8204c53`, 0/15/172; candidate is
  0/15/73.
- V40 final acceptance/postacceptance index, policy, trusted-context, and
  toolchain receipts remain respectively
  `a44929f89fca9629b06163814c8c1233278f830036c343c52e11fd4b1ea22a3e`,
  `2668171e0b0c22f2022793c4413b359b3dd31282bc3fbbe1ac413665a647b7b6`,
  `5a6b03c002f64e01266e94ebc2724e4e625fde7f6a5144e0c1d1e91ac32ca7c1`,
  `664402f3791b17c88bcd6ea9e4f3cba59eec5e319e11e5514f8717c1fd1f3bca`,
  and `f4e33b7d885e68d62efb0704c6abb47d38d15a396352b187f94ceb2139f91651`.
- The unlaunched official argv is exactly three strings, 63 canonical JSON
  bytes / `b25b1c349997da1741c666a76a23234c4b67f6c42279bed15ac2fcef5afc75f0`.
  Its 12-string clean vector is 499 bytes /
  `206a97eef84df82a9d78d7a48c7bde7ac490cbb695388c16e5a3d27dbaab6674`;
  its 12-token literal envelope is 513 bytes without LF /
  `aaccf085d0ea3d55a4adbc5913c4fc35e15eb8af59bb3722cd6197dd89198574`;
  its four-string outer zsh argv is 538 bytes /
  `a3e9f544e5173a7b960e17e3ddb0df1239d5ca802ee2899b560343e85af0170f`.
- The command uses the candidate repository, candidate-private HOME/TMPDIR,
  `/dev/null`, a 122,400-second outer allowance, and a 1,000,000-byte
  diagnostic ceiling. Existing limits remain two Planner cycles, three Coder
  cycles, 131,072 requirement bytes, 1,000,000 role/log bytes, 3,600 seconds
  per role, and fixed Runner timeouts 900/900/2,400/300 seconds.
- A future dispatch must revalidate final closed documents, V40 provenance,
  the sealed V5 root/sanitized result, pristine run, policy/trusted-context/
  toolchain evidence, architecture, branch/HEAD, inventories, candidate set,
  exact launch identities, and absence of prohibited processes. Fresh read-
  only Planner/Reviewer/Tester/Gateway, sole isolated Coder with only its exact
  recorded session, fixed Runner, evidence correlation, no `--last`, one
  writer, and trusted CAS gating remain mandatory.
- The prior authority for `candidate.oivrdV6U` / run
  `20261014T191719Z-0802b465` was consumed and does not transfer. The current
  formal invocation budget remains one and unconsumed; any future launch
  consumes it and every stop is retained without retry, repair, or replay.
- Next action: fresh explicit operator authority for exactly the reported V40
  loop envelope. This cycle launches no model, role, Runner, Gateway, test,
  service, render, evaluation, inference, publication, commit, push, cleanup,
  `--last`, or `resume_liveclip.sh` action.

## M3A-v5 accepted root and opaque handoff freeze (2026-10-14)

- The first/only V5 root-only invocation is accepted immutable evidence: no
  session, chunk `d6dbae`, exit `0`, wall `1.727236125` seconds, no timeout or
  truncation, stdout 964 /
  `a69244c4b76deb3bb433cc82b87255148d3eadb008eb3b13cb6c478f3f1e243f`,
  and empty stderr. Phase/result is `M3A_V5_ROOT_ONLY` /
  `M3A_V5_READY_FOR_CONTROLLER_REVIEW`.
- Root/empty home/empty tmp/receipts are uid 501 mode `0700`; files are uid
  501 mode `0600`. Driver/controller/source/writer/self-check/final-index are
  31,335 / `8dc670fa2aca566f9107d51b0e291f8a7e6dc18ec7d45c30d0cab8b3869b506d`,
  1,295 / `e4067945105daa5413d1e2af72cdcd1598e1c59939487c9e4b688922dae0790b`,
  432 / `b6e12b972cf04d8158dfd985107a56b09b7d3140b916801dc6c4728e79db243d`,
  84 / `0be3d41e3bcdcee3b79bb20f9936414865667fc55ab4a48544e6b2dab114818d`,
  2,832 / `e2ef09c2cb87eedf96cc8b5c301bc77f4235bd5a2652e28065b87cecf9170be5`,
  and 475 / `b0ea1d421e6eec8135485a4de5b36bd551cd489786058d589809edf5e855486d`.
  Root argv binding is
  `409c67f9bb957b41a53b0680bf31c4102ef3bf343c638c92557935f745ee4fb9`.
- Controller independently loaded the sealed driver and called only
  `validate_root` against the actual root receipts; result is exactly
  `SEALED_V5_VALIDATE_ROOT_PASS`. Root budget is consumed. The sanitized result
  is absent, no login child/handoff ran, candidate count is 24, delivery is
  0/15/172, and the accepted candidate is 0/15/73.
- V4 remains immutable rejected construction evidence: its stale V2 receipt
  name and incompatible final-index schema make its handoff unusable. Never
  retry, repair, mutate, or reuse it. The historical destination-absence
  observation must not be repeated or described as unprobed.
- The sealed V5 handoff schema is 15 strings; pinned Python plus driver makes
  a 17-string argv. The clean `env -i` vector and always-single-quoted literal
  payload each contain 27 tokens; the outer non-login launch is the exact
  four-string `/bin/zsh -f -c <payload>` argv. It uses the accepted candidate
  repository cwd, candidate-private HOME/TMPDIR, `/dev/null` stdin, 120-second
  outer and 30-second status-child bounds, 4,096-byte sanitized stdout and
  65,536-byte aggregate diagnostic ceilings. Exact final identities are
  reported after these documents close.
- The driver alone may, after every non-secret gate passes, perform one opaque
  no-follow/exclusive copy, fsync/revalidation, and pinned DEVNULL login-status
  child. Its sole receipt has the accepted eight sanitized fields. Raw
  authentication bytes or metadata are never printed, logged, hashed,
  serialized, committed, or exposed in receipts/prompts/controller/model
  output. This cycle does not probe either authentication location or execute
  the driver.
- Handoff invocation/result/destination budgets are one each and unconsumed.
  Every stop is retained with no retry, repair, replay, replacement, cleanup,
  alternate source, second receipt, or earlier-root/HOME/candidate/run reuse.
  A successful sanitized receipt would be authentication evidence only.
- Next action: independent reconstruction and fresh explicit one-time operator
  credential authority for exactly the reported handoff envelope. No handoff,
  login, model, formal role, Runner, Gateway, test, service, render,
  evaluation, inference, publication, commit, push, cleanup, `--last`, or
  `resume_liveclip.sh` authority is exercised here.

## M3A-v5 root-schema repair and root-only boundary (2026-10-14)

- V4 root-only remains accepted immutable construction evidence: chunk
  `0bf301`, exit `0`, wall `1.472920666`, stdout 964 /
  `2fa18b555dca33f4bff5061f4c272a5e0eac6186d2fd3462bae6c53742cc06f9`,
  empty stderr, and ready-for-controller-review result. Its sealed driver,
  controller acceptance, source, writer, self-check, and final-index hashes
  are respectively
  `5fc9247bf3798f91e3d9e1232aedd5930944ad47075e95ffe60c6f9acc9c30b2`,
  `4a68168e89ab721b49b88b3d4c6a85e20fd5ff9ce6f31d25e3a1e98959fcb49d`,
  `f226b8521985f29171045533a1e3f53175b84efe80f5aaf90bb35062464a3083`,
  `5703e6adb4a55660c4d0bbbed7b0b341d95231dccbf894a9a5dacac5e266a080`,
  `3a9d4034fa5d4f1190c94e8f9ff0d3cb69e10ac5a87e4bb2b9d231f792781034`,
  and `b93529d171eb4b406fc391ba703f0810efc688f70bed2eef02a0064e693fbffd`.
- V4 handoff is rejected and abandoned: its sealed driver still requires
  `controller-acceptance-v2.json` although the root contains
  `controller-acceptance-v4.json`, and expects final-index `verdict` plus
  `contract_sha256` although the sealed index uses `result` and has no
  `contract_sha256`. No V4 handoff/result exists. Never retry, repair, mutate,
  or reuse V4.
- One controller read-only check observed destination absence without source,
  content, byte, metadata, or credential inspection. It is recorded as
  `CONTROLLER_OBSERVED_ABSENT_ONCE_NOT_REPROBED`; V5 does not repeat the check
  and does not represent the state as unprobed.
- Trusted Main changed only this file, the Living ExecPlan, and new
  `tools/loop_engineering/m3a_v5_source_freeze.py`. Helper is 63,577 /
  `b8407a30f79bf52e4696856116322c8105049200b57eb76d9c8b60891d54fb84`;
  source 919 /
  `38f938aa797a3b1ff6f8a99addac066c5f2472782be5eb79c52e5abddce9dbf7`;
  derived driver 31,335 /
  `8dc670fa2aca566f9107d51b0e291f8a7e6dc18ec7d45c30d0cab8b3869b506d`;
  canonical contract 3,512 /
  `b5dcec9dc7def45b94fcdf217e0b3fa41579b01287d426408ba815dc67fabd4c`.
- V5 root construction and generated driver share byte-identical final-index,
  receipt-domain, and receipt-value validators. Root-only executes the exact
  in-memory acceptance/final-index positive proof before `mkdir`. Seven
  negatives reject stale V2/V4 filenames, `verdict`, extra
  `contract_sha256`, missing `result`, and stale final/acceptance phases.
- Helper/source/driver AST and compile, Ruff F/B/S, opaque-copy/login-status
  source equivalence, actual non-secret V40 validation, contract positive plus
  14 negatives, acceptance positive plus 12 negatives, real Python `-c`
  shape, document/evidence correlation, and no-write checks pass.
- Delivery is 0/15/172 after the one new V5 helper; candidate remains
  0/15/73 with 24 exact candidates. V5 root/result remain absent. No
  credential location was accessed and no login/model/downstream phase ran.
- Frozen launch is a 22-string Python argv, 32-string clean vector, no-LF
  32-token literal payload, and separate four-string `/bin/zsh -f -c` argv;
  cwd is immutable `candidate.OlsWg1/repo`, stdin `/dev/null`, outer bound 120
  seconds, diagnostics 65,536 bytes. Exact identities follow final closure.
- Next safe boundary is independent reconstruction and separate authorization
  for one no-replace credential-blind V5 root-only invocation. Later opaque
  handoff requires fresh explicit one-time operator credential authority;
  formal/model authority remains separate and absent.

## M3A-v4 source freeze and root-only boundary (2026-10-14)

- The sole V3 root-only invocation is consumed immutable failure evidence:
  chunk `7001f7`, exit `1`, process/tool times
  `0.05623454198939726` / `0.733792416` seconds, empty stdout 0 /
  `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`,
  stderr 624 /
  `a9a207454070b918c21aa99b8e45e8ce4d066f0b92f53a0f027b0870bcc7b74d`,
  terminal `RuntimeError: root-only argument count mismatch`. Python `-c`
  retained literal `--`, so 19 values reached the 18-value V3 parser. Failure
  preceded root creation; V3 root/result remain absent and no credential,
  login, authentication, or downstream action ran. Never retry or repair V3.
- Trusted Main changed only this file, the Living ExecPlan, and new
  `tools/loop_engineering/m3a_v4_source_freeze.py`. V4 corrects only this argv
  boundary while advancing all versioned root/result/phase/identity bindings.
  The source requires real `sys.argv` to begin `['-c', '--']` with length 20
  and passes `sys.argv[2:]`, exactly 18 helper arguments. The pinned-Python
  sentinel probe observes the same shape.
- Helper is 47,848 /
  `c3321a52ff2bfafe44bcec3a62eb19e78003eab46db4ef0a7b070d3894be7ff2`;
  embedded source 919 /
  `0873f0cf31df774c97115fb5c7998ab4603874386f7a5f602b0fa8cc53cecb38`;
  derived driver 28,285 /
  `5fc9247bf3798f91e3d9e1232aedd5930944ad47075e95ffe60c6f9acc9c30b2`;
  canonical contract 3,422 /
  `e32b9b8cd06441a46d85d0bb98cacff619686e282c7d6e08f788ff86d38f0526`.
- Helper/source/driver AST and compile, Ruff F/B/S, inherited opaque-function
  equivalence, required operations, exact eight receipt fields, actual
  non-secret V40 validator, contract positive plus 13 negatives, acceptance
  positive plus 12 negatives, and real Python `-c` argv shape all PASS.
- Exact V40 root/final provenance, pristine candidate/run, architecture,
  acceptance-v3 requirement, branch/HEAD, 24-name candidate set, and
  inventories correlate read-only. Delivery is 0/15/171 after the sole new
  V4 helper; candidate remains 0/15/73. V3/V4 roots, V4 result, and V40 root
  final/auth results are absent.
- Credential blindness and no-replace semantics are unchanged. No source-
  freeze or root-only path identifies or probes a credential location or
  launches login status. Root/root-invocation/handoff/result/destination
  budgets are one each; later handoff requires fresh operator authority and
  formal inference remains separately unauthorized.
- Frozen launch is a 22-string Python argv containing literal `--`, a
  32-string clean vector, a no-LF always-single-quoted 32-token zsh-`-c`
  payload, and a separate four-string `/bin/zsh -f -c <payload>` argv. Cwd is
  immutable `candidate.OlsWg1/repo`; stdin is `/dev/null`; bounds are 120
  seconds and 65,536 diagnostic bytes. Final identities are reported after
  document closure.
- Next safe boundary is independent reconstruction and explicit authorization
  for exactly one credential-blind no-replace V4 root-only invocation. It may
  create only the fixed root, driver, empty private home/tmp, external
  acceptance, and four supporting receipts plus final index, then stop ready
  for controller review. It may not create the handoff result/destination or
  access credentials.

## M3A-v3 source freeze and root-only boundary (2026-10-14)

- Trusted Main changed only this file, the Living ExecPlan, and new
  `tools/loop_engineering/m3a_v3_source_freeze.py`. No V3 root, receipt,
  result, private destination, candidate, run, auth access, login-status
  child, role/model, test, or downstream action ran.
- Helper is 44,684 /
  `e4cf74b028e03d61493a8bc4cfebb7ffdc3b6ba72dbdbce8cdda7eb3338d614c`;
  the unique embedded source is 777 /
  `aa30abb096b2ad02469b0e4ba7ec3383cee437b9282f93e226e0af7acf3a3b13`;
  the independently derived V3 driver is 28,285 /
  `1faf298e280204e8be5c0aa0355ed1b4e33c8f3b6d0827e6d6377f5105753b78`;
  the canonical handoff contract is 3,422 /
  `9bebc1881238a91407ace36f8c95cdf8e3827b7714adbe0c860b8c00e0ebb34a`.
- M3A-v2 is sealed source-equivalence precedent only. V3 advances the root,
  result, phase, V40 target/run/provenance, 24-name candidate set, and current
  inventories. No historical authority, root/result/destination, candidate,
  run, or credential state transfers.
- AST/compile and Ruff F/B/S pass. Exact normalized source equality passes for
  opaque copy/revalidation/fsync, termination, login-status, and sanitized
  receipt functions. The eight-field receipt, active V3 phase, required
  opaque operations, and absence of formal/downstream command surfaces pass.
- The positive contract and acceptance models, thirteen contract negatives, and
  twelve acceptance negatives pass. Explicit non-secret correlation covers
  the V40 root/preparation and
  final provenance, pristine state/events, policy/toolchain/trusted evidence,
  architecture, acceptance-v3 requirement, main/HEAD, exact candidates, and
  delivery 0/15/170 plus candidate 0/15/73. V3 root/result remain absent.
- The exact derived driver's actual non-secret V40/target validator executes
  to PASS without calling private-runtime, opaque-copy, or login-status code.
- All pre-handoff correlation lexically omits the protected entry before
  metadata/content access. Source-freeze and root-only do not resolve, probe,
  list, stat, open, read, hash, copy, print, log, serialize, or identify an
  authentication location and do not launch login status. Destination absence
  remains an accepted unprobed precondition.
- After final document closure, the external controller acceptance binds both
  document identities. Root-only is a 22-string Python argv with an
  18-string helper schema and a 32-string clean vector with exactly eight
  environment names. The no-LF literal envelope is only the single-quoted
  direct-vector `-c` payload; it contains no zsh, exec, redirection, cwd, or
  stdin token. A separate four-string `/bin/zsh -f -c <payload>` argv supplies
  the non-login launcher. Cwd is immutable `candidate.OlsWg1/repo`; stdin is
  opened from `/dev/null` by the launcher; bounds are 120 seconds and 65,536
  diagnostic bytes. Exact identities are reported for reconstruction.
- A separately authorized root-only invocation may create only the fixed
  no-replace V3 root, derived driver, empty private home/tmp, controller
  acceptance, and four supporting receipts plus final index. Root and
  invocation budgets are one; retain every stop and never retry or repair.
  The actual opaque handoff still needs a new explicit one-time operator grant,
  and formal model authority remains separate and absent.

## Accepted V40 final provenance and M3A-v3 design boundary (2026-10-14)

- The sole V40 `accept-final` invocation is accepted immutable evidence: no
  session, chunk `8d5a0f`, exit `0`, process/tool times
  `8.291638750000857` / `8.205788833` seconds, no timeout/truncation, stdout
  751 / `9fb44ef45672029548260b786db896e2562da32f7e21fe06196b77a78030d26d`,
  and empty stderr. Result is `M3S_V40_FINAL_PROVENANCE_READY_FOR_CONTROLLER_REVIEW`.
- Five uid-501 mode-`0600` outputs are final acceptance 3,913 /
  `a44929f89fca9629b06163814c8c1233278f830036c343c52e11fd4b1ea22a3e`,
  transport 1,383 /
  `1651b2c39787898f63a20390f30ac52fae672a3fb691116f44566242b1d15f2d`,
  repository manifest 6,139,910 /
  `20f5cf4e26274de1176aa23a79ee9508396246d18a14a1046bae5918f2e87403`,
  attempt manifest 12,177,744 /
  `d6f9d170fbc6db5ebceaaaa9e6dfc63b838f1d2e46dd77782db4845a87e42c5e`,
  and final index 2,731 /
  `2668171e0b0c22f2022793c4413b359b3dd31282bc3fbbe1ac413665a647b7b6`.
  Completed tree is 44,326 paths / 967,345,497 bytes /
  `894bf7939742cafb4f7ee512bd2ffa4b592a5016a93f3e8288e4adf75251f1ba`.
- `candidate.M4v94Rmv` / `20261014T214746Z-cd5796b8` remains pristine
  `received` at 0/0. State/events are unchanged. Candidate count is 24;
  delivery is 0/15/169 and candidate is 0/15/73; root final/auth results remain
  absent. Root through final-acceptance budgets are consumed; authentication
  and formal budgets remain separate and unconsumed.
- Gap decision: M3A-v2's opaque-copy and sanitized-receipt mechanisms remain
  the security precedent, but its V39 bindings and root/handoff/result/private-
  destination budgets are consumed. Its root, candidate, run, HOME, result,
  and authentication state are immutable historical evidence and cannot be
  repaired, replayed, repointed, transplanted, or reused for V40.
- Fresh design is fixed absent no-replace `m3-authentication-handoff-v3`, bound
  only to accepted V40 final provenance and the pristine V40 candidate/run.
  Root-only remains credential-blind and may later create only a derived
  single-command handoff driver, external acceptance, empty private home/tmp,
  and four supporting receipts plus final index. It cannot probe a credential
  location or launch login status.
- Active V3 metadata is controller acceptance `M3A_V3_CONTROLLER_ACCEPTANCE`,
  root `M3A_V3_ROOT_ONLY` / `M3A_V3_READY_FOR_CONTROLLER_REVIEW`, final index
  `M3A_V3_FINAL_INDEX`, and later sanitized `M3A_V3_AUTH_HANDOFF` /
  `READY_FOR_CONTROLLER_REVIEW`; older phase names are historical only.
- All pre-handoff correlation must omit the protected credential entry before
  metadata/content access. Credential content/location/name and all
  secret-derived metadata are excluded from prompts, argv, environments,
  manifests, receipts, diagnostics, commits, and reports. A later authorized
  handoff may persist only the accepted eight-field sanitized receipt.
- Root/root-invocation/handoff/result/destination budgets are one each; every
  stop is retained with no retry, repair, replacement, alternate source,
  cleanup, or reuse. Authentication success will not grant formal authority.
- This cycle edits only the two documents and creates no helper/source/root.
  The next deterministic boundary is one separately authorized credential-
  blind M3A-v3 source-freeze/root-only-design cycle, stopping before root
  creation. The actual handoff requires a new explicit one-time operator grant
  for this exact V40 candidate/run; no prior M3A authority transfers. Formal
  model inference remains another later authority.

## Accepted M3S-v40 preparation and frozen final acceptance (2026-10-14)

- The sole preparation is accepted immutable evidence: session `4478`, chunks
  `acee28` / `efd881`, return `0`, elapsed `249.238045` seconds, no timeout,
  truncation, or wrapper error. The uid-501 mode-`0600` root result is 23,850 /
  `cd13363aee5d6fd069355ff1ee31ac1f3827b2f25bb9a565eebc3bb68b2dd9bf`;
  semantic result is
  `M3_SUCCESSOR_PREPARATION_V40_AWAITING_CONTROLLER_ACCEPTANCE`.
- Exactly `candidate.M4v94Rmv` and run
  `20261014T214746Z-cd5796b8` were created. The run remains pristine received
  at 0/0 with null Coder/error and empty artifacts/results; state/events are
  12,796 /
  `3a5517a757be71d40566e5175576b200cef65da8c4b0184e75d6ff880a159ed8`
  and 144 /
  `f1a5ec47ed1051af8f64e2fdf0c105881b6a733c63bbfeedde0bf273e21285a8`.
- All 38 receipts sealed without error. Final index is 18,095 /
  `f31b88a03ec37ada6237eb92817004ad4a39b42ee768da1ad5fb019206bd2a81`;
  repository manifest file is 6,139,707 /
  `6a862b74d533c6cbf9935b711032c209da0f7a0247c0698dbe3d2907436708bd`
  over 27,412 paths / 581,100,106 bytes; attempt manifest file is 12,176,698 /
  `fb244a4eebeb6c3d973b1141844687ae14efd9f432d65808e5645d5cf8f17488`
  over 44,319 paths / 936,825,023 bytes; completed tree is 44,321 paths /
  949,019,816 bytes /
  `8371424444dc49dd688dca18f063df4fb8b7a79eb2d01478829a928dc4a1bc78`.
- Preparation invocation/result, suffix, and init budgets are consumed. Final
  acceptance/auth/formal budgets remain unconsumed. Candidate count is 24;
  delivery remains 0/15/169 and candidate 0/15/73. All five final-acceptance
  destinations and root final/auth results are absent. Preserve and never
  retry, repair, replay, delete, clean, or reuse the V40 evidence.
- Sealed offer is 5,032 /
  `afa8c4b8427193e6efa2ca2c024af22baf35a7f2eab7c8c00ba01ee9393f977c`.
  Exact external acceptance is 3,912 canonical no-LF bytes /
  `7ffba177969a3d29ed5f2540ee7360bb58dde63811d1a95de6aa905c6e0e6205`,
  or 3,913 transported bytes with one LF /
  `a44929f89fca9629b06163814c8c1233278f830036c343c52e11fd4b1ea22a3e`.
  Its `documents` are the immutable preparation generation; separate argv
  fields bind this cycle's final closed ExecPlan/STATUS hashes.
- Frozen `accept-final` is direct and credential-free: 17-string Python argv,
  32-string clean `env -i` vector, and 32-token always-single-quoted non-login
  envelope. It uses `candidate.M4v94Rmv/repo`, `/dev/null`, 120-second
  driver/outer bounds, and 65,536-byte aggregate diagnostics. Exact identities
  are reported after these self-hashed documents close.
- Success may create only final acceptance, transport, two postacceptance
  manifests, and postacceptance final index, then stops at
  `M3S_V40_FINAL_PROVENANCE_READY_FOR_CONTROLLER_REVIEW`. The reserved root
  final result is an absence/environment gate and is not written.
- This cycle edits only the two documents and executes no acceptance, auth,
  role/model, test, service, render, evaluation, publication, commit, push,
  cleanup, media mutation, `--last`, or resume action. Next single safe
  boundary is independent controller reconstruction followed by one exact
  direct V40 `accept-final` authority.

## Accepted M3S-v40 root and frozen preparation boundary (2026-10-14)

- The sole V40 root-only invocation is independently accepted immutable
  evidence: session `31299`, chunks `e6ae6c` / `1fd80f` / `3aff7d`, exit `0`,
  observed wait `70.281583083` seconds, no timeout/truncation, stdout 704 /
  `8b9470370c9d0de5af54cf613edd17072d3a5d7773a0fbda2542c336d1704cdf`,
  and empty stderr. Phase/result is `M3S_V40_ROOT_ONLY` /
  `M3S_V40_READY_FOR_CONTROLLER_REVIEW`.
- Root and private directories are uid 501 mode `0700`; files are uid 501
  mode `0600`. Driver/controller/source/writer/self-check/final-index are
  468,657 /
  `4b2e438f652998fc36cae9590ecf17b08d6e245433cdf5eab9480b5ddc1fafc2`,
  14,519 /
  `89b2ebbc6d18cc24bab47c72bf5e9499c1e47da22fd648ef5e563ee1c461e7c5`,
  524 / `8de386e0c256635505bb41c8b3c1855db8744fa889d96f6be80b7ad19e916d25`,
  72 / `931b38e3d416a90977e891d368b075055925ae6070e732e3d5820ae21f610388`,
  5,173 /
  `fdcd6049a7f6dad74eb7f6522ad8b2c1c20fb18368024af8ef9a04e5c8c1feaa`,
  and 2,000 /
  `9d623cd3b398010a279cb424a93cbee91e99e2555ab9307075bd9043c1dd7a7a`.
- Root controller verdict is accepted-before-creation; source/writer/
  self-check PASS; final verdict is ready for controller review. Final index
  binds pre-root plan/STATUS and root argv
  `95077d6f26b13e5f0b5f931dbb902ee1a7c0c3d6990d88e343cd8435d5f6f061`.
  Self-check has 64 gates and no-write PASS.
- Root budget is consumed. Preparation result/invocation, suffix, loop-init,
  final acceptance, auth, and formal budgets remain unconsumed. All three V40
  reserved results are absent; candidate count is 23; delivery remains
  0/15/169.
- The frozen future preparation is the sealed driver's exact 23-string
  `prepare` schema plus pinned Python/driver, for 25 argv strings. It binds
  final post-root documents, driver, base, seed, immutable wrapper 2,345 /
  `d022a3dbb40be1664ba663617c18e1690c3e353be51d20a46d8c852f2d3e14ed`,
  root final index, and root controller acceptance. Final canonical identity
  is reported after document closure.
- The direct bounded-wrapper vector is 17 strings with root-private HOME/TMP,
  exact clean environment, seed/result/phase/timeout/canonical-argv bindings,
  pinned Python, and immutable wrapper. The non-login envelope uses standard
  always-single-quoted reopening and `/dev/null`. Inner/outer bounds are
  2,730/2,760 seconds; output/diagnostic ceilings are 1,048,576/65,536 bytes.
- The future invocation/result budget is consumed at exclusive result
  creation; suffix at the sole `mktemp`; init at the sole loop-init. Before
  allocation the same verified process repeats all 64 gates over exact final
  documents, root evidence, 23 predecessors, V3/13-path/B2/policy/toolchain/
  trusted-context evidence, inventories, protected omissions, and process
  exclusions. Success stops awaiting distinct final controller acceptance.
- This documentation-only cycle changes no other path and executes no
  preparation, allocation, credential access, loop-init, role/model/test/
  service/render/evaluation/publication/commit/push/cleanup/`--last`/resume
  action. Every future stop is retained; no retry, repair, replay, reuse, or
  cleanup is allowed.
- Next single safe boundary after independent reconstruction: exactly one
  frozen bounded-wrapper V40 preparation invocation. Final acceptance,
  authentication, and formal dispatch remain separately unauthorized.

## M3S-v40 source freeze and root-only prerequisite (2026-10-14)

- Accepted starting identities are ExecPlan 7,127,127 /
  `17a097998140b413b28300f58b756ac64d7f4be628c48103187b289a96e3c6ff`,
  STATUS 170,324 /
  `5877740291932b6b1e844822835fba56ee64cea96640672a6b2cdf4db80d72dc`,
  and acceptance-v3 12,289 /
  `308fdc96f2c5ddaffb6d01c65ddc089958a5ba883ab2c00c986da38d5483ba00`.
  Starting delivery is 0/15/168; the single new V40 helper makes final
  delivery 0/15/169. Candidate inventory remains 0/15/73; exact candidate
  count is 23; fixed V40 root and all three reserved V40 results are absent.
- The fresh Trusted Main helper is
  `tools/loop_engineering/m3s_v40_source_freeze.py`. It derives V40 only from
  immutable sealed V39 driver 452,597 /
  `9b756bf28d7c625e28c0a85ff92b1ee40ca7c53572105122973b9a35fdeca7bc`,
  rolls active/future V40/V41 metadata, and preserves historical evidence.
  The complete V39 root/preparation/final-acceptance/formal-stop closure is a
  fail-closed immediate predecessor; no retained candidate/run/session/root
  is reused or mutated.
- Preallocation is the exact 23-name candidate set. Sanitized
  `candidate.oivrdV6U` evidence is 56,251 paths / 1,143,615,319 regular bytes /
  `b1506798b693d79b61d3e1c55bd525d84fec54e09d793d910b65e3b2342d3d1c`;
  its one protected credential entry is omitted before metadata/content
  access. Together with `candidate.KWbe2iGW`, omission count is exactly two.
- V40 binds acceptance-v3, trusted-context successor-v2, the exact 13-path
  future Coder allowlist, immutable B2 seed, policy/toolchain, architecture
  HTML, branch/HEAD, final documents, 0/15/169 inventory, and V39 terminal
  evidence. Future loop-init remains 3 strings / 104 canonical JSON bytes /
  `d74c746962574dcba6994d591f75734fbbee957669d710b5631e7d4f7bdae842`.
- Static validation passes exact source/helper/driver AST and compile,
  deterministic transform, canonical contracts, command schemas 23/23/15,
  one `mktemp`, one `loop-init`, zero phase-policy violations, semantic
  acceptance negatives, and the complete actual 64-gate allocation-free
  graph with process gate true and byte-identical before/after snapshots.
- Root/result/suffix/init budgets are one each, but this cycle crosses none.
  Root-only may later create only the fixed private root, derived driver,
  external acceptance, empty private home/tmp, and four supporting receipts
  plus final index. Every stop is retained; no retry, repair, replay,
  replacement, cleanup, or reuse is allowed.
- This cycle edits only the Living ExecPlan, STATUS, and the new non-product
  V40 helper. It creates no root/candidate/run/result, invokes no driver phase
  or loop-init, accesses no credential, and launches no role/model/test/lint/
  render/evaluation/publication/commit/push/cleanup/`--last`/resume action.
  The exact final source/helper/driver/acceptance/contracts and root
  argv/vector/envelope identities are reported after byte closure.
- Next safe boundary, only after independent controller reconstruction: one
  exact credential-free V40 root-only invocation from immutable
  `candidate.OlsWg1/repo`, non-login `/bin/zsh`, `/dev/null` stdin, exact
  eight-name environment, 120-second outer bound, and 65,536-byte diagnostic
  ceiling. It must stop before preparation.

## V39 terminal formal stop and V40 recovery design (2026-10-14)

- The only V39 formal invocation is consumed immutable `BLOCKED` evidence:
  session `32807`, chunks `60025d` / `02b218`, exit `2`, cumulative waits
  `333.223254791` seconds, no timeout/truncation. Run
  `20261014T191719Z-0802b465` is terminal at 1/1; state is 12,021 /
  `78b8133ace2dbf2b9237465028245ab4e953fc4631c9c21f8f87f274af45d47d`,
  events 4,224 /
  `b9abfe8299d47328ca50638515f857115d6166a8b80ee8113a341007a0b12603`.
- Exact Coder session is `01a13c35-37c9-7493-821a-6cefd8ed7513`.
  Planner `READY` is 11,291 /
  `39133d5beb3b72e22f4d2e96e9f3100a2bcbf4a27eef83195b738f582549c8c2`;
  Coder `BLOCKED` is 2,691 /
  `53e325e8ef39291201051a03a8dedccea2b7b8c65165495ac287d9e4a421e945`.
  Reviewer/Tester/Runner/Gateway and command results are absent. Candidate,
  run, session, roots, receipts, and role artifacts are retained and never
  retried, resumed, repaired, replayed, published, or reused.
- Architecture decision: compatible. The bounded exact-tree repair belongs in
  infrastructure adapter `src/liveclip/media/secure_files.py`, not an
  application service. The file is 65,066 /
  `8bf78b587f96b82cd2c2669c2d1b32b10431217ef9bf51f6bed6b171af7f29b6`
  and imports only the standard library. Future Coder ownership expands by
  exactly it and `tests/unit/test_secure_files.py` 28,467 /
  `05fbb0882926603deff39fa3ebdf34edc075f38fa133e4aeb145281c6491d7b9`;
  the exact allowlist is thirteen paths. Formal workflow and Runner remain
  unchanged.
- Acceptance requires an incremental descriptor-anchored scan bounded by the
  exact expected entry count/depth, rejection of unknown paths before
  metadata/open/recursion, no enumeration of unexpected subtrees, preserved
  no-follow/pinned identity/rehash/rollback behavior, and synthetic negative
  fixtures for wide/deep/extra/missing/duplicate/type/race cases. A need for
  another path is `BLOCKED`, never implicit scope expansion.
- Reconciliation against `AGENTS.md`, `.agent/PLANS.md`, and the checked-in
  loop-engineering ExecPlan preserves the isolated sole Coder, fresh read-only
  roles, fixed Runner, evidence correlation, and trusted publication gates.
- New Trusted-Main requirement is
  `docs/requirements/liveclip-agent-runtime-v2-acceptance-v3.md`. It preserves
  the inherited outcome while binding the V39 stop, exact thirteen-path
  allowlist, fresh no-reuse candidate/run rules, and versioned successor-v2
  trusted record. Final identity is reported after closure.
- Fresh M3S-v40 design uses absent fixed no-replace root
  `m3-successor-preparation-v40`, immutable B2 seed, exact 23 predecessors,
  one root/result/suffix/init budget, and exactly one future
  `loop-init REQUIREMENT=docs/requirements/liveclip-agent-runtime-v2-acceptance-v3.md`.
  Its three-string canonical JSON is 104 bytes / SHA-256
  `d74c746962574dcba6994d591f75734fbbee957669d710b5631e7d4f7bdae842`.
  It never copies V39 candidate/authentication state. Preparation, final
  acceptance, new opaque authentication, and formal inference remain distinct
  future authorities.
- Pre-edit delivery was 0/15/167; the sole new requirement makes the closed
  inventory 0/15/168. Candidate remains 0/15/73 and candidate count 23. This
  cycle edits planning documents only,
  creates no root/candidate/run, and runs no model, role, test, lint, render,
  evaluation, publication, cleanup, commit, push, `--last`, or
  `resume_liveclip.sh`.
- Next boundary after independent acceptance of the final three file
  identities: one credential-free V40 source-freeze/root-only-design cycle,
  stopping before root creation.

## M3A-v2 accepted authentication and frozen V39 formal boundary (2026-10-14)

- The sole opaque handoff is accepted immutable evidence: no session, chunk
  `5b7131`, exit `0`, wall `0.260951209` seconds, no timeout/truncation, stdout
  228 / `ad7d4e5eb2e6d7275eb6f9a6e43e20bc3f0cb4cc25f101bef8526d41e6a853e8`,
  and empty stderr. The exclusive sanitized receipt is uid 501 mode `0600`,
  261 bytes / `e7da30b99e7983e6984c22a22a5d084d622a7eb2279ed417a88ac461410f5c1a`;
  it reports copy success, destination mode `0600`, owner uid 501, format 1,
  `SUPPORTED_AUTHENTICATED`, phase `M3A_V2_AUTH_HANDOFF`, result
  `READY_FOR_CONTROLLER_REVIEW`, and null sanitized error.
- Handoff invocation/result/destination budgets are consumed. Credential
  content and secret-derived metadata remain opaque and excluded from logs,
  hashes, receipts, prompts, argv, environments, commits, and reports.
  Authentication success is not formal-role authority or engineering
  acceptance.
- Candidate `candidate.oivrdV6U` and run
  `20261014T191719Z-0802b465` remain pristine `received` at 0/0 with null
  Coder/error and empty artifacts/results. State/events remain 9,210 /
  `2648acc7d3dcc144911480c434dc7e52ec3dce984bc0baf382c44dad8e594043`
  and 144 /
  `8378d385b481413208343ce35b4a9f7976f6ed47fee2a7395b2b70a792a1ece2`.
  Candidate count is 23; delivery is main at
  `2f361fcddc0e63ae62ee62826e27b54bb8204c53`, 0/15/167; candidate is
  0/15/73.
- The unlaunched official argv is exactly three strings, 63 canonical JSON
  bytes / `849d982523c516ee44cad62c073f2af2d262cbe2d87fd927b14ecfdec2f92eb6`.
  Its 12-string clean vector is 499 bytes /
  `aeecbfd7cf02e1a9e43c8ab8462c79fd2c63d3cc1e8779e9320d4d40af953d35`;
  its 12-token literal non-login envelope is 513 bytes without LF /
  `f348f66359b9095b76c0763555659bdd846fd99c6a07cf738b07771c62fb1503`.
  It uses the candidate repository, private HOME/TMPDIR, `/dev/null`, a
  122,400-second outer allowance, and a 1,000,000-byte diagnostic ceiling.
- A later dispatch must revalidate the final closed documents, V39 final
  provenance, M3A-v2 root and sanitized result, pristine run, exact
  policy/trusted-context/toolchain evidence, branch/HEAD, inventories, and
  candidate set. Fresh read-only Planner/Reviewer/Tester/Gateway, sole
  isolated Coder, fixed Runner, evidence correlation, checked-in retry gates,
  no `--last`, one writer, and trusted CAS publication remain mandatory.
- Formal dispatch is one-shot and retained on every stop, with no retry or
  repair. This cycle does not launch it. Real model inference remains excluded
  and requires new explicit operator authority; no role, Runner, Gateway,
  test, service, render, evaluation, inference, publication, commit, push,
  cleanup, `--last`, or `resume_liveclip.sh` ran.

## M3A-v2 accepted root and opaque handoff freeze (2026-10-14)

- The first/only credential-blind root invocation is accepted immutable
  evidence: no session, chunk `54fb2d`, exit `0`, wall `0.241832333` seconds,
  no timeout/truncation, stdout 161 /
  `0831f4aec8cf18b5fb4ca9f732d3879cde974045407d40789d515650739083da`,
  and empty stderr. Phase/result is `M3A_V2_ROOT_ONLY` /
  `M3A_V2_READY_FOR_CONTROLLER_REVIEW`.
- Root/empty home/empty tmp/receipts are uid 501 mode `0700`; files are uid
  501 mode `0600`. Driver/controller/source/writer/self-check/final-index are
  23,756 / `0e86fb41bbee0ae89244a5a766b33714f302c72407a7c9994c5e384996ec7288`,
  3,551 / `af9c92dc577c5fd9f6289e9e6d216ada2c75d083023f9fba38e328473e6259b7`,
  392 / `9af7315a0fbedb3f9bb09bb764204db6899f554bd29d69773bdec6bc1e488015`,
  61 / `15e6d36769e6bcd3e3fa6a4057ae27207335809748197560041643e0415085df`,
  1,165 / `3fe1f03eeac73a39da493c83fa491bb92d8c5d40f7129889837cdd042ca4cf4d`,
  and 872 / `1489cdf38801c5290b50d3da12a0913d1add34dbea3baf3a0a0c9d160402fce8`.
  Root argv binding is
  `663e08157116f43913f9be6c079cf775f8abdb42b47a8e6bd98f156fa4de7d14`.
- The root budget is consumed. The sanitized handoff result and destination
  budgets remain unconsumed; reserved result is absent. No credential location
  was probed and no login child or handoff ran. Candidate/run remain pristine;
  candidate count 23, delivery 0/15/167, candidate 0/15/73.
- The frozen handoff is one 17-string Python argv inside a 27-string clean
  `env -i` vector and 27-token always-single-quoted non-login envelope. It uses
  candidate-private HOME/TMPDIR, `/dev/null` stdin, 120-second outer and
  30-second status-child bounds, 4,096-byte sanitized stdout and 65,536-byte
  aggregate diagnostic ceilings. Final identities are reported after these
  documents close.
- The driver alone may, after all non-secret gates pass, perform one opaque
  no-follow/exclusive copy and pinned DEVNULL `codex login status`. Its sole
  receipt has the accepted eight sanitized fields and no secret-derived
  metadata. The documentation/static cycle does not probe either credential
  location or execute the driver.
- Invocation/result/destination are single-use. Every stop is retained; no
  retry, repair, replacement, cleanup, alternate source, second receipt, or
  M3A-v1 reuse is permitted. Authentication success is not formal-role or
  engineering acceptance.
- Next action: independent reconstruction and distinct exact authority for the
  single reported handoff envelope. No handoff, role, Runner, Gateway, test,
  service, render, evaluation, inference, publication, commit, push, cleanup,
  `--last`, or `resume_liveclip.sh` authority is exercised here.

## M3A-v2 opaque authentication prerequisite design (2026-10-14)

- V39 final controller acceptance is now accepted immutable evidence: the
  sole direct invocation exited `0` at chunk `77f98e`; stdout is 751 bytes /
  `987352f48cffb057e269e36faebe6d498fcfa684d2d6c8411a94aee6e73acc88`,
  stderr is empty, and phase/result is
  `M3S_V39_FINAL_CONTROLLER_ACCEPTANCE` /
  `M3S_V39_FINAL_PROVENANCE_READY_FOR_CONTROLLER_REVIEW`.
- The five postacceptance files are uid 501 mode `0600`: final acceptance
  3,912 / `fe6405636b4fa359c1e3ade43f0821a80cf636128a0f9726bdd4825f941f5c56`,
  transport 1,383 /
  `6e37cf4d3f37d4c848c6f52dd5690b6bae145ce44fe7c8ed235657469073ad5e`,
  repository manifest 6,139,908 /
  `86ed1804a7b9373e9547f985dbd71136d70787dcad229e3b475de277c97bb6bc`,
  attempt manifest 12,177,741 /
  `115cd285478ced736b3af391e15f39947bd171786e18dc42c89313ac8ec5bdb7`,
  and final index 2,730 /
  `a3b5ae0908569c996ac3b59957125b1647c2e8f9cd8595035a4d95d78cba4db6`.
  Completed tree is 44,326 paths / 967,213,201 bytes /
  `c74a87299cdd78549769ba7a0f0490e1ebcd0d63a3a768c45debcde991cabbce`.
- Accepted target remains `candidate.oivrdV6U`, run
  `20261014T191719Z-0802b465`, pristine `received` at cycle/code-cycle 0/0
  with no Coder session/error/artifacts/results. Candidate count is 23;
  candidate inventory is 0/15/73. The new trusted helper is the sole delivery
  addition, making final delivery inventory 0/15/167. V39 root final/auth
  results remain absent.
- A fresh M3A-v2 design follows the accepted M3A-v1 opaque-copy security
  model while replacing all predecessor gates with V39 final provenance. Its
  fixed no-replace root is absent. Root-only is credential-blind: it may write
  only the derived driver, external acceptance, empty private home/tmp, and
  four supporting root receipts plus final index. It may not probe any
  authentication location or launch login status.
- The future driver has only one `auth-handoff` command and an exclusive
  sanitized eight-field receipt. It preserves no-follow/exclusive copy,
  source revalidation, fsync, DEVNULL login-status child, pinned executable,
  private candidate HOME/TMPDIR, no raw diagnostics, and zero persisted
  secret-derived metadata. Root/handoff/result/destination budgets are one
  each; all stops are retained and never retried.
- This cycle freezes root-only only. Exact final document, source, helper,
  driver, contract, controller acceptance, argv, vector, and envelope
  identities are reported after document closure. Root execution, handoff,
  authentication access, formal roles, tests, services, rendering,
  evaluation, inference, publication, cleanup, commit, push, media mutation,
  `--last`, and `resume_liveclip.sh` remain unperformed and unauthorized.
- Next safe boundary: independent controller reconstruction, followed by a
  distinct exact authority for one M3A-v2 root-only envelope. Root success is
  not handoff authority; handoff success will not be formal-role authority or
  engineering acceptance.

## M3S-v39 prepared candidate and final-acceptance freeze (2026-10-14)

- The sole allocation-free verifier is accepted immutable PASS evidence:
  session `25851`, chunks `9b798a` / `ad71c4` / `58b260`, exit `0`, 5,104-byte
  stdout SHA-256
  `efa65881acb2bd1e7fbb1167a019f60956f5668b61489349a02bd4b7c1057ecb`,
  empty stderr, exactly 62 gates, authentication absent, and byte-equal
  pre/post snapshot
  `5112633daac2ddc957cdc90edf144ad42ffa45a708a8f08bbde18496879fc69f`.
  Its one-use budget is consumed.
- The sole preparation is accepted immutable success evidence: session
  `92334`, chunks `49e70d` / `042fc2` / `bd5e9b` / `be8e63` / `064ddf` /
  `1e00fe` / `bd5cc0`, return `0`, wrapper elapsed `227.044397`, no timeout,
  truncation, wrapper error, session ID, or credential variables. Result is
  `M3_SUCCESSOR_PREPARATION_V39_AWAITING_CONTROLLER_ACCEPTANCE`.
- Root result is uid 501 mode `0600`, 23,849 bytes /
  `314a857182f9238219bb28d1ba03c7f84344883264518205241d6190bc692667`;
  embedded output is 20,476 /
  `22f442e87a366331ce937d66132b3706bec4c18d072e76edcdb26e0fb0ddfdcb`.
  Exactly `candidate.oivrdV6U` and official run
  `20261014T191719Z-0802b465` were created. The run is pristine `received`
  at 0/0 with null Coder session/error and empty artifacts/results.
- All 38 receipts are sealed. Final receipt index is 18,094 /
  `b42071ee39c7f176f30750a937106ed50a22c65d7aed41c8aacf9db0b9521867`;
  completed tree is 44,321 paths / 948,887,527 bytes /
  `0c6bdcf0df5bcc095a4bc8ff4c5dba5d8dcf939dde308b8cacc9831dbbeeee73`.
  Candidate inventory is 0/15/73; delivery remains 0/15/166; candidate count
  is 23. Final acceptance/auth/formal work has not run.
- Verifier, prepare-result, suffix, and init budgets are consumed. Preserve
  V39 root/result/candidate/run/offer and never retry, repair, delete, replay,
  clean, or reuse them. Final acceptance is a distinct one-use boundary;
  authentication and formal dispatch remain unavailable afterward until
  their own independently accepted evidence boundaries.
- Sealed offer is 5,031 bytes /
  `5d7eb88ee075a4d5945443a4d8801bc4707868c3cd27ea9e87921b74fc80df08`.
  Exact external acceptance is 3,911 canonical no-LF bytes /
  `a2188c5568185b540bf77441b256992e32a82a51d32a8ca731fc7dfb4532cac5`,
  or 3,912 transported bytes with one LF /
  `fe6405636b4fa359c1e3ade43f0821a80cf636128a0f9726bdd4825f941f5c56`.
  It binds the immutable offer documents; separate argv fields bind the final
  post-edit ExecPlan/STATUS hashes.
- Frozen `accept-final` is direct and credential-free: 17-string Python argv,
  32-string clean `env -i` vector, and 32-token always-single-quoted non-login
  envelope; candidate repo workdir, `/dev/null` stdin, `BOUND_TIMEOUT=120`,
  120-second outer bound, and 65,536-byte aggregate diagnostics. Exact final
  command identities are reported after these self-hashed documents close.
- Success may create only the final controller-acceptance file, transport
  receipt, two postacceptance manifests, and postacceptance final index, then
  must stop at `M3S_V39_FINAL_PROVENANCE_READY_FOR_CONTROLLER_REVIEW`. The
  reserved root result is an absence/environment gate and is not written by
  the sealed direct driver. Any stop is retained and never retried.
- Next action: independent controller reconstruction and explicit authority
  for exactly one frozen `accept-final` invocation. This documentation cycle
  executes nothing and grants no authentication, role, test, service, render,
  evaluation, inference, publication, cleanup, commit, push, media mutation,
  `--last`, or `resume_liveclip.sh` authority.

## M3S-v39 accepted root and ordered command freeze (2026-10-14)

- The sole root-only invocation is independently accepted immutable evidence:
  exit `0`, session `16252`, chunks `1c881d` / `4ee045` / `c1615f`, observed
  wait `68.060836832` seconds, no timeout/truncation, stdout 704 /
  `9ba8fa9f702986302d9260ff1e6c9b2e2503c397c47fede7acfe8107ab6c520c`,
  and empty stderr. Phase/result is `M3S_V39_ROOT_ONLY` /
  `M3S_V39_READY_FOR_CONTROLLER_REVIEW`.
- Root/`home`/`tmp`/`receipts` are uid 501 mode `0700`; home/tmp are empty;
  files are uid 501 mode `0600`. Driver/controller/source/writer/self-check/
  final-index identities are 452,597 /
  `9b756bf28d7c625e28c0a85ff92b1ee40ca7c53572105122973b9a35fdeca7bc`,
  10,768 / `e32334901302206f7ea712c1559119c1d8ee8929b5279f71f64088dfab5e4da1`,
  524 / `e9ffd0486c0885049557090f98d75084fae6f469cd539f2fd9e9a420baa96098`,
  72 / `3d03786a9b07dea917e1c42b7712ca8cbb19a8c4920a9d171e86fbbe80ee22d3`,
  4,400 / `d6932f607b85dee7b9294e6eceea3c8c86fe603c2b89115732e6d132d0d22e7e`,
  and 2,000 / `d13dd343c9aec55a93bab0e795780bf0e851269c9bf5f6ce4d3725ee8d7e06fc`.
- Controller receipt is `ACCEPTED_BEFORE_ROOT_CREATION`; source/writer/
  self-check are PASS; self-check binds 62 gates/no-write PASS; final verdict
  is ready for controller review and binds root argv
  `9f0e085167d9eff3a844bd9c69317dbe65ce7bbe370e12c3684fb2a24c747b06`.
- Inventory remains 0/15/166; candidate count is 22; V38 root and all three
  V39 reserved results are absent. Architecture HTML remains protected at
  66,116 / `48d87ef5864adfa9f4eb7115055924713e64b1a9000c2ed17678bc84bc8c41ce`.
  Only the root budget is consumed.
- Two commands are frozen against the same final documents. First is one
  allocation-free direct `verify-prepare`: 25-string Python argv inside a
  39-string clean vector, 120/150-second driver/outer bounds, 65,536-byte
  diagnostics, expected sole stdout phase/result/gates
  `M3S_V39_POST_ROOT_VERIFY_PREPARE` / PASS / 62, and strict no-write proof.
- Second is one separately authorized bounded-wrapper `prepare`: 25-string
  Python argv inside a 17-string wrapper vector, 2,730/2,760-second bounds,
  1,048,576/65,536-byte output/diagnostic ceilings, no-replace result, one
  suffix, one init, and only the frozen preparation path through
  `M3_SUCCESSOR_PREPARATION_V39_AWAITING_CONTROLLER_ACCEPTANCE`.
- No document or protected-state byte may change between independently
  accepted verifier PASS and prepare launch. Verifier PASS is not prepare
  authority. Non-PASS consumes verifier authority and stops permanently.
- This cycle executes neither command and grants no prepare, final acceptance,
  authentication, formal role, test, service, render, evaluation, inference,
  publication, cleanup, commit, push, media mutation, `--last`, or
  `resume_liveclip.sh` authority.

## M3S-v39 source-freeze boundary (2026-10-14)

- The accepted V38 root command is stale, unexecuted, permanently abandoned,
  and non-reusable. Its accepted source-freeze identities remain ExecPlan
  7,060,496 /
  `43b1b4a955a8fb867d1ec000ee9288ac3d12d1ed2b36b2bb720f4b6363d36680`,
  STATUS 149,485 /
  `2ec540b45c13ad15276841a0fce963bdd0cf68d2742713a89bd04f209399b273`,
  helper 41,978 /
  `e6ec4f0400ee4a4477d82e5a75b4294900477834a8a5430d024d0fc18d9f4501`,
  and derived driver 446,985 /
  `406a0a9cf2a901df045d8c0d237f057a30885b5f41dd95ee916163e8e27d6fb0`.
- Cause: after V38 freeze, the separately authorized operator architecture
  artifact added one exact untracked path. V38 froze 0/15/164; the accepted
  HTML moved inventory to 0/15/165. V38 root and all three result paths remain
  absent. No V38 root/result/suffix/init budget was crossed.
- `docs/liveclip-architecture.html` is protected operator-owned evidence:
  66,116 bytes /
  `48d87ef5864adfa9f4eb7115055924713e64b1a9000c2ed17678bc84bc8c41ce`.
  V39 rejects mutation, loss, substitution, or extra inventory drift before
  allocation.
- New trusted non-product helper is only
  `tools/loop_engineering/m3s_v39_source_freeze.py`. Its addition makes final
  inventory exactly 0 staged / 15 modified tracked / 166 ordinary untracked;
  candidate count remains 22.
- V39 derives only from the independently reconstructed accepted V38 driver,
  rolls active/future metadata to V39/V40, binds the exact stale V38 closure,
  retains the 22-name phase-aware candidate-set contract, and keeps command
  schemas 23/23/15 with one `mktemp` and one `loop-init`.
- Static AST/compile, Ruff F/B/S, exact V38 source/driver/acceptance
  reconstruction, contract-hash, phase/result, candidate-set, architecture
  positive/negative, acceptance-negative, stale-inventory 164/165 rejection,
  and the full 62-gate allocation-free graph pass with byte-equal no-write
  snapshots.
- Next boundary is independent controller reconstruction and explicit
  acceptance of one exact V39 root-only command. This cycle grants no root,
  prepare, accept-final, allocation, authentication, role, test, render,
  evaluation, inference, publication, cleanup, commit, push, media mutation,
  `--last`, or `resume_liveclip.sh` authority.

## M3S-v38 source-freeze boundary (2026-10-14)

- V37 verifier PASS is immutable: session `51656`, chunks `c2a01c` /
  `81d484` / `9a7104`, exit `0`, 59 gates, stdout 5,102 bytes /
  `6426c9834eaf30b72b9c955198dccfc59166b1abb0cebe20f2eea303858c4516`,
  empty stderr. Its budget is consumed.
- V37 prepare is consumed retained failure evidence: session `69918`, launch
  chunk `a91429`, return `1`, wrapper elapsed `199.764291`, no timeout,
  truncation, wrapper error, or credential variables. Exact terminal is
  `RuntimeError: V36 candidate count mismatch`.
- Root result is uid 501 mode `0600`, 24,715 bytes /
  `ea6666ca7f1265377bdda4492ad8fb2c53ee620dfd42c821d24ef5ca55dd5c2f`;
  embedded output is 21,286 /
  `094c81669dba218a55122645a3969155989fb39c03ba25cf3c3948e8d7467ca3`.
  Exactly `candidate.vuDWtK0T` and run
  `20261014T075525Z-4dcccf5a` were allocated. The run remains `received` at
  0/0 with null Coder session/error and empty artifacts/results.
- Setup/readiness/profile/doctor/loop-init/bindings/offer passed. Sealing is
  complete without errors: preservation 281,296 /
  `73966dd258cd96b855f8091392ad4309cb110071f164710d0ebd86e18afcca24`;
  stop 241 /
  `bbc6de901b1f01586df4b6b662d50932b72a104cf7e6ceef0ddbb742fdc28c58`;
  final index 18,496 /
  `3712d186cc0e43732aed03c29d8aa9226d16c5cab93c5e48ff4049bcd47ae3ac`;
  completed tree 44,322 paths / 948,848,595 bytes /
  `86c961b967d997e7fa21810b8b6e4ab0ca81223a72eea2b14043008adf28bd16`.
- Candidate count is exactly 22. V37 result/suffix/init and verifier budgets
  are consumed; final acceptance/auth/formal remain unconsumed and
  unauthorized. Never reuse V37 root/result/candidate/run.
- Cause is the full historical live-count defect class: V34, V35, and V36
  validators compared today's live candidate total to their immutable recorded
  21. V38 checks those recorded counts structurally (21/21/21), checks V37's
  recorded 22 structurally, and leaves evolving live-set authority only in the
  phase-aware central predecessor contract and exact postprepare final gate.
- V38 preallocation is exactly the 22 retained names. Postallocation, if later
  authorized, is exactly those names plus one unpredictable current candidate.
  Unknown extra, missing, duplicate, substitution, second-current, and
  current-is-predecessor fixtures all reject.
- New trusted non-product helper is only
  `tools/loop_engineering/m3s_v38_source_freeze.py`. It derives only from
  sealed V37 driver, binds the complete V37 stop, keeps command schemas
  23/23/15 with one `mktemp` and one `loop-init`, and runs the actual complete
  60-gate graph with process gate before any V38 `mkdir`.
- Final inventory is 0 staged / 15 modified tracked / 164 ordinary untracked;
  the fixed V38 root is absent. Static AST/compile, Ruff F/B/S, contract-hash,
  phase/result, candidate-set, acceptance-negative, and 60-gate full pre-root
  validation pass with byte-equal no-write snapshots.
- Next boundary: independent controller reconstruction and acceptance of one
  exact V38 root-only invocation. This cycle grants no root, prepare,
  accept-final, allocation, authentication, role, test, render, evaluation,
  inference, publication, commit, push, cleanup, media mutation, `--last`, or
  `resume_liveclip.sh` authority.

The sole authoritative Living ExecPlan is
`docs/exec-plans/liveclip-agent-runtime-v2.md`.

## Current checkpoint

- The sole V36 allocation-free verifier is consumed immutable failure
  evidence. It launched once in session `55489` (chunks `40e44c` / `973250`),
  exited `1` after `28.708372417` seconds without timeout/truncation, emitted
  empty stdout 0 bytes /
  `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`,
  and emitted 1,651-byte stderr /
  `620a90d8c4a93b105f5bc2ddf7554f53b478bf4a13ae07c08bcb6e31b3bcc2a8`.
  Terminal is `RuntimeError: V32 result terminal evidence mismatch`. Forty
  gates passed, `m3s_v32_blocked` failed, and 17 later gates did not run. V36
  prepare never launched and is abandoned non-retryable.
- Pre/post correlation proves V36 documents/root unchanged, Git-status digest
  `75277a0966472fea6b9b03b91b35351ab373e953c6f790346e24ad3fbf2a9990`
  unchanged, inventory 0/15/162, 21 candidates, and all three V36 reserved
  results absent. One postflight JSON/Python boolean typo was read-only; final
  explicit correlation passed.
- Cause is exact: immutable V32 result 3,570 bytes /
  `004e8ad6abce6da0ffd0a32cbfbfb943536cf2e28f21a0c7d4fed0e77cb675ce`
  binds prepare argv SHA-256
  `7fc7f513179056fe2dfd6862e65e3f10f9e30bbe6a3c0e7a14a33403419fc798`
  and ends `RuntimeError: future V33 result fixture mismatch`; V36 incorrectly
  rolled that historical string to `future V36`.
- M3S-v37 is the sole current boundary. Trusted helper
  `tools/loop_engineering/m3s_v37_source_freeze.py` is retained as the one
  untracked V37 helper, so inventory remains 0 staged / 15 modified tracked /
  163 ordinary untracked; full Git-status SHA-256 is
  `fd48f60e00cfe42be03dd1aa4d913053e6fa8065e781f907dbd79a86b4410911`.
  It derived only from sealed V36 bytes, restored exact V32 `future V33`
  evidence, bound complete V36 root/verifier evidence, and passed the complete
  59-gate pre-root graph with no write.
- The separately authorized V37 root-only invocation is complete and
  independently accepted. Tool session `47023` exited `0` after approximately
  60.2 observed seconds; exact aggregate wall/chunks were not surfaced. It had
  one compact JSON stdout, empty stderr, no truncation, and phase/result
  `M3S_V37_ROOT_ONLY` / `M3S_V37_READY_FOR_CONTROLLER_REVIEW`.
- Fixed V37 root and its `home`/`tmp`/`receipts` directories are uid 501 mode
  `0700`; home/tmp are empty and all files are uid 501 mode `0600`. Exact
  driver/controller/source/writer/self-check/final-index identities are
  respectively 438,264 /
  `d23f1513e8130da7d389697d33c543770453648ad1d5be5ca117d31f5e97094d`,
  9,784 /
  `d00250be433935fa1dc69d1f8ff39b7976b215a5dde62d946a1a45c318fcd8ed`,
  524 / `ba745a5d94b04d430842beb916de82fe32422c22d064007085dad0868fb5259c`,
  72 / `b09abfdb6b28cebf2a5c787da2bb923902aeeba2a57af61d3c6c1330ac8fd06c`,
  8,072 /
  `18fc6544f84ea687b15b942a450f1b7b7341bd4e67ef4598e665c573094a2f59`,
  and 1,999 /
  `c48aadacb754bce93e6ffe9b090fa58304c09b8a1b698d159773f6c313d6f53a`.
  Final index binds root argv
  `fb72c714707fae63b0a165daa719514df6a33a2bfd1e8f048410e431579c114c`;
  self-check records all 59 gates and no-write `PASS`.
- All three V37 reserved results remain absent and candidate count remains 21.
  Only the root budget is consumed. The current documentation boundary freezes
  one allocation-free `verify-prepare` invocation and a distinct later
  bounded-wrapper `prepare` invocation against the same final documents. No
  document byte may change between independently accepted verifier PASS and
  prepare launch. Neither command is executed or authorized by this closure.

- M3S-v35 root-only remains accepted immutable evidence. Its root is uid 501
  mode `0700`; immutable driver, controller acceptance, and final index are
  respectively 425,920 /
  `349309ec7bd676d8bd2d5b34b69d0fc1e57683fe864d4287ad29b2f8069aaafd`,
  8,153 /
  `b25ef8c63eb64cbe9d40de696faef654b51473e266e94fb198e5fea13a5fb14a`,
  and 1,999 /
  `b3a31500402e750f658c1c2006ae43309597f2ca89016b0b47a94cd5b7785172`.
  Its three reserved results were absent at verifier launch and remain absent.
- The sole V35 `verify-prepare` invocation is now consumed immutable failure
  evidence. It launched once with chunk `7a2cc9`, no session, exit `1`, wall
  `0.026321792` seconds, no timeout/truncation, empty stdout 0 bytes /
  `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`,
  and a 1,652-byte stderr traceback /
  `371b0b9ab0da298aa7e234544e3590eb078b453e8e52ac2eb95c6755366c961c`.
  Exact terminal error is `RuntimeError: controller acceptance semantic
  mismatch` in `verify_prepare -> validate_controller_acceptance`, before
  `read_only_gates`; all 57 gates are `NOT_RUN`.
- Preflight matched the accepted documents, sealed root/driver/wrapper/
  receipts, verifier argv/vector/envelope, inventory 0/15/161, 21 candidates,
  and reserved absences. Postflight proves documents and complete V35 root
  unchanged, git-status digest
  `e5cabb718a23026fe117168751b9aabc0126e1337caeba2f934c2fe805fae82d`
  unchanged, inventory 0/15/161, candidate set 21, and all reserved results
  absent. The verifier budget is consumed. V35 `prepare` was never launched,
  remains unauthorized, and must never be retried.
- Root cause is exact: `controller-acceptance-v35.json` embeds the actual V34
  predecessor closure, while sealed `candidate-driver.py` line 6627 compares
  it to stale `PREVIOUS_M3S_V33_CLOSURE`. This is an internal semantic-model
  mismatch, not changed evidence, authentication, or process state.
- M3S-v36 is the sole current design boundary. New trusted non-product helper
  `tools/loop_engineering/m3s_v36_source_freeze.py` adds exactly one untracked
  path, making final inventory 0 staged / 15 modified tracked / 162 ordinary
  untracked. The helper is 34,717 bytes /
  `af81d42d4fe9840b9b71c050a65e8302dd461f0a6d9d587f80e317f588968eab`;
  its unique raw source is 2,859 bytes /
  `206d0b1a9dc5583a080e1e84996825416de6de2553a6c72b8a9098349f91dfdb`.
  It derives only from sealed V35 driver bytes, rolls V36/V37
  metadata, binds the complete V35 root/verifier closure, and replaces the
  stale inline V33 comparator with one pure immediate-predecessor semantic
  model used by both receipt validation and fixtures.
- The independently derived credential-free V36 driver is 430,756 bytes /
  SHA-256
  `b77d5b05aed9cd86f8d17100f6e0a99e7c522ad38f79d015d61fc75a6e13cfa3`.
  Candidate/formal/initial/policy/trusted contract hashes are
  `bf6198fea10ec65109bff208d5fc8e9843b031646962967389d705d22684ebe7` /
  `70b63e787c7195e254bee058d98ada477ca411edfe637d101551dfb210124ae3` /
  `034bf76f031f9da71b69d988cbcf15fb7674c24f7f455b3a72b8bacc4e1829c3` /
  `f24b16b458ad26161be697a410848aa5da0524e77329d90771508ed7be3bd97a` /
  `3fad3588585c494c461f4e4c3b16885401b312210a6778d097799d5170cb9f1b`.
- Static actual-model validation accepts only the full V35 closure. V33 and
  V34 substitution, missing, mutated, and extra predecessor fixtures reject
  on `predecessor_closure`; wrong-root rejects on `root`. Actual V35 stopped
  evidence and current 0/15/162 documents pass; stale 156/159/160/161 reject.
  AST/compile, project-local Ruff F/B/S, phase-source policy, exact 23/23/15
  command surface, 58 gates, one `mktemp`, and one `loop-init` pass.
- M3S-v36 root-only is complete and independently accepted. The sole
  invocation exited `0` in `1.062082542` seconds, chunk `c7a279`, with no
  session, timeout, truncation, or stderr; phase/result was
  `M3S_V36_ROOT_ONLY` / `M3S_V36_READY_FOR_CONTROLLER_REVIEW`. Root and its
  `home`/`tmp`/`receipts` directories are uid 501 mode `0700`; home/tmp are
  empty and every file is uid 501 mode `0600`.
- Immutable V36 files are driver 430,756 /
  `b77d5b05aed9cd86f8d17100f6e0a99e7c522ad38f79d015d61fc75a6e13cfa3`;
  controller acceptance 8,799 /
  `b49b5f5d3b380866f75410a65f390b4d45fcb2f15eca10c8f811a3a4a47687dd`;
  source receipt 524 /
  `afffcb591673791706e53db372ecbf1054e7497655c566709a43c578e556c500`;
  writer self-test 72 /
  `25136877d8ba255deff9b18bb1e739213619e55a30466855f42ae46a7a17ce23`;
  self-check 4,070 /
  `78c41f930dc25b0dcf591221e6e21079ac590b7e14261d01e9dcdff729c3fbd0`;
  and final index 1,999 /
  `69bede8bac7bfcfd8f534d0e79ae7932e4929f2946905312a216f84541521213`.
  Final index binds root argv
  `70e659e45fb34c8cf7db68c3c0afb2a7d9adc9ac7f476de10a5de0d9b51f1c3d`.
  Controller is accepted-before-root; source/writer/self-check PASS.
- Two postflight correlation drafts referenced nonexistent helper symbols
  after root success. They failed read-only, ran no driver phase, and made no
  mutation; final explicit correlation passed. All three reserved V36 results
  remain absent, candidate count is 21, and inventory is 0/15/162. Only the
  V36 root budget is consumed.
- The current boundary freezes distinct one-use `verify-prepare` and later
  bounded-wrapper `prepare` commands against one final ExecPlan/STATUS
  generation. The verifier is allocation-free, uses V36 private home/tmp,
  calls the actual 58-entry gate graph with process gating, and writes no
  result. Prepare remains separately unauthorized until the verifier PASS is
  independently accepted. No documentation byte may change between accepted
  verifier PASS and prepare launch; any change invalidates both commands.
- The exact next safe action is independent reconstruction and one verifier
  dispatch only. Verifier failure stops without retry. PASS is not prepare,
  final-acceptance, authentication, or formal authority. No prepare/result,
  suffix, candidate, run, acceptance, authentication, role, test, render,
  evaluation, inference, or publication is executed by this closure.

- M3S-v33 `prepare` is consumed immutable preallocation-stop evidence. Its
  exact envelope ran once: tool exit `1`, wall `0.266359667` seconds, chunk
  `6e8a0a`, no session/truncation. Wrapper phase
  `M3_SUCCESSOR_PREPARATION_V33` elapsed `0.322461` seconds with no timeout,
  output truncation, wrapper error, or credential variables. Retained result
  is uid 501 mode `0600`, 3,931 bytes / SHA-256
  `9a9967ca5bde99aa34aa2b7ffe82bc95c422c9f0c852ad95f11c6fc792ea866b`.
  Exact error is `RuntimeError: original status counts mismatch` at
  `main:7642 -> execute:7232 -> read_only_gates:3839 ->
  validate_original:2560 -> require:735`.
- V33 expected 0 staged / 15 modified tracked / 156 ordinary untracked while
  the accepted pre-V34-helper full inventory is 0/15/159. The result budget is
  consumed; the stop preceded `mktemp`, so suffix/init remain unconsumed but
  abandoned. Candidate count is 21. No candidate, run, offer, acceptance,
  authentication, role, test, or downstream phase ran.
- At its accepted post-root checkpoint, M3S-v34 was the prepare boundary.
  Trusted helper
  `tools/loop_engineering/m3s_v34_source_freeze.py` adds exactly one untracked
  path, making final inventory 0/15/160. It derives only from the sealed V33
  driver, rolls current/future result metadata to V34/V35, binds the complete
  V33 stopped closure, and changes the executable original-worktree count to
  exactly 160.
- The independently derived V34 driver is 419,288 bytes / SHA-256
  `376a6a65e907dd37024e9c615dd8e80e2fd0ab429b1e7d588bf7ffb67a8aa311`.
  Unique raw source is 2,859 bytes / SHA-256
  `684f9b30a855bff3066cbdb4c1a702ba17f9b3192cdec2f9f454d0d0e9837d79`.
  Candidate/formal/initial/policy/trusted hashes are
  `bf6198fea10ec65109bff208d5fc8e9843b031646962967389d705d22684ebe7` /
  `70b63e787c7195e254bee058d98ada477ca411edfe637d101551dfb210124ae3` /
  `034bf76f031f9da71b69d988cbcf15fb7674c24f7f455b3a72b8bacc4e1829c3` /
  `a710a56da3b840eb34a474195562b63956720608cd5e892687b87ffc5c543ab5` /
  `414fc9a8eca07cff7bf0ff68443627381a143f5da51916678c8e86b72619f64f`.
  Helper is 48,066 bytes / SHA-256
  `1a105b430a1c42357f817d86cd7ab077866605ec20244023621eb4577642ca89`.
- V34 root-only completed exit `0` in tool wall `1.059372208` seconds, chunk
  `d914f4`, with no session/truncation and empty stderr; phase/result was
  `M3S_V34_ROOT_ONLY` / `M3S_V34_READY_FOR_CONTROLLER_REVIEW`. Root is uid
  501 mode `0700` with exact driver, empty private `home`/`tmp`, and private
  receipts; directories are mode `0700` and all files uid 501 mode `0600`.
- Immutable root files are controller acceptance 7,776 /
  `37bc9a44abfec3563591f257a7da73784ee60735cd80ae4426d03d5bc3ca3b26`;
  source receipt 1,285 /
  `b886fb83a89dbc6e16d75a0e55bf9a5f1b7d7e9de598b30c59fe8632a23750b1`;
  writer self-test 124 /
  `574319210cc14fa09c4c4c2ad93e3a09c9de3d58422993ae40486a09591d6d54`;
  self-check 9,611 /
  `bbeca7385bb70baeb192d5bd9205e7e95eec7a34545dd1e897fafaf185cab579`;
  and final index 2,434 /
  `06cd81b2ee35260a9362c3f9721c98e84aa250e02da62433d4b845e70ff0c5b1`.
  Controller is accepted; source/writer/self-check PASS; final verdict is
  `M3S_V34_READY_FOR_CONTROLLER_REVIEW`.
- V34 static validation invokes the actual authenticated derived
  `status_counts()` and `validate_original()` functions against final document
  hashes and authoritative full-path Git status before prepare. Exact
  0/15/160 passes; stale 156 and 159 negatives reject. The corrected V34
  current/V35 future runtime result fixtures, all 63 safe preallocation gates,
  39/12 receipt domain, one `mktemp`, one `loop-init`, two-command surface,
  and absent auth/role capability also PASS statically.
- V34 successor result is now the immutable stopped receipt recorded above;
  final-controller-acceptance and auth results remain absent. Candidate count
  is 21. V34 root and prepare-result budgets are consumed; suffix/init are
  abandoned unconsumed. Its accepted prepare boundary is non-retryable;
  `accept-final`, auth, and formal work remain unavailable.

- M3S-v33 root-only is complete and independently accepted. Its one
  invocation exited `0` in tool wall `0.780234208` seconds, chunk `e2e910`,
  with no session/truncation and empty stderr; phase/result was
  `M3S_V33_ROOT_ONLY` / `M3S_V33_READY_FOR_CONTROLLER_REVIEW`. The private
  root is uid 501 mode `0700` with exact driver, empty `home`/`tmp`, and
  private receipts; all files are uid 501 mode `0600`.
- Immutable V33 file identities are driver 412,417 /
  `b5cc316bb00a0c6aad40249af31526cac9ec9c8813ed51d7b057e077a496336d`;
  controller acceptance 7,498 /
  `9de383f56cdc1102354700732f8e84dafe96504ac7c6c3c64f608b91bb9d2867`;
  source receipt 1,285 /
  `1fcf5cf63803ae13fd73cfda756e2db6ad5e959d38c20bc0aa668e3a8b5718ab`;
  writer self-test 124 /
  `3798abbd6c00a70962899c30dc17fa3d2d1a15f81a2de34d0704fc1082f15955`;
  self-check 9,051 /
  `303c6369b0d6bf759feecbad6dcb418811f7bfadb70e8c1accaec5cdd8e03a25`;
  and final index 2,434 /
  `70642506faab1a597a3e7892c235faa86c6221e5f1743ff0b1bbbd08d3a49d4a`.
  Root argv binding is
  `bb0dc4b0c2ce295cf29906044413f8a87808a06ab9a133c85e7a003b650d4fda`.
  Source/writer/self-check are PASS; final verdict is
  `M3S_V33_READY_FOR_CONTROLLER_REVIEW`.
- V33 final-controller-acceptance and auth results are absent; candidate count
  remains 21. Its root and prepare-result budgets are consumed. The failed
  prepare boundary is non-retryable; suffix/init are abandoned unconsumed and
  `accept-final`, auth, and formal authority remain unavailable.
- The V33 source-freeze used one filename-filtered `find` that traversed
  retained candidate HOME entries while locating Ruff. It emitted no
  authentication path or metadata and opened/read/hashed/copied/printed no
  authentication content. Future validation must use the known project-local
  Ruff path and explicit targets, never broad candidate-HOME traversal.

- M3S-v32 prepare is consumed immutable preallocation-stop evidence. The exact
  envelope ran once; tool exit `1`, chunk `f6b933`, wall `0.147461833`
  seconds, no session/truncation. Wrapper phase was
  `M3_SUCCESSOR_PREPARATION_V32`, return code `1`, elapsed `0.208103`, with no
  timeout, output truncation, wrapper error, session, or credential variables.
  The exact terminal cause is `RuntimeError: future V33 result fixture
  mismatch` at `main:7542 -> execute:7105 ->
  validate_active_phase_names:1377 -> require:731`.
- The retained no-replace V32 result is uid `501`, mode `0600`, 3,570 bytes /
  SHA-256
  `004e8ad6abce6da0ffd0a32cbfbfb943536cf2e28f21a0c7d4fed0e77cb675ce`.
  V32 root and prepare-result budgets are consumed. The stop preceded the sole
  `mktemp`, so suffix and init are unconsumed and abandoned in V32. Candidate
  count remains 21; no suffix/candidate/run/offer/auth/role/test/downstream
  phase exists. Final-acceptance and auth results remain absent.
- Root cause is exact: the V32 runtime fixture constructs its allowed current
  result as V31 and its forbidden future result as V32. The already-created
  current V32 result is therefore rejected before allocation. V31 remains
  immutable earlier `BLOCKED_NO_SAFE_DISPATCH` history; V32 itself must never
  be retried, repaired, or reused.
- M3S-v33 is the sole current design boundary. New helper
  `tools/loop_engineering/m3s_v33_source_freeze.py` is 46,513 bytes /
  SHA-256
  `ff30f1cf4e5a0016c4b673b432a2ac31c198ad9760ced2f73b841c30110a9e55`;
  unique raw source is 2,859 /
  `3278e153783a21d80e4b3b74b29ecce847cbed27ede6deec7b70c56efa0c5bd5`;
  and the independently derived driver is 412,417 /
  `b5cc316bb00a0c6aad40249af31526cac9ec9c8813ed51d7b057e077a496336d`.
  Candidate/formal/initial/policy/trusted contract hashes are
  `bf6198fea10ec65109bff208d5fc8e9843b031646962967389d705d22684ebe7` /
  `70b63e787c7195e254bee058d98ada477ca411edfe637d101551dfb210124ae3` /
  `034bf76f031f9da71b69d988cbcf15fb7674c24f7f455b3a72b8bacc4e1829c3` /
  `c318213c5d701865c99bd213196ab8b0bf38137abf29327589f8be838a00369e` /
  `f7e2d60b0289588456f4df8efc44839c2644b8bb250465c36c16c9ea7419d126`.
- V33 preserves the two-command `prepare`/`accept-final` surface, 28/39/12
  receipt domain, exact 21 predecessors, protected credential omission, one
  `mktemp`, one `loop-init`, and no auth/role/resume capability. Its runtime
  fixtures accept only the current V33 result and reject exact future V34;
  regression, omission, and substitution mutations are explicit. Helper and
  derived driver pass AST/compile and Ruff F/B/S; contracts match; 62 safe
  preallocation fixtures PASS through `IMMEDIATELY_BEFORE_SOLE_MKTEMP`.
- The fixed no-replace V33 root is sealed and immutable. Its root budget is
  consumed; prepare-result, suffix, init, offer, final-acceptance, auth, and
  formal budgets remain unconsumed and separately gated. The closed prepare
  boundary is 25 Python-argv strings and a 17-string direct-wrapper vector;
  exact byte/hash identities are reported only after both documents close.
- Candidate count remains 21 on branch `main` at
  `2f361fcddc0e63ae62ee62826e27b54bb8204c53`. Full-path inventory is
  reconciled after final closure. Authentication and formal authority remain
  unavailable; this post-root cycle creates no result, suffix, candidate, run,
  offer, final acceptance, or downstream evidence.
- The single authorized formal dispatch for `candidate.5nZWpynN` / run
  `20261013T215618Z-941df9ff` is consumed immutable terminal evidence. Process
  exit was 2; tool session `73148` terminated; launch/terminal chunks were
  `dd11e1` / `ea50cb`; observed wall was `234.903325293` seconds; diagnostics
  were not truncated; no retry ran.
- Final `state.json` is 9,406 bytes, mode `0644`, uid 501, SHA-256
  `92428fa2311798509fa658a5d425b5bab558415c72827e99b141fa4fca0f902e`.
  State is `blocked`, cycle/code-cycle 2/0, null Coder session, empty command
  results, and `last_error` `plan repair budget exhausted`. Planner artifacts
  `001.json` and `002.json` are respectively 10,607 /
  `81081997445f3882d0dec34aadcb2c89a5778d1d0e4b3dd7562f709853de506a`
  and 11,089 /
  `0f1a624c79674b82d9e81946965a44d587ee85379eecc5bf7ce98a988c06bbc7`;
  both verdicts are `NEEDS_INPUT`.
- The correlated defect is candidate-visible provenance. Preparation-time
  trusted context contains no literal external acceptance of the final
  record/policy/candidate, current sealed ToolchainManager source/snapshot
  fingerprints, and dispatch. No Coder, Runner, Reviewer, Tester, Gateway,
  test, product edit, rendering, evaluation, inference, service, or
  publication ran.
- M3S-v31 root-only is complete and independently accepted. Its one invocation
  exited 0 in tool wall `0.645027041` seconds, chunk `a63ef2`, with no session
  or truncation, empty stderr, phase/result `M3S_V31_ROOT_ONLY` /
  `M3S_V31_READY_FOR_CONTROLLER_REVIEW`. Only the root budget is consumed; no
  prepare result, suffix, run, final-acceptance transport, authentication, or
  formal budget is consumed. The canonical aggregate design is 8,242 bytes / SHA-256
  `8a7644183a20a2afba6833cb4bcee31ea64553cb3a035523fa69a934545776df`.
  Component hashes are terminal closure
  `a5f42d591bce6309906e575cd89373e5f471ad59bdd297c19ffb6064f0e81791`,
  command construction
  `166bb64e47124e2a696f14c72e76c67c96e09f70ceff0ef910851595e27624a8`,
  preparation `9500d5e4c6c9faf791f3d8b33bb6b035a585e7276b386a4a2e90bba935cbc076`,
  offer `d582d546e88bb2ce359d49d11654ab2a0efe490a253de3844b5a08e2856e0121`,
  final acceptance
  `2c41c7a37e95a7d3cfc2c4b9f9d2610d8b56cfc59ec3193d6060882d61c27198`,
  and future formal dispatch
  `bf1d05c8ff9b1a5c7f158a3409a3c4fea1f4edd34fe94b41dd794801b1626c68`.
- The unique raw preparation source is 2,800 bytes / SHA-256
  `3543079a1a186bcef70329e1445b3f71060f3090d7241571e0cb012c8fdcd8c6`;
  the minimum trusted helper is 47,433 /
  `ccf537707fdca1d0aeaee9ba4eaf7e894ac82e1cd5956b18b8bf3ed164e44548`;
  and the independently derived two-command V31 driver is 399,161 /
  `20aa989f3065f688b7e7476fe7e743d5ca1bbcd353a9d88c667e397c01c18d89`.
  Its candidate/formal/initial/policy/trusted contract hashes are
  `bf6198fea10ec65109bff208d5fc8e9843b031646962967389d705d22684ebe7` /
  `70b63e787c7195e254bee058d98ada477ca411edfe637d101551dfb210124ae3` /
  `034bf76f031f9da71b69d988cbcf15fb7674c24f7f455b3a72b8bacc4e1829c3` /
  `1c9c97463a744ca7560b8b49458cb14d6f9f924e1566ea96a99b9bfa144bff90` /
  `51977559d7f1fd05c02431033edee8c31e7dea37c1ce7888e00740ab54c584d8`.
  Correlation remains branch `main`, HEAD
  `2f361fcddc0e63ae62ee62826e27b54bb8204c53`, 0 staged / 15 modified /
  157 untracked after the one new helper and exactly 21 candidates.
- The fixed V31 root is uid 501 mode `0700` with exact entries
  `candidate-driver.py`, empty private `home`/`tmp`, and private `receipts`;
  all regular files are uid 501 mode `0600`. Driver is 399,161 /
  `20aa989f3065f688b7e7476fe7e743d5ca1bbcd353a9d88c667e397c01c18d89`;
  root acceptance 6,771 /
  `ddf1a7fdf68f2d3a1e6715119136c0113667331ccce5d5d0891a862b87f8237c`;
  source receipt 1,372 /
  `4cc0999117afcbe320e1bba08c406fff7400ee61b0b982851cc21da091afdd8b`;
  writer self-test 124 /
  `891f9425400f3cbd37e2c41286aa485fee8d2f3fec43e64b733c07a36e41725d`;
  self-check 13,553 /
  `02f374200c93cd13132f988330f2d03fc8b198e61595cbf6f8ac1d397b12ecbb`;
  and final index 2,435 /
  `4265e1e266b696d6d33f7717680d157216bcfdcde7211577d1e1da5d8b5ead5b`.
  Root argv hash is
  `797c62711a8d29ef5535facb24a09deca1cf75fc59ce561d42a4010d82973d9d`.
  Source/writer/self-check are PASS; final verdict is
  `M3S_V31_READY_FOR_CONTROLLER_REVIEW`; both reserved results remain absent.
- Post-root runtime-equivalent static validation closes V31
  `BLOCKED_NO_SAFE_DISPATCH`. The sealed `SUCCESSOR_V31_RECEIPTS` tuple has
  39 names after adding the controller-acceptance offer, while
  `historical_receipt_contract_self_test()` still requires 38 and its
  11-name `SUCCESSOR_ONLY_RECEIPTS` omits that offer. `read_only_gates()` runs
  the self-test before the sole `mktemp`, so the exact first failure would be
  `RuntimeError: successor receipt fixture count mismatch`. No prepare was
  launched; result/suffix/init remain unconsumed but unusable in V31.
- V31's intended authority separation remains evidence: credential-free
  preparation would stop at a candidate-specific offer, a separately accepted
  exact-byte `accept-final` would transport external authority, and formal
  dispatch would remain a third boundary. The driver may not generate
  authority. The retained V30 candidate/run and M3A-v1 credential state are
  not reusable; any fresh successor and authentication require new explicit
  authority.
- The operator's exact instruction `go` authorized one fresh opaque
  authentication handoff only for accepted immutable `candidate.5nZWpynN` and
  pristine run `20261013T215618Z-941df9ff`. The M3A-v1 root-only prerequisite
  and its single handoff are now independently accepted and consumed.
  Authentication success does not authorize `loop-run`, any formal role, or
  engineering acceptance.
- M3A-v1 root-only completed exit 0 in tool wall `0.216757667` seconds,
  chunk `1092de`, with phase/result `M3A_V1_ROOT_ONLY` /
  `M3A_V1_READY_FOR_CONTROLLER_REVIEW`, empty stderr, and no session or
  truncation. Root/private directories are uid 501 mode `0700`; root entries
  are the mode-`0600` driver, empty private home/tmp, and private receipts.
  Driver is 22,180 /
  `c513d37f32e171a131ce336d7e419854d42beacc4fdc997ab8324bfebc4202f4`;
  controller acceptance 2,936 /
  `097ea697029e77b3bd6b09f20ec9e66b0800e42a142bc20a90ab82d51d41d4c5`;
  source receipt 826 /
  `55008378a546056b636db14b2e0976728f3cb36fb8f7722cf451252fbd6616d1`;
  writer self-test 119 /
  `8f6468265d8b1937f0cfb83c606f72ce9bf615f374a7caa30bb53549d191b116`;
  self-check 2,598 /
  `dd2bb00abcb4942c697f4e089adc409e6ab9d863b8e48858ec151cc3db3ad90c`;
  and final index 1,916 /
  `f1f20aa6c97e74f3e907976a55ad7bd7d2b13fdcc7980cde8cb53eef5edf5e78`.
  Final phase/verdict is `M3A_V1_FINAL_INDEX` /
  `M3A_V1_READY_FOR_CONTROLLER_REVIEW`; root argv SHA-256 is
  `84bb551fd0c6f614c239647b5a0cf7fa0a8e4b6eec97f12153e1042819c95b9d`.
- Root, handoff invocation, sanitized-result, and exclusive-destination
  budgets are consumed, immutable, and non-reusable. The handoff completed
  exit 0 in tool wall `0.325635625` seconds, chunk `abf3e2`, with no running
  session, truncation, or stderr. Its uid-501 mode-`0600` sanitized receipt is
  261 bytes / SHA-256
  `d75b3a8b357f20f4f1d957dba490eca191b31992558473d06902bd6a18326860`.
  Exact fields are `copy_success=true`, destination mode `0600`, destination
  owner uid `501`, format version `1`, login status
  `SUPPORTED_AUTHENTICATED`, phase `M3A_V1_AUTH_HANDOFF`, result
  `READY_FOR_CONTROLLER_REVIEW`, and `sanitized_error=null`. Credential
  secrecy is preserved; no credential content or secret-derived metadata is
  recorded here.
- M3S-v30 is the accepted immutable M3 candidate checkpoint. Its accepted
  candidate-recovery wrapper returned `0` after `204.294412` seconds with no
  timeout, truncation, wrapper error, session, or credential variables. The
  no-replace result is 23,400 bytes /
  `509bbec65b5cb07bc19bf0d9c740c945322209201dc23d322f06e0a7c856de2a`,
  uid 501 mode `0600`.
- Exactly one candidate, uid-501 mode-`0700` `candidate.5nZWpynN`, was
  allocated with exact `home`/`repo`/`successor-receipts`/`tmp` entries;
  candidate count is 21. Its sole run is
  `20261013T215618Z-941df9ff`, received at cycle/code-cycle 0/0 with null
  Coder session and error and empty artifacts/results. State/events are
  9,210 / `16168ec80f3669ac41aca51259e2c74695df521a1fa9b5b1ca777a9150857c8e`
  and 144 /
  `05548bec4262b27010afef13fcf2a80164b5d4b146b9fc956c888975f3415e3b`;
  the unexecuted future loop argv hash is
  `ae53455123cf594c35d26a7c19abdae78d5dca691cca6bdf4b9f43b3536b7aef`.
- Dry-run capture/validation, setup, readiness, credential-free profile
  staging, doctor with proven termination and `safe_to_seal`, loop-init,
  controller transport, policy/toolchain binding, preservation, and final
  binding all passed. Their exact size/hash evidence is recorded in the
  Living ExecPlan. Final bindings are 5,408 /
  `bfe7219b055694f54a7f7f9ed64aa59dac2bfd20f98ed056054c19ec5ef55ca6`.
- Sealing completed with no errors and verdict
  `M3_SUCCESSOR_PREPARATION_V30_READY_FOR_CONTROLLER_REVIEW`. Final index is
  17,607 /
  `dfa502322327d4ee6a3f67227ecbbc3544416e052cb146bfe7220a03c972e3de`;
  repository manifest is 27,411 paths / 580,703,161 bytes, file 6,139,501 /
  `14755daf1ecd8d6d6059491ecfbbfa2691edb4107ffc8a13426b954ad5b5054b`;
  attempt manifest is 44,317 pre-index paths / 936,263,099 bytes, file
  12,176,262 /
  `c83ee0354e8c57fe5f106b841b35b31d91f71d48b1be6154dae82a190ed56d4c`;
  completed tree is 44,319 paths / 948,456,968 bytes /
  `943e3e3833202f953a9eff3d2e266effe37dd81d7e0747a38cbc4b8781fa4b9a`.
  Candidate worktree and toolchain source/snapshot fingerprints are
  `926ae7802440da7e035724f55a50b8cc1fee79333dffd2dca380c53611e16f57` /
  `4a31e3aa1481dd5802e9e8746f9e85918eb21ec10edc6af683ff672684dfe02c` /
  `db4508dbe46589cb29aa1093f83ceb4c0fdacc8878accfc521583fd00ce1152b`.
- Candidate inventory is 0/15/73; delivery remains 0/15/156.
  Result/invocation, suffix, and init budgets are consumed and non-reusable.
  `auth-handoff-v30-result.json` is absent. No credential, formal role,
  additional test, rendering, evaluation, inference, publication, commit,
  push, cleanup, or source-media mutation occurred.
- Acceptance categories remain separate: the root checkpoint proves the
  driver/bootstrap boundary, and the candidate checkpoint proves preparation,
  pristine run initialization, preservation, and sealing. The M3A checkpoint
  proves only the sanitized opaque-handoff outcome. None is a formal-loop,
  product, Runner/test, render, evaluation, inference, or publication
  acceptance.
- The accepted handoff left the run received at cycle/code-cycle 0/0 at that
  historical boundary. The separately authorized formal invocation later
  consumed the run and stopped in Planner as recorded above. Candidate and
  delivery inventories remain protected. V13 and M3A-v1 auth/HOME are
  non-reusable.
- Historical root-only evidence remains immutable. Its accepted invocation
  completed exit 0 in tool wall `0.866240208` seconds, chunk
  `596167`, with phase/result `M3S_V30_ROOT_ONLY` /
  `M3S_V30_READY_FOR_CONTROLLER_REVIEW`, empty stderr, and no session or
  truncation. The root is uid 501 mode `0700` with exact entries
  `candidate-driver.py`, empty private `home`/`tmp`, and private `receipts`;
  every file is uid 501 mode `0600`.
- V30 immutable identities are driver 383,064 /
  `520f6a6ccb243ae970d1160c3c94935eed348dde4453368abd2355c8d6d5038f`;
  controller acceptance 6,787 /
  `fa3e73554d00de49e18ae03e8f2eb449026707178c18d5c905e458a177502133`;
  source receipt 3,846 /
  `2336f2655d8a15ac16c5a50feea5af13d8c20ebae8c67de2f05fe481c8084a37`;
  writer self-test 156 /
  `db80f9c5c124983960a65bfae770fac99f4948cf72b0995930395ec3e3c23d75`;
  self-check 7,843 /
  `3d4e9ecf4ea13e1b6f7e1cc5b07a917e6de7440b21cb9224f69d7ef32f041b89`;
  and final index 5,452 /
  `1b3e06d653d93ef52615bf9369a33927c0cbf186e3b00b89d78a9055237a850b`.
  The index binds root argv
  `bf89b8bfd3d1cae0430f3e1c27cd3efa0760d1cf54f7c826d728d84887cd6386`,
  main/`2f361fcddc0e63ae62ee62826e27b54bb8204c53`, inventory
  0/15/156, and 20 candidates. At that checkpoint both reserved results were
  absent.
- Root/controller-acceptance budgets are consumed and immutable. The consumed
  one-shot credential-free candidate-recovery boundary used a 27-string
  execute argv, 17-string direct-wrapper vector, non-login `/bin/zsh`,
  immutable `candidate.OlsWg1/repo`, `/dev/null`, inner/outer bounds
  2,730/2,760 seconds, and wrapper/diagnostic bounds 1,048,576/65,536 bytes.
  Its result/suffix/init budgets are consumed; it must never be retried.
  Authentication and formal work remain unauthorized.
- V29 candidate recovery is consumed immutable stopped evidence. Wrapper
  return code was 1 after `0.200325` seconds, with no timeout, truncation,
  wrapper error, session, or credential variables. Exact terminal exception
  was `RuntimeError: future V30 result fixture mismatch`, at `main:7050 ->
  execute:6767 -> validate_active_phase_names:1356 -> require:713`. Its
  27-string argv hash is
  `689dac879f241c51c1c8230eddca5b1e29c938906f401ce02dad9ab387d7e9c1`.
  The no-replace result is 3,726 bytes /
  `cd26e31285042f127ca9e59c6ddf2906784841629883f022368b3e2da36a6c5b`,
  uid 501 mode `0600`. It stopped before gates and `mktemp`; candidate count
  remains 20, no run exists, and materialization through sealing did not run.
  Result/root are consumed; suffix/init are abandoned unconsumed. Never retry
  or repair V29.
- The immutable root is
  `/Users/junhuaxu/Library/Application Support/LiveClip/engineering-candidates/agent-runtime-v2/a822890ace12/trusted-tools/m3-successor-preparation-v29`,
  uid 501 mode `0700`, with exact entries `candidate-driver.py`, empty private
  `home`/`tmp`, and private `receipts`; all files are uid 501 mode `0600`.
  Driver is 376,711 bytes /
  `a8ce70fc86c6105b1a45836b8e8194ddedba3922f0b357fd58a3dc088537ea43`;
  controller acceptance is 7,075 /
  `5f6d96648d4bfc7716bd761668522b5325f6f2495ccb980ce6ab0235b29ca89a`;
  final index is 4,899 /
  `31f75f9a3111ee0b0fb529c2edb8441667b0c226e9d666d7263dda3862592931`;
  root argv hash is
  `a175391f3e4a69d7edf29e4c739bd0ae777f53dfc5bc39b6990146bf334a44b6`.
- Root receipts are source 3,883 /
  `8494faacc6f4903980e6d473aa448f1d07089b81a7c7085c0ba03e1e1ec3e9d5`,
  writer self-test 156 /
  `24bea54c4b5c9e80d93af3f90b7900dd36b21e304d006826441a69d65ff54ff3`,
  and self-check 41,164 /
  `5926ff58de9e9d9aee9d5d9d2cb5fc25624b94abc96cfd02d52b5ae2b43b11aa`.
  The consumed successor result above is now the sixth root receipt;
  `auth-handoff-v29-result.json` remains absent. Candidate count is 20 and
  delivery remains 0 staged / 15 modified / 156 untracked.
- The one accepted V28 root-only invocation is consumed immutable pre-root
  evidence: exit 1, chunk `cd461c`, tool-reported wall `0.000008` seconds, no
  running session, empty stdout, exact stderr `RuntimeError: V27 intermediate
  driver mismatch`, call path `<module>:1007 -> main:1003 -> root_only:969 ->
  require:184`. It stopped before fixed-root `mkdir`; V28 root, driver,
  acceptance, four root receipts, both reserved results, candidate, and run
  remain absent. Never retry or repair V28.
- Root cause is exact: V28's `derive_v27_driver` used active `CONTRACTS` and
  `CONTRACT_HASHES` rather than version-scoped V27 values. Accepted V27 is
  368,663 bytes / `891dabdbb9c7e7243852e5f8d61afe3068d22496e8356a5faa7adb7df544383a`;
  the independently reproduced captured-global mutation is 368,723 bytes /
  `c6aac2b171c8608927b037246f644c2b84e6c52e0a7b2bd48ccec4090a0d59e6`,
  60 bytes larger, first differing at offset 15,478.
- V29 source is 127,886 bytes /
  `d2ab24a5aad4725422755c21e2dfcb7b4050c15979b8a55aab01c779aa138d34`;
  independently derived credential-free driver is 376,711 bytes /
  `a8ce70fc86c6105b1a45836b8e8194ddedba3922f0b357fd58a3dc088537ea43`.
  Contract hashes candidate/formal/initial/policy/trusted are
  `b3956662bf9a9f1b78b6a3352e301d264a0e0e4d27c4f4d18effefd895563fa2` /
  `70b63e787c7195e254bee058d98ada477ca411edfe637d101551dfb210124ae3` /
  `034bf76f031f9da71b69d988cbcf15fb7674c24f7f455b3a72b8bacc4e1829c3` /
  `677b6dd9fa8f14611fff189469f9084a92342fa8b0ef54a96699e5a11aa81cc3` /
  `266f0da0c1409c771495fe01647051d9bf3164a085278bcd86d72ef5e8d0ed50`.
- V29 preserved canonical provenance, the ignored-acceptance path-set repair,
  separate no-follow acceptance validation, 20 exact predecessors, 38
  receipts/11-name delta, one `mktemp`, one `loop-init`, five-stage sealing,
  and protected-path omission before metadata/content access. It has no auth
  command/path/phase/capability and no `--last` or resume capability.
- Historical V29 static closure required unique extraction, deterministic four-step
  V25→V26→V27→V28→V29 derivation, the exact accepted V27 positive and
  captured-global mutation negative, AST/compile, Ruff F/B/S, exact full-byte
  zero-violation phase validation, exact schema/receipt/predecessor domains,
  0/15/156 inventory and 20 candidates.
- The frozen V29 recovery boundary was one ordered 27-string execute argv, one
  17-string direct-wrapper vector, and one literal non-login-zsh envelope.
  Final current documents are independently bound before the sole `mktemp`;
  historical root documents remain immutable evidence and are not equated to
  current hashes. Inner/outer bounds are 2,730/2,760 seconds and wrapper/
  diagnostic bounds were 1,048,576/65,536 bytes. Those identities are now
  consumed and non-dispatchable.
- Historical static inspection proved sealed root/controller/final-index/root-argv and
  wrapper checks, exact 14-phase active policy, and current-document/
  predecessor/inventory gates precede the sole `mktemp`. After allocation only
  materialization, overlay, dry-run, setup, readiness, credential-free profile
  staging, doctor, one `loop-init`, trusted/relational-toolchain binding,
  preservation, and five-stage sealing are reachable. No auth or formal
  capability exists.
- Exact root cause: V29's future-result fixture concatenated version 29 while
  its classifier correctly forbade only versions 30 through 54. The classifier
  returned `[]` for the current V29 result, contradicting the stale expected
  `forbidden_receipt`. V30 permits its current V30 result, forbids V31 through
  V54, requires the V31 result negative, and directly mutates that fixture
  back to V30 to prove the regression is rejected by the same ordered runtime
  algorithm.
- V30 preserves the exact 20 predecessors, 38 receipts/11-name delta,
  canonical provenance, independent document generations, ignored-acceptance
  path-set repair, relational toolchain proof, one `mktemp`, one `loop-init`,
  five-stage sealing, and credential omission before metadata/content access.
  Contracts candidate/formal/initial/policy/trusted are
  `b3956662bf9a9f1b78b6a3352e301d264a0e0e4d27c4f4d18effefd895563fa2` /
  `70b63e787c7195e254bee058d98ada477ca411edfe637d101551dfb210124ae3` /
  `034bf76f031f9da71b69d988cbcf15fb7674c24f7f455b3a72b8bacc4e1829c3` /
  `42c84b0cc1d500ebf85ffda78d68613e559817f0be9c70d236e30182331b4cee` /
  `1de92b92ce62dbfa8f37a286bfdd51550b5230f5b47da48fdfbfe17d03b3e369`.
- The historical post-root reconstruction boundary was completed and its
  single recovery invocation is consumed by the accepted V30 candidate
  checkpoint above. It grants no auth or formal authority and must never be
  reconstructed as current dispatch authority or retried.
- The exact V25 stop is consumed immutable evidence: wrapper exit 1 after
  125.131859 seconds with no timeout, truncation, wrapper error, session, or
  credential variables; result 23,783 bytes /
  `acbd5d763f262c6895e450da00123b79859f8ae980f162b5cde6f34d028ba2eb`;
  terminal error `RuntimeError: successor repository path set mismatch`.
  Retained `candidate.VoU5SVVl` and run
  `20261013T172149Z-741dab1b` are immutable; setup/readiness/doctor and the
  relational toolchain proof passed. The run is received at cycle/code-cycle
  0/0 with null Coder session, empty artifacts/results, and no error.
- V25 sealing completed without errors with final index
  `ef3649ba1623c3addb9a1f1c69069a9ff6535116724aa8fc28b0c6c7350e1a35`;
  repository manifest 27,411 paths / 580,145,044 bytes /
  `5445b78d6dee7bd200eecbad3a40f863a9bbb963ad573ce59526ed508be3ecdf`;
  attempt manifest 44,317 paths / 935,656,694 bytes /
  `2a6eeb6ddb9b85c3574df51ddaddbb56c922456f6d755c9eb881a03b299a22b1`;
  completed tree 44,319 paths / 947,850,511 bytes /
  `50d0d63aa147df6ff9bf5595bfe4bdc6e55c6ceb3bf9bf9a7b449bd980e17665`;
  toolchain snapshot 4,878 bytes /
  `73f30a6332b14675d461b471ea472d540f1644b2cb7bb3e267a9ff33e6ce25a8`.
  Final bindings are absent. V25 result/suffix/init are consumed; no retry,
  repair, mutation, or reuse is permitted.
- Root cause is exact: V25 transported the controller acceptance to the
  intentionally ignored path `.loop/trusted/controller-acceptance-v25.json`,
  then incorrectly added that path to the Git-derived expected set. The actual
  manifest correctly has 2,251 tracked + 73 ordinary-untracked = 2,324 records;
  V25 expected 2,325, with only that ignored path missing and no extras.
- The sealed V25 root remains immutable. Its root-only invocation completed
  once: exit 0 after `0.209801625` seconds, phase `M3S_V25_ROOT_ONLY`, result
  `M3S_V25_READY_FOR_CONTROLLER_REVIEW`. Driver/final-index/root-argv identities
  remain `d71302ef6ca8d7a7ef458326d6664fa7cf81a4dd23657703c13599c49fa18ffe` /
  `4e6ca80019e76f12b9fd2f53533590a77787ebc653182949b7a7729752f303d4` /
  `42437f01adb0d6ecfacccc51d698ee20c30d9819279c16549804d34c532cf10a`.
- M3S-v24 is consumed immutable pre-root stop evidence. Its accepted root-only
  invocation exited 1 after 0.053815666 seconds with no running session at
  `root_only:695 <- validate_driver:543 <- phase_fixtures:427 <- require:145`;
  exact error is `RuntimeError: future phase fixture mismatch`. The fixed V24
  root remains absent and must never be retried or repaired.
- The V24 defect was an impossible fixture: payload
  `M3S_V24_SOURCE_WRITE` was current-version data while the expected result
  was `future_v25:M3S_V24_SOURCE_WRITE`; the classifier correctly returned an
  empty violation list. The independently derived V24 driver fixture itself
  was not the failing fixture.
- V24 fixes the V23 toolchain contradiction by binding the checked-in
  `tools/loop_engineering/toolchain.py` identity (21,534 bytes /
  `4820631747ab71606de10046b9131ef5cf585eac80950461e910f9dc9bf8581a`)
  and candidate-local relations, not unknowable future values. Readiness =
  source-before = source-after = prepared source; the returned private snapshot
  fingerprint must equal its independent recomputation.
- V24 error sealing uses five monotonic stages: overlay; loop-init plus initial
  state/events; trusted context/controller/policy; toolchain snapshot; final
  bindings. This removes the V23 missing-receipt coupling while success still
  requires the full 38-name domain and 11-name delta.
- The exact V23 candidate-recovery invocation is consumed immutable evidence.
  It exited 1 after 108.011975 seconds with no timeout/truncation/wrapper error,
  credentials, auth access, or formal/model work. Its mode-`0600` 23,546-byte
  result SHA-256 is
  `8d038cdbff58c55345d1cc5affcbab869b87c20308012e4a1ded438eab0bfb65`;
  exact error is `RuntimeError: controller-accepted toolchain fingerprint
  mismatch`.
- V23 allocated retained uid-501 mode-`0700` `candidate.qaDKDWkQ`, raising
  candidate count to 19, and initialized consumed run
  `20261013T161821Z-c2843a48`. Setup returned 0, readiness passed, and doctor
  passed with terminated/proven/safe-to-seal lifecycle. The run remains
  received at 0/0 with null Coder session, empty artifacts/results, and no
  error. Result/suffix/init budgets are consumed; no repair, retry, mutation,
  or reuse is allowed.
- V23 stop/preservation identities are 263 /
  `8e440731ea80481c2315013b0c52f79f88e402b5a3048076e891c1a31d36dfd7`
  and 175,517 /
  `578c6b80f9aa1fa8ca5bcac0731c7dd697593a2645c6e0a91f43a5daa1f474de`.
  Its final index is 17,270 /
  `4ccb0ec0c5ab31828505acdb0bf82f57a1fd68cff65bc0fd872341b41f273720`;
  final repository manifest is 27,411 paths / 579,973,034 bytes /
  `cad5b39e484610c890c2efb3fdbc55eb0ec5de3054b82559658cc073b53d390c`;
  final attempt manifest is 44,316 paths / 935,442,608 bytes /
  `fadb42c3c9bf86e149a44801a85edf717203887620de23f052874617b7b4d264`;
  completed tree is 44,318 paths / 947,635,920 bytes /
  `cea591014cc9baced8ac703ef6fb3f7aeabde824eb002bab628fc82b5504bfff`.
- V23 verdict is
  `M3_SUCCESSOR_PREPARATION_V23_STOPPED_SEALING_INCOMPLETE`; only
  `successor-v23-toolchain-snapshot.json` and
  `successor-v23-final-bindings.json` are missing. The stale fixed
  controller values were source
  `d6a7f3f77d2b5edebab0792182a4bbacf0e8e6bd6201f8c5c851881efd889922`
  and snapshot
  `cecd553240606ac99485a822364db6662ac68c5a027a2d425049db2b00c0099a`;
  readiness observed
  `7436088b9e6c349a3c7f7f4c4789ab1db639730845d3f7ce91116fc7ba324aec`.
- V23 root-only remains sealed and immutable: driver 334,941 /
  `b69290f7b2000d1ec0e67913d95dd03ac8fc5079242fe30177729caef164f044`;
  controller acceptance 5,727 /
  `f58a1b42f6f25112653715f7628021f8d9047215b9add3ecb034a7d26b8ccd5b`;
  final index 5,471 /
  `a9921b89fdd6220a53943434bb9747a9531ef8094845ce6421c2fd2550f775ec`;
  root argv
  `b41b08955cd05382d61588d5425dc8faca9cf2e70d61f80069f65a56d0ea0f78`.
- Delivery remains `main` at
  `2f361fcddc0e63ae62ee62826e27b54bb8204c53` with 0 staged / 15 modified /
  156 untracked. Protected credential omission still occurs before metadata or
  content access; only `candidate.KWbe2iGW` has one omission.
- Historical V25 next-boundary reconstruction and its one-shot recovery
  dispatch are now consumed by the retained stop recorded above. They are not
  current authority and must never be retried. No authentication file was
  accessed.
- V22 candidate recovery remains consumed immutable preallocation-stop
  evidence: exit 1 after 69.608542 seconds, phase
  `M3_SUCCESSOR_PREPARATION_V22`, result receipt 3,923 /
  `bd77a38e2a7c4b4465d0b266676947e1a6f306a6a282bcf97665e12a2c6f7478`,
  exact error `RuntimeError: predecessor path count mismatch:
  candidate.KWbe2iGW`. It stopped before `mktemp`; its result/invocation and
  accepted execute/vector/envelope are consumed and never retryable.
- M3S-v22 is the retained immutable predecessor checkpoint. Its separately authorized
  root-only invocation completed exactly once: exit 0 after 0.232539 seconds,
  tool chunk `1fdba1`, phase `M3S_V22_ROOT_ONLY`, verdict
  `M3S_V22_READY_FOR_CONTROLLER_REVIEW`. The uid-501 mode-`0700` fixed root
  contains exactly the driver, empty private `home`/`tmp`, and private
  `receipts`; every retained file is uid 501 mode `0600`.
- Immutable V22 identities are driver 328,891 /
  `fe956d8bedc1aad9423c0707b0fe2dfeb4f934b25e077534daa7ffc010271793`;
  controller acceptance 5,733 /
  `86f6b2a705c347e3ad085057ac3d307c213d2227f6b40b5f63b06ad2587e493d`;
  source receipt 4,460 /
  `100b85b340898dcdbb24b56d2645e100d8d75770366f29c2d19d42bbe52dd896`;
  writer self-test 156 /
  `675abc5cf2c6d66274351a6dd76243970f97dd66e269ca711ee7a6d28fc2874d`;
  self-check 11,602 /
  `d218212d3e4fd45c5c9092c8784d6e1ae98ba41940e469921e764b82d78f61b4`;
  final index 5,477 /
  `476ad193e2641feaa62adc77f1bcdc76262b1009ea322e6fd0bd27b4d26e23a4`;
  root argv
  `61dfcbfaf24dbca209fb998ec8f9edd749929232f5b2329eee826eb9d9db376b`.
- The final index binds historical pre-root documents ExecPlan
  `b400ecceebf397a80c18c67dfd18e75fdd14452a716006102671473152d98e9c`
  and STATUS
  `b52b4f7cd78834c276b44cb1a2315d6bff68a31e2320ce5c09cca8f96d316692`.
  Both V22 reserved results remain absent. Candidate count remains 18 and
  delivery remains `main` at
  `2f361fcddc0e63ae62ee62826e27b54bb8204c53` with 0 staged / 15 modified /
  156 untracked. Root/controller budgets are consumed; result/suffix/init are
  available once. Authentication and formal dispatch remain unauthorized.
- The sole V21 candidate-recovery invocation is consumed immutable
  preallocation-stop evidence. The wrapper exited 1 after 61.867283 seconds
  with phase `M3_SUCCESSOR_PREPARATION_V21`, no timeout/truncation/wrapper
  error/session/credential variable. Its uid-501 mode-`0600` no-replace result
  is 4,231 bytes /
  `932cc7cdfb8f2aaeaaf6b5fd225729f3ca9a2395e3e246116b27a8d596da8308`.
  Exact terminal cause is `RuntimeError: credential path excluded from
  manifests` at `tree_manifest:2341 <- validate_predecessors:2559 <-
  read_only_gates:3723 <- execute:6534`.
- The stop preceded the sole `mktemp`; candidate count remains 18. V21
  result/invocation is consumed, suffix/init were not consumed but are
  abandoned with V21, and no setup/readiness/doctor/loop-init/auth/role/test
  or downstream phase ran. The accepted V21 execute/vector/envelope hashes
  `54acf46b5fe6e99568b9cdefefcf070cb674fdc0f5c9374d62bde6b840ea9a37` /
  `b615723711093b999ee4f1fd8f027762772d545e18049d681d2b391dda6f106a` /
  `ecfa3ee7b5452ec7ee1de54bf06b5f6dbd51b7fc0594cde29359e154afc6eabf`
  are consumed and never retryable.
- V22 derives only from the sealed V21 driver and changes one manifest policy:
  the exact protected credential relative path is omitted before
  `file_record()`, so it is never opened, read, hashed, copied, logged,
  serialized, or emitted. Exact omission counts are one for the retained
  credentialed predecessor and zero for all other 17; four near-match
  negatives remain included and therefore fail any unexpected identity drift.
- The shared two-field tree-total schema and all non-credential path/count/
  byte/hash evidence remain unchanged. Static validation requires the omission
  branch's `continue` before all file access, no content/identity/hash/write
  call in that branch, exact 18-name omission coverage, and the pre-auth sealed
  predecessor identity already frozen in V21.
- Contract-object/hash equality, independent historical/current documents,
  exact 14-phase execute-only policy, 38 receipts, 11-name delta, one result,
  one unpredictable suffix, one loop-init, private HOME/TMPDIR, no-replace
  retention/sealing, no retry/reuse, and the immutable wrapper/seed/toolchain
  bindings are preserved. V22 has no auth or formal command surface.
- The frozen V22 candidate-recovery boundary uses one ordered 27-string
  execute argv, one 17-string direct-wrapper vector, and one literal non-login
  zsh envelope derived from the final current document identities independently
  of the immutable historical receipt. Inner/outer bounds are 2,730/2,760
  seconds and wrapper/diagnostic bounds are 1,048,576/65,536 bytes.
- Static inspection proves controller/contract/root/final-index checks and
  current-document validation occur before the sole `mktemp`. The exact
  protected path `home/.codex/auth.json` is omitted before content access;
  omission counts are one for `candidate.KWbe2iGW` and zero for the other 17,
  with four near-match negative fixtures. The execute surface preserves the
  exact 14 active phases, 38-receipt domain, 11-name delta, one suffix, one
  `loop-init`, no auth/formal capability, and retain/seal/no-retry behavior.
- That V22 reconstruction and one-shot candidate-recovery boundary are
  historical consumed evidence, not current authority. No authentication file
  was accessed during that design cycle.
- M3S-v19 root-only preparation completed exactly once and is sealed,
  accepted, consumed, retained, and immutable. The invocation exited 0 after
  0.4132215 seconds with phase `M3S_V19_ROOT_ONLY`, verdict
  `M3S_V19_READY_FOR_CONTROLLER_REVIEW`, and empty stderr. The uid-501
  mode-`0700` root contains exactly `candidate-driver.py`, empty private
  `home`/`tmp`, and private `receipts`; every file is uid 501 mode `0600`.
- Immutable V19 identities are driver 312,527 /
  `a192f3346f3ef386edaebbad8e2b0c7361e47c2567583d8a2669600b3594842f`;
  controller acceptance 3,758 /
  `a582d7a60ffe18a5dd5aeb302527013e88f53b5e3331dcc8af7a2dca55b047a7`;
  source receipt 4,798 /
  `909c221a25d18d65d5928d4c1d0a61cffa3f8d15b2d20d0c7e1e7bada4f6ec8d`;
  writer self-test 156 /
  `2987ad8e4e073add322c308328d7bcd7b98cea142face4e9ac095d575c66c607`;
  self-check 19,962 /
  `3f08703469eaa9e02bc841fd57e9de80eec1c366e6cf18d29eca8bb300fe1ef3`;
  final index 5,861 /
  `e81f0238a340199c90d5cae32b6a574d7b0102e4cb6c344836206ab3a1fb11a7`;
  root argv
  `1cda5dfc777f3d228a2e70d711beab05e6397e7a04d7cd629838355936ccc13d`.
  Both reserved V19 results are absent. Candidate count is 18; delivery is
  0 staged / 15 modified tracked / 156 untracked.
- V19 candidate recovery closes `BLOCKED_NO_SAFE_DISPATCH`. The immutable
  external receipt carries policy/trusted contract hashes
  `86d9e2e06917da6b91f811cbc030ba4d6aa9bd0cde23f4d5f1b30cc8d63da7ef` /
  `11303be256fd994c33e414b3acfc5add50b884cddef6b65285bc5894e5d16f26`,
  while the sealed driver's literal `CONTROLLER_CONTRACT_HASHES` requires
  `86dfbfa372003a292045ada604e17991325a30ed7f66030cbc6f29cdd1d28583` /
  `439dffb8ea1eca10cc77986d5061828d8b87c6cec1193a67d6d9a7c06c9550d4`.
  Candidate/formal/initial hashes agree, but exact object equality cannot.
- `validate_controller_acceptance()` enforces that equality before wrapper/
  final-index completion, before current-document `read_only_gates()`, and
  before the sole `mktemp`. Current ExecPlan/STATUS hashes are independently
  supplied to and validated by `read_only_gates`, but no current hash choice
  can repair the earlier immutable semantic mismatch. Structural inspection
  still proves the exact 14-phase active set, 18 predecessors, one result,
  one unpredictable suffix, one `loop-init`, and only the frozen setup/
  readiness/doctor/preservation/sealing path.
- Root/controller budgets are consumed. Result/suffix/init remain unconsumed
  but are abandoned with V19 and confer no retry authority. The exact
  27-string execute argv, 17-string wrapper vector, and literal envelope are
  derived only as rejected static identities. No driver or wrapper was run;
  no result, suffix, run, auth, role, test, render, evaluation, inference,
  publication, or downstream phase exists or is authorized.
- Exclusive V19 source remains 64,804 bytes /
  `20e6122c85d6ca886a520a30cbc5100f7395732e2ab0ca2ae30d280ef4e1f337`;
  the accepted independently transformed driver is the 312,527-byte identity
  above. The immutable wrapper is 2,345 bytes /
  `d022a3dbb40be1664ba663617c18e1690c3e353be51d20a46d8c852f2d3e14ed`.
- M3S-v18 candidate recovery is consumed immutable preallocation-stop
  evidence. The sole invocation returned 1 after 0.149305 seconds with no
  timeout, truncation, wrapper error, session id, or credential variable. Its
  mode-`0600`, uid-501 3,612-byte result SHA-256 is
  `7aa1b5a48b8bde8267c51d70742dc5b59185611cc8d0c125f040d6eb1ddad8c0`;
  exact terminal exception is `AttributeError: 'dict' object has no attribute
  'st_mode'` at `validate_controller_acceptance` line 6326. No suffix, run,
  setup, readiness, doctor, auth, role, test, or downstream phase ran.
- M3S-v18 root-only preparation is sealed and independently accepted. The
  single invocation exited 0 after 0.399761042 seconds with phase
  `M3S_V18_ROOT_ONLY`, verdict
  `M3S_V18_READY_FOR_CONTROLLER_REVIEW`, and no reported stderr. The uid-501
  mode-`0700` root contains exactly the mode-`0600` driver, empty private
  `home`/`tmp`, and private receipts with the immutable controller acceptance
  plus four root receipts. Root/controller/result budgets are consumed;
  suffix and init were not crossed and are abandoned with V18. Auth and formal
  dispatch are unauthorized.
- Immutable V18 identities are driver 305,862 /
  `5a5f958050a281a836da0507f295c0ecc5e7dec3399fea28331ecb7aad9dcda5`;
  controller acceptance 3,798 /
  `6dfa640f91cb7f9f466c29d479056351195d11346785445f028e18b600efb196`;
  source receipt 4,838 /
  `ecc3b7cd98a319c5107263500579c124427c3d9aec2201fab04bf230542efbaa`;
  writer self-test 156 /
  `6eeda3e1527803658ddd5c4fc1297d6c7e306e8aa939e2f50448c77871aa06e6`;
  self-check 15,829 /
  `603ef568cc8657fd3f7ecffe6008165be998cb7c1bfec3419ff324c15639a73d`;
  final index 5,901 /
  `66f13730dde72f4f8a8b77120e68bca3c50dd96fc5a01a7627213360fe555c67`;
  root argv
  `2d71ff49e08833b81af4cb6c9f4c0c1bd88ec86241a018889511541fbeeb1e13`.
  The consumed successor result is recorded above; the auth result remains
  absent. Candidate count remains 18 and delivery remains 0 staged / 15
  modified / 156 untracked.
- The frozen V18 candidate-recovery boundary uses one 27-string execute argv,
  one 17-string direct-wrapper vector, and one literal non-login-zsh envelope
  derived from the final current document identities independently of the
  historical receipt. Inner/outer bounds are 2,730/2,760 seconds and
  wrapper/diagnostic bounds are 1,048,576/65,536 bytes. The result is
  no-replace; `mktemp` and `loop-init` each occur exactly once and consume
  their own one-shot budgets.
- Static full-byte inspection proves current-document validation and the exact
  14-phase active policy occur before the sole `mktemp`; the exact inactive
  writer/auth fixtures each fail with one policy violation. The execute
  surface has one 25-token schema, exact 18 predecessors, a 38-name sealing
  domain with 11-name successor delta, and no auth/formal/`--last`/resume
  capability. Successful recovery stops for controller review.
- M3S-v17 candidate recovery is consumed immutable preallocation-stop
  evidence. The sole invocation returned 1 after 0.151416 seconds with no
  timeout, truncation, wrapper error, session id, or credential variable. Its
  mode-`0600`, uid-501 3,709-byte result SHA-256 is
  `d65064d99735c89bedddcc396040389293c7bb40213157cb63bd45f758e4a102`;
  exact terminal error is `RuntimeError: successor phase policy violation:
  inactive_active_version:M3S_V17_WRITER_SELF_TEST`. No suffix, run, setup,
  readiness, doctor, auth, role, test, or downstream phase ran. Candidate
  count remains 18 and delivery remains 0 staged / 15 modified / 156
  untracked.
- V17 execute/vector/envelope SHA-256 identities
  `aff0634c3cfb7393720b885f971761abc2241c1cbfc85c41238afe6ba4673c8a` /
  `6a6a1ae235885017711026370856616c8dd3dd68d2d75794ca6dd1d63d9600b1` /
  `513dfb7776fb70d091d21663c1558bd8fe2644989c7cadd326674991795fac93`
  are consumed and never retryable. Root/controller/result budgets are
  consumed; suffix/init were not crossed and are abandoned with V17.
- M3S-v17 root-only preparation is sealed and independently accepted. The
  exact invocation exited 0 in 0.160501458 seconds with phase
  `M3S_V17_ROOT_ONLY`, verdict
  `M3S_V17_READY_FOR_CONTROLLER_REVIEW`, and empty stderr. Its uid-501
  mode-`0700` root contains exactly the mode-`0600` driver, empty private
  `home`/`tmp`, and private receipts with the accepted controller receipt plus
  four root receipts. Root/controller-acceptance/result budgets are consumed
  and immutable; suffix/init were never consumed. Auth and formal dispatch
  remain unauthorized.
- Immutable V17 identities are driver 300,521 /
  `85668e6c17ed929e9b4f7c4eae431fd3cf25f8174377eacfc5f2a153e0743f99`;
  controller acceptance 3,784 /
  `7d6cb468661054a1bbe58ed0dac4d1885b6a2f9724a7a93db37f950d3deae645`;
  source receipt 4,823 /
  `f2abcc48461575c5f6d7a3608861ce9c7a68c1a93f44c57c219b3178af12fc9f`;
  writer self-test 156 /
  `a2991706b3f09bea8a7b690e87c004b7916b6aab6e5844be9729939607bd4a15`;
  self-check 11,767 /
  `a0a184500199eb2c9670025413bf7533607f5dee63e8c194a7bddaaf7cf5aaf2`;
  final index 5,886 /
  `c9b4d22be3aa39b4959aa1be5ffa177529d1af8aa5a03d4def71668e82ed0ea9`.
  Root-prepare argv SHA-256 is
  `0a511f52bd3857ed103f697441cd32bef58a94262ba29021e53a8221186d8789`.
  The successor result above is present; the auth result remains absent and
  candidate count remains exactly 18.

- M3S-v16 candidate recovery is consumed immutable preallocation-stop
  evidence. The sole invocation returned 1 after 0.141347 seconds with clean
  wrapper fields and exact terminal error `RuntimeError: successor phase
  policy violation: missing_active:M3S_V16_AUTH_HANDOFF`. Its 3,700-byte
  result SHA-256 is
  `3762f76a0e34dcb1976e07ed77d1e7776564e027185ca97ebd0ab76ff33ac063`.
  Candidate count remains 18; suffix/init were not crossed; no setup,
  readiness, doctor, auth, role, test, or downstream phase ran.
- The V16 execute/vector/envelope hashes
  `a47e65a802a29e8b82fe35d7ec4115bce508e1aa6307da1d273a336ef4d7691e` /
  `adc7ec0236a6bfe420c10dba7b6eba98fc0e37aa104584c8e9b5ea948fb9d636` /
  `dae532241c666a446fe6341dc7682566d996cd026b10717cf22f6a99210542e8`
  are consumed and must never be retried.
- The exclusive V17 preparation source remains 60,099 bytes / SHA-256
  `fa4e6c3900ca8c150bec466951d028696d17bf9c049f5e59b75c0053baefffe4`;
  the sealed driver is its independently derived 300,521-byte output above.

- M3S-v16 root-only preparation is sealed and independently accepted. It
  supersedes only the unsafe V15 candidate-recovery boundary; every V15 root
  byte and receipt remains immutable. V16 treats the pre-root controller
  receipt's document identities as historical acceptance evidence and
  validates later execute-time current documents independently. No gate equates
  the two generations.
- The unique V16 preparation source is the exclusive marker payload, 48,880
  bytes /
  `96e9377b91552f086bbddffdfc514546095a5839e5d1557ca4687fddfeccb213`;
  independent deterministic transformation yields a 293,857-byte
  credential-free driver /
  `f97a3c80e66def343db2f3c3026f6c956fa84fb8834ecd323800f1185dee56bb`.
  Both parse/compile and pass Ruff F/B/S. Static structure proves one 25-token
  execute schema, exact 18 predecessors, one `mktemp`, one `loop-init`, exact
  V1-V17 phase domain, V16 receipt/path/schema domains, historical/current
  document separation, and no auth or resume capability.
- The first V16 closure report incorrectly included both marker lines in the
  source range (exactly 72 extra bytes). Controller reconstruction rejected
  that stale boundary before dispatch. The corrected root-only invocation then
  completed once with exit 0 in 0.1613375 seconds, phase
  `M3S_V16_ROOT_ONLY`, verdict
  `M3S_V16_READY_FOR_CONTROLLER_REVIEW`, and empty stderr.
- V16 contract SHA-256 values are candidate allocation
  `4b4b648d76faeed7ee32f2c50f775726f47436a9291650910f9ebf34d40e72c6`,
  formal dispatch
  `70b63e787c7195e254bee058d98ada477ca411edfe637d101551dfb210124ae3`,
  initial run
  `034bf76f031f9da71b69d988cbcf15fb7674c24f7f455b3a72b8bacc4e1829c3`,
  policy/toolchain
  `768359902152117dabaa11c9634fe900e1f8f448903d3161228f8b14694c1835`,
  and trusted context
  `0009972fc70f7445d2b1fa9b3bf52be66eba1108aef5a5193ba979f21ada4d22`.
  Root/controller-acceptance budgets are consumed and immutable. Result,
  suffix, and init remain unconsumed; auth and formal dispatch remain
  unauthorized.
- The uid-501 mode-`0700` V16 root contains exactly its mode-`0600` driver,
  empty private `home`/`tmp`, and private receipts. Immutable identities are:
  driver 293,857 /
  `f97a3c80e66def343db2f3c3026f6c956fa84fb8834ecd323800f1185dee56bb`;
  controller acceptance 4,168 /
  `043b40b488f0dc71a9cb136c2e193b9f50cfca516f67e084a71419782b1f88a1`;
  source receipt 5,174 /
  `c821c059035f304a5d56286a934500b7bfc29cf8f7761f670dc30b99adc58cbe`;
  writer self-test 156 /
  `9fc0e149f0a78301534b78fe9bcf50f91f1452efc67d6739512ff8e0f54002d9`;
  self-check 7,793 /
  `8cd0d47d3728c6ff3e55302c6ee96e9139972bcf55c9213436a323768250d1d4`;
  final index 6,236 /
  `891c192da8d96bfd479cafaae027ff7998b1529e5569dbde7e5bf20cf52359c9`.
  The final index binds root argv SHA-256
  `fc424b91c50cb490507d93c6252ec16ea703851aca54dffa4d70f41c4106bf27`.
  Both reserved results are absent; candidate count remains 18 and no new run
  exists.
- The closed candidate-recovery design uses exactly one 27-string execute argv
  through the immutable 2,345-byte wrapper
  `d022a3dbb40be1664ba663617c18e1690c3e353be51d20a46d8c852f2d3e14ed`,
  one 17-string direct-wrapper vector, and one always-single-quoted envelope.
  It binds final current documents separately from the historical controller
  receipt, then validates both before the sole `mktemp`. Inner/outer bounds are
  2,730/2,760 seconds; wrapper/diagnostic bounds are 1,048,576/65,536 bytes.
  Exact argv/vector/envelope identities are derived only from the final closed
  documents. Successful recovery stops at controller review and grants no auth
  or formal-role authority.
- The accepted M3S-v15 root-only invocation completed with exit code zero in
  0.158372333 seconds, phase `M3S_V15_ROOT_ONLY`, verdict
  `M3S_V15_READY_FOR_CONTROLLER_REVIEW`, and empty stderr. Its fixed uid-501
  mode-`0700` root contains exactly the mode-`0600` driver, empty private
  `home`/`tmp`, and private receipts with the accepted controller receipt plus
  four root receipts. Root and controller-acceptance budgets are consumed and
  immutable; no replay or root repair exists.
- Immutable V15 root identities are driver 288,261 /
  `57cfac05048a79b9e13190e2fb6a75a51995055907e6bae882dc37837258d1a4`;
  controller acceptance 2,812 /
  `84fa6a69e8f3409f6693ef7f8cd23830e1a3f13b3e19f326a35f54f67058e019`;
  source receipt 1,920 /
  `cd286fe8cd2e4579b3fa4b1ba18c42c7630565d81f8ab9da5a4aae167a8b08b4`;
  writer self-test 156 /
  `0a68f61a6a411883a60a1da29cc1dd7bdadb56d9b18021d7351e4aacf523e2da`;
  self-check 3,422 /
  `bd5bc0b77c0ff6a048f59e65b308b87fb2a783bc6fb2e18b8c2a789d7792c3ce`;
  final index 2,982 /
  `f9db898a93abc92f371a1280237e74ec6ba229cfd18bffc76a51ec9ef8e1bb3a`.
  The final index binds root-prepare argv SHA-256
  `368e5197a14bf251a5a0b65da9f516ef2a39e94075242581f2d6ed67d1e084f6`.
- Both V15 reserved results remain absent. Candidate count remains exactly 18;
  delivery remains branch `main`, HEAD
  `2f361fcddc0e63ae62ee62826e27b54bb8204c53`, 0 staged / 15 modified
  tracked / 156 untracked. Candidate result, suffix, and init budgets remain
  unconsumed. Auth and formal dispatch remain unauthorized. The sealed driver
  has no auth command, credential source, login probe, or credential-copy
  capability; new explicit authority is required for any later V15 handoff.
- Static derivation of the credential-free candidate-recovery boundary found
  an unsatisfiable identity conjunction before execution. The immutable
  controller receipt binds pre-root ExecPlan/STATUS hashes, while the sealed
  driver requires those receipt hashes and the current post-root file hashes
  to equal the same execute arguments. New hashes fail `accepted ExecPlan
  mismatch`; old hashes fail current-document validation. No exact V15
  candidate-recovery invocation can pass preallocation, so result/suffix/init
  remain unconsumed and no execute boundary is authorized.
- The single accepted M3S-v14 root-only invocation remains consumed and
  non-retryable. It exited 1 after 0.147307 seconds during preflight
  `validate_v13_evidence` with exact terminal `RuntimeError: V13 artifact
  lineage mismatch`, before fixed-root `mkdir`. V14 remains absent. V15's
  exact ordered full-path lineage predicate closes that defect without
  weakening provenance.
- The one authorized V13 formal invocation is consumed, retained, and
  terminal `blocked`. Candidate `candidate.KWbe2iGW` and run
  `20261012T225001Z-e23eba62` are immutable and non-reusable. The invocation
  exited 2 at Planner cycle 2 / code cycle 0 with null Coder session, empty
  command results, and `plan repair budget exhausted`. No Coder, Reviewer,
  Tester, Runner, Gateway, test, render, evaluation, inference, service,
  candidate publication, or delivery publication ran.
- Terminal `state.json` is 9,406 bytes mode `0644`, uid 501 /
  `3a684a63704c66361b10310fc316fdb6f8bd987fc367cff7f36ffd02c87581c6`;
  `events.jsonl` is 2,056 bytes mode `0644`, uid 501 /
  `42c1f21286deab698ad94b415a382170271413b2f918dfa12d1d9f893e93b662`.
  Planner artifacts `001/002` are 9,291 /
  `527032e756f774075116302207b972567e7ec794f5d38f9e02b11056ebbf6b84`
  and 10,030 /
  `141fe3c956aa438d84825c4c2a89dd948218cbddf88d47fcce347f85b615fc02`.
  Their event logs are 61,935 /
  `a4867bf7afa7b624d3f1e2b32666a7b6c8ada69035679c95b05644597034ff4f`
  and 100,302 /
  `1afc5e20d6b5b4135b1a61106bab52328d80df8b89c63625c0c1800305bd621a`;
  final captures are 9,186 /
  `9fbc81ea9a937c78de26dd03e25b819a04b095da869b2ceca3df2c98bb34fb92`
  and 9,925 /
  `1c6a8ffb235b7b90c7a5ff288e3997e130765e53973d9fa635691c7e4d2b3516`.
- Both Planners returned `NEEDS_INPUT`: candidate-visible final bindings and
  trusted context contained producer labels but no literal externally issued
  controller-acceptance receipt. Toolchain source/snapshot fingerprints
  `d6a7f3f77d2b5edebab0792182a4bbacf0e8e6bd6201f8c5c851881efd889922` /
  `cecd553240606ac99485a822364db6662ac68c5a027a2d425049db2b00c0099a`
  were internally consistent but could not supply external authority.
- M3S-v11 is consumed, retained, and immutable. Its uid-501 mode-`0700` root
  contains the mode-`0600` 259,661-byte driver
  `bc0c97ee1169a64582bbae39b7793f3c5e401e7be9aad0a4c377f74c8ee6d983`,
  empty private `home`/`tmp`, and private `receipts` containing the four
  sealed prerequisite receipts plus the consumed candidate-recovery result.
  Source is 12,640 /
  `7110db23d05f84917056140c5605250bda4f738bc880fbcebcbf0f26932dc5d2`,
  self-check 2,078 /
  `145d0023479ea6b4a8ab0a06346c94afd08b47f01a0eafee5bfd3c486311d6bf`,
  writer self-test 84,849 /
  `bda2658a28c121aea6be9906a120b8b579667a914a82c6460930351fe87e871f`,
  final index 37,431 /
  `750cd8adcc528f52dda0c556d16490ed922eee0d2c84d875ad25579d375222df`,
  and result 4,297 /
  `cbef725679d2a73bd9cedc178a8fa12096f1b187db18ec3ab3229c0127477c15`.
- The V11 candidate-recovery wrapper returned 1 in 51.265066 seconds with no
  timeout, truncation, session, credential variable, or wrapper error. It
  stopped at the preallocation `validate_profiles` gate on exact terminal
  `RuntimeError: hash mismatch: /Users/junhuaxu/.codex/config.toml` because
  the frozen expected identity was 1,471 bytes /
  `5867648914af98477ad9f83e6e79ee48fce60b8dd42b7839bd73e335f1a654d0`
  while the controller-observed private regular mode-`0600` file was 1,628
  bytes /
  `5e0924533a66285439d856dff8bc8e7bbc138af7a1addbae8e562eb7be6208bb`.
  Candidate count remained exactly sixteen; no suffix, candidate, setup,
  readiness, doctor, init, M3 role, test, render, evaluation, or inference ran.
  The V11 root/result invocation budgets are consumed. Its suffix/init budgets
  were never consumed but are abandoned with the immutable V11 chain and
  confer no retry authority.
- M3S-v12 root-only preparation and its separately authorized candidate
  recovery are complete, consumed, retained, and immutable. The fixed
  uid-501 mode-`0700` root retains the mode-`0600` 271,365-byte driver
  `bdaf7c297679ed9cd1880ce39013fbb861d2ee2b68bf8609cd442144a357d443`,
  four prerequisite receipts, and the mode-`0600` 22,987-byte result
  `cdf655c04ba00b49a7328429fcb3d746925836a3c29e3585552c88efbc06a4a9`.
  The wrapper returned zero in 181.903681 seconds with no timeout,
  truncation, wrapper error, session ID, or credential variable.
- Exactly one new suffix exists: `candidate.mRMO7MQ6`, raising the exact
  candidate count to 17. Its mode-`0700` parent contains only `repo`, private
  `home`/`tmp`, and private `successor-receipts`. Verdict is
  `M3_SUCCESSOR_PREPARATION_V12_READY_FOR_CONTROLLER_REVIEW`; sealing has no
  errors. The complete tree is 44,319 paths / 946,642,902 regular bytes /
  `d1ff05d5a397d0c2f0969d2fb7e7ef0e4ccd89c4044d38928114c0a688350c01`.
  Final index is 17,147 bytes /
  `f5a86dd894e25d821f408e4cdf85a8a6b071a7bfe0ec818c65edace5020b70a4`;
  repository manifest is 6,139,714 bytes, 27,412 paths / 579,120,121 bytes /
  `55f90d7970d5ee844465ba09537628c41f3990bd148a9d17bd64925e7e3394c1`;
  attempt manifest is 12,176,268 bytes, 44,317 pre-index paths /
  934,449,487 bytes /
  `92cb4555c3dc2b5738db348c8295cb0583430df764bb2a01942b897e9f8fdc96`.
- Setup returned zero without credentials; readiness passed with no issues;
  doctor passed with return code zero, terminated lifecycle and proven safe
  sealing; preservation passed. The V12 opaque-config rule read, hashed,
  copied, and persisted no operator config content and matched the private
  metadata tuple in the same driver process before staging only the five
  reviewed profile files. Root/result/suffix/init budgets are consumed and
  immutable. No retry or reuse exists.
- The sole initialized V12 run `20261009T235710Z-7716e9ad` was dispatched
  exactly once and is consumed terminal `blocked` at Planner cycle 1 / code
  cycle 0. Terminal `state.json` is 9,439 bytes mode `0644` /
  `ccbc294860f252647f35759722a06dad4176cf4f8339073ba562900142a1aebb`;
  terminal `events.jsonl` is 690 bytes mode `0644` /
  `5bf26b433f398e09e87809744e324c200f701cd1a7bee230b5834be08ecc26b7`;
  and `agents/planner/001-events.jsonl` is 4,114 bytes mode `0644` /
  `231289a174dd5e401beca46bdfc868cee17fb3cf79a487a8f6bbf64769ea6d01`.
  Coder session is null; artifacts and command results are empty. No Planner
  artifact, Coder, Runner, test, Reviewer, Tester, Gateway, or publication
  exists. Sanitized diagnostics bind repeated WebSocket 401 responses,
  fallback to HTTPS Responses, and the same 401 outcome with
  `Missing [REDACTED] [REDACTED] in header`. Final bindings remain 3,767 bytes /
  `de356dd0ffe99e615822047f6186fea8f4b2948ae0c71e4b90746600742bf741`
  and bind worktree fingerprint
  `07b48ebeac6c1815f22d4b7623a471107d8a9d4eee0b3097ab8fbfcdd1cd1b65`.
- Candidate-local trusted context is 3,308 bytes mode `0600` /
  `a8fc178f750c4cec01dc0343c8e432390f6bb9a1f8add5eac0c060b871d10aca`;
  its 4,026-byte receipt is
  `e276be6c1225846e4027e6d019d193afd7004b33cefdb5dc13c8cc70738cf369`.
  Policy semantic SHA-256 is
  `95cbe7afde8a3af5e7f80a06845dd982bfe76f25981ce575737cc233c06d919c`;
  toolchain source/snapshot fingerprints are
  `8d3b65f90d64db7f8628d7fd48b4e8709bd0eb87477528b31081f9b4cad87f57`
  and
  `cde01d5ba4d0697d80f90ca7bdef4b60ad7defa5882a2e9f4479631f6c312197`.
- The consumed historical dispatch argv was
  `["/usr/bin/make","loop-run","RUN_ID=20261009T235710Z-7716e9ad"]`,
  canonical JSON 63 bytes / SHA-256
  `e1dc675a7ba4a1b63129e1be9e67b1d5cd32a96d058f31cef7550f860e0b9e0f`.
  Its exact candidate CWD, seven-name private environment, non-login zsh
  envelope, `/dev/null` stdin, 34-hour outer allowance, 1,000,000-byte
  capture bound, initial-state preconditions, role/session rules,
  Runner/Gateway gates, stop conditions, and completion evidence are frozen
  in the Living ExecPlan. The single invocation is terminal evidence and must
  never be submitted again. This was one formal engineering workflow, not
  product inference, media evaluation, rendering, benchmark execution, or
  publication to the delivery worktree.
- Static source inspection correlated the authentication failure without
  touching credential material. The operator has now explicitly authorized
  one fresh successor to use the currently authenticated Codex account through
  an opaque handoff into a new private HOME. M3S-v13 keeps
  `safe_child_env()` unchanged and rejects token/environment/keychain/
  interactive fallbacks. Credential bytes remain forbidden from inspection,
  parsing, printing, logging, hashing, diffing, receipts, manifests, prompts,
  and commits.
- The unique embedded V13 preparation source is 46,740 bytes / SHA-256
  `bbb65498eb25bc148c56c8b8e5423f28c241e4630b24f7249bc5d2ec3f2a40b2`.
  Its deterministic non-evaluating transformation of immutable V12 raw bytes
  yields a 285,428-byte V13 driver / SHA-256
  `0dc4830e8684afc879f3e63793e0265fa149d2e5cdf4ed8a8e7fe9970cfbde3d`.
  Both parse/compile and pass Ruff F/B/S. The driver has exactly two commands,
  `execute` and `auth-handoff`; one `mktemp`; one `loop-init`; seventeen
  predecessor names; one auth-path manifest exclusion; and one fixed
  `codex login status` child with `shell=False`, `DEVNULL` channels, and no
  credential-bearing environment.
- M3S-v13 root-only preparation completed successfully and is now consumed,
  retained, and immutable. The fixed root is uid `501`, mode `0700`, with
  exact entries `candidate-driver.py`, `home`, `receipts`, and `tmp`; home/tmp
  are empty mode-`0700`. At root-only closure, receipts was mode `0700` with
  exactly four mode-`0600` files. Driver is 285,428 bytes /
  `0dc4830e8684afc879f3e63793e0265fa149d2e5cdf4ed8a8e7fe9970cfbde3d`;
  source receipt 652 /
  `dd48c2a062cf37e107c8ea96623047f4403e3b0ca2a64ddd4d805800c7dc44d6`;
  writer self-test 156 /
  `a3b80bb79d6e510f22b32e0e63e61bad772b7f3eefeb953dab55d6bf1831361f`;
  self-check 862 /
  `c8e3463ea95cb84bb39736a2e1c6e390f6bcdefc87a1088117cd87b55f8198f4`;
  final index 1,355 /
  `f5e20e2f2367fe0585f0d692c3c7039ea2572e0a9f0d3d77fd359db63098f352`.
  Verdict is `M3S_V13_READY_FOR_CONTROLLER_REVIEW`; root-prepare argv SHA-256
  is `078421abee58e58975d10585bfae305fb49ed5ce47d0a1ae5de03449655bc839`.
  Candidate recovery and opaque auth handoff have since appended their two
  separately budgeted accepted results; all six root receipts are immutable.
- M3S-v13 credential-free candidate recovery completed successfully and is
  consumed, retained, and immutable. The mode-`0600` root result is 22,756
  bytes / `7069f0f99a79fc9d2ce967df68689d98eabbdacf53baaa1f514db7848634b4b3`,
  with return code zero, 215.915482 elapsed seconds, no timeout/truncation/
  wrapper error/session, and empty credential variables. Its exact 25-string
  execute argv has canonical SHA-256
  `96626934af6e3e30ccdd43e3e4dd895b0a59222e07b5b61404032f82684cefa9`.
- Exactly one new suffix exists: `candidate.KWbe2iGW`, raising the exact
  candidate count to 18. The uid-501 mode-`0700` candidate contains only
  `repo`, private `home`/`tmp`, and private `successor-receipts`. Final verdict
  is `M3_SUCCESSOR_PREPARATION_V13_READY_FOR_CONTROLLER_REVIEW`; sealing has
  no errors. The complete tree is 44,316 paths / 946,755,162 regular bytes /
  `e0aa33a9231aa88ec1a809be4f2bf7413973d16320146cd0c42cde051a6bca38`.
  Final index is 17,147 bytes /
  `faa61806d4738ccc648510ea0da8517578055a7043192443100c08f8500fba1b`;
  repository manifest is 6,139,138 bytes, 27,409 paths / 579,226,272 bytes /
  `67977ece5258767b0a46381b8033c3a49d5da1e5400d5c4c03f4fd2e9e9d4e84`;
  attempt manifest is 12,175,677 bytes, 44,314 pre-index paths /
  934,562,338 bytes /
  `8beef3afae1a83e370dde5495af8420c2b097225f99cf1bfa560c3a79b3bb624`.
- Final bindings are 3,767 bytes /
  `ef20fa2659c1257c5aa3d72ce5f601d2ed3bc25b96fea67f69efffd61c9750e7`
  and bind candidate worktree
  `2b53f22934a8b976e6dfdee6ebc563fcf25734e9b9f675cf3013143a308744f2`.
  Candidate-local trusted context is 3,308 bytes mode `0600` /
  `b50a86e35fe64342f4c3e49c2589416aaaac8763e4f5b0b8d7cd79b67cc15ae5`.
  Setup, readiness, doctor termination, preservation, context/policy/toolchain
  binding, init, and sealing all passed.
- Fresh run is exactly `20261012T225001Z-e23eba62`. Initial `state.json` is
  9,210 bytes mode `0644` /
  `e68cb2a333e3dc82f35959f10fdf560c41549df8e7f3dfa8a3c8e34d66f3e01a`;
  initial `events.jsonl` is 144 bytes mode `0644` /
  `26c337eae49c5f87b812c1ed8ba9026beeb11daab32b857318da1e85c2864dc0`.
  State is received, cycle/code-cycle zero, Coder session null, artifacts and
  command results empty, and error null. Future loop-run argv SHA-256 is
  `62e86b2cda27eef25af809829d275da401c5af66e844d4dce060ebd21ce77082`;
  no formal dispatch is authorized.
- The separately authorized V13 opaque auth handoff completed successfully.
  Its exact non-secret result
  `trusted-tools/m3-successor-preparation-v13/receipts/auth-handoff-v13-result.json`
  is 262 bytes, mode `0600`, owner uid `501`, SHA-256
  `75a72ce1afd6e59a05df27422c68c3059ad351df156b87070f0943fb2396a601`.
  Its eight sanitized fields are `copy_success=true`, destination mode
  `0600`, destination owner uid `501`, format version `1`, login status
  `SUPPORTED_AUTHENTICATED`, phase `M3S_V13_AUTH_HANDOFF`, result
  `READY_FOR_CONTROLLER_REVIEW`, and null sanitized error. No auth file was
  accessed during this documentation cycle.
- V13 root/result/suffix/init/auth-handoff/formal-dispatch budgets are consumed
  and immutable. The historical frozen dispatch was inner argv
  `["/usr/bin/make","loop-run","RUN_ID=20261012T225001Z-e23eba62"]`:
  3 strings, 63 canonical JSON bytes / SHA-256
  `62e86b2cda27eef25af809829d275da401c5af66e844d4dce060ebd21ce77082`.
  The direct seven-name private `env -i` vector is 12 strings, 499 canonical
  JSON bytes / SHA-256
  `aca9829c16784bdb9d859fb3404733a3c10aca6c395a5086f32609bbf48ec1d7`;
  its always-single-quoted envelope is 12 tokens, 513 bytes without trailing
  LF / SHA-256
  `2b7cbf5db23ee839ae0cf005eddb75986e637bae6beadfcae085de7723b10aa0`.
  Workdir is the candidate repo; shell is non-login `/bin/zsh`; stdin is
  `/dev/null`; outer/diagnostic bounds are 122,400 seconds / 1,000,000 bytes.

- M3S-v9 is consumed, retained, and immutable. Its UID-501 mode-`0700` root
  contains only the mode-`0600` 249,012-byte driver
  `c560c94de52b7ae361e01c23af5aa7947275405a7e6fe0b696591ef6b2d6b1c5`,
  empty private `home`/`tmp`, and private `receipts` containing the 12,629-byte
  source receipt
  `26779b08c43b78c604b1469b4d99464d36fe1c6c5fe063c809cbd6233b3ee857`
  and 3,848-byte self-check result
  `a0202c7a7fbe32064dbb27cad30416dddeab8d8e66c3b47915532b6cf5395734`.
  Transport was rc0 in 0.049008 seconds; self-check was rc1 in 0.088476
  seconds with clean wrapper fields and exact terminal `RuntimeError: file
  exceeds read bound: /Users/junhuaxu/autoclip/docs/exec-plans/liveclip-agent-runtime-v2.md`.
  The outer stopped in 0.429038 seconds on `RuntimeError: self-check outer
  return code` with empty stdout. Writer self-test, final index, reserved
  result, candidate, and every downstream phase are absent.
- V9 failed because its generic 4,194,304-byte buffered-read bound was applied
  to the 4,194,810-byte closed ExecPlan at
  `validate_m3s_v8_procedural_stop`, an exact 506-byte excess. V10 preserves
  the generic receipt/data bound and routes every buffered Living-ExecPlan read
  through one explicit 8,388,608-byte helper, with boundary and structural
  call-site fixtures.
- Complete M3S-v10 source is frozen only in the Living ExecPlan: writer 9,478
  bytes / `1d2523a41e74e6519d96a98123e74f0b315f4a559757aafceb60850c76593e61`;
  driver 256,603 bytes /
  `beb060307f255cd51de489289bfaea104ae2f76385a5aeaf17aa86b85a753062`;
  pre-root orchestrator 63,672 bytes /
  `1eb7d895062b3ac65277c13fbfb8f245af67875fc27ace51e19011aaa5f1489e`;
  envelope-v6 source 13,627 bytes /
  `dc8f7c26ebf5b85532e4ce15d4516e0d7a8302d2ad2c695d38e676c7dee40a17`.
  The fixed V10 root is absent and unconsumed; no V10 source, wrapper, root
  phase, result, candidate, or downstream phase ran.
- V10 binds the exact V9 stop, preserves every V1-V9 frozen byte and retained
  root, retains the V8 absent-root gate, blocked-state `code_cycle == 1`, M2
  manifest/tree separation, 28 historical versus 37 future receipt names,
  one-suffix/init budgets, and pre-`mkdir` 26/25/23 plus 32-element command
  construction. Controller independently audited all sixteen predecessor
  manifests as exact; that remains correlated evidence, not a new receipt.
- V10 static closure is complete without evaluating embedded source: unique
  extraction, parse/compile-only, Ruff F/B/S, structural security and schema
  fixtures, exact V9/protected evidence, V8/V10 absence, Appendices 15/153,
  main/HEAD, 0/15/156, and sixteen candidates all pass.

- M3S-v7 is retained consumed and immutable. Its source transport was rc0 in
  0.048956 seconds; self-check was rc1 in 4.26554 seconds with exact terminal
  `RuntimeError: blocked run state mismatch`. Both receipts have clean wrapper
  fields. The UID-501 mode-`0700` root contains the empty private `home`/`tmp`,
  mode-`0600` 242,362-byte driver
  `7ddb4d2fba4f9b392db584bcd4ece290230f7875750cb0e55148d2d0ac948add`,
  12,629-byte source receipt
  `8f10a4bf7d9dee39148df8d221e4d0b39339618dfe1a688afd2a38338e52c833`,
  and 3,386-byte self-check result
  `cc23a533ab87484f75f0983ec46eda3e4288b7ab987de96aa833a51e18a48e1e`.
  Writer self-test, final index, reserved result, candidate, and downstream
  phases are absent; V7 cannot be repaired, retried, appended, or reused.
- The immutable blocked state remains 17,815 bytes /
  `cb6e8a2ff53902dc617281757a6d5a910069109b1e2637ef5929c914ca25a6e5`.
  It records run `20261009T124056Z-37111cbc`, state `blocked`, cycle 1,
  code cycle 1, Coder session `01a120b3-f587-7682-80e4-635b1fcfd823`,
  and exactly one Planner plus one Coder artifact. V7 incorrectly asserted
  code cycle 0.
- Complete M3S-v8 source is frozen only in the Living ExecPlan: writer 9,473
  bytes / `110dd173f64876a14e807ec5fdf3d70c23c50b1d0a37ea27df78252e609caba7`;
  driver 244,989 bytes /
  `89d5603134e0b005ec50f8b7518fe52cfadb78ac670d90fa295e0149617591f3`;
  pre-root orchestrator 55,201 bytes /
  `c3b4d172ecbc203c0cf697fc29ecf10ae708db39d432ef52546d448139d42cf5`;
  envelope-v4 source 13,619 bytes /
  `2d9ced86d68eaa4d2fb0526b5ffe7bb7bd6b75cdd814ea4f38683cb918f73424`.
  V8 validates the exact V7 stop and blocked-state artifact mapping, preserves
  the M2 manifest/tree split, and constructs all root argv before `mkdir`.
  The fixed V8 root is absent; no V8 wrapper or root phase ran. The source
  ranges are historical input to V9 and not executable V8 authority.

- M3S-v6 is retained consumed and immutable. Its source transport was rc0 in
  0.049437 seconds; self-check was rc1 in 6.747865 seconds with exact terminal
  `RuntimeError: hash mismatch: /Users/junhuaxu/Library/Application
  Support/LiveClip/engineering-candidates/agent-runtime-v2/a822890ace12/
  candidate.dygENR4n/receipts/final-attempt-manifest.jsonl`. Both records
  prove no timeout, truncation, session, credential variable, or wrapper error.
  The UID-501 mode-`0700` root contains only empty private `home`/`tmp`, the
  exact mode-`0600` 236,732-byte driver
  `7362b9815df413509e6d778ac9805a1aa2029870ca8bac6cd45a9e78dfe7eea0`,
  12,629-byte source receipt
  `9ec5e2f860260a874fe53c03f7385112efefe7cb4390cd0d3fa5bcb1697a4f7b`,
  and 3,890-byte self-check result
  `be3dd27b7fb7f15d4ce693ec7e3b89a132824ecc11f4566ac83be8157499f5a9`.
  Writer self-test, final index, reserved result, candidate, and downstream
  phases are absent. V6 cannot be retried, repaired, appended, replaced,
  chmodded, deleted, or reused.
- V6 conflated two valid but different M2 identities. The immutable final-
  attempt manifest is 6,282,115 bytes / 27,442 paths / 581,558,467 regular
  bytes / `a0f211b62cb93e45a8fa2a3ae0d17dcd03093f20c033bf9e2056ffba5a9fe1cb`;
  the completed attempt tree is 27,444 paths / 587,853,366 regular bytes /
  `c5d16be1ce9c79e7fc0332240f42a4785364539e83c9cf5b129a13c1a7c5aec3`.
  The V7 design binds both parsed M2 records and keeps these types separate.
- Complete M3S-v7 source is frozen only in the Living ExecPlan: writer 9,473
  bytes / `f48ea01d8b4a3cac3cb9b40277c72e2b67457a4afb837bcd5eb8d7929d523173`;
  driver 242,362 bytes /
  `7ddb4d2fba4f9b392db584bcd4ece290230f7875750cb0e55148d2d0ac948add`;
  pre-root orchestrator 52,027 bytes /
  `c602442a87dfb619d11cce4b206d9b11dcf106e80d217c44cbc46d6c2658a11d`;
  strict envelope-v3 source 13,619 bytes /
  `3a7540778b514b9761c5fe5616dbc2b25430570dd4eddf08d750690156a21df3`.
  It validates exact V1-V6 stops, separates manifest/completed-tree evidence,
  precomputes 26/25/23 and 32-element argv arrays before `mkdir`, and versions
  every active namespace to V7. Controller review rejected the first postimage
  for two stale V6 root diagnostics and one stale envelope-v2 AST filename;
  those three active labels were corrected and accepted before the consumed
  root-only action. That action is the retained V7 stop recorded above.
- M2 remains complete at immutable `candidate.dygENR4n`. M3 has one immutable
  blocked predecessor; successor preparation and the fresh formal run remain
  unstarted. No setup, readiness, doctor, loop-init, loop-run, role, Runner
  test, render, evaluation, inference, or publication ran in this checkpoint.

### Historical checkpoints

- M3S-v3 is retained stopped and immutable. Its source transport passed, but
  self-check returned rc1 with exact
  `RuntimeError: V5 candidate receipt set mismatch`. Driver/source/self-check
  identities are
  `1bd1f454458978af4cfe71002d16f4ca3258223ca1332200ad50a542d684648c`,
  `845017e41ed39e27d3aedad25d8e3d72343253fb9969295a7bfe40d720354387`,
  and `81c750c57bc8139df151c599b454d64c10366dbd15341e80c1fec517dffc7714`.
  No writer self-test, finalize, candidate, or run occurred. V3 incorrectly
  reused its 37-name future-successor tuple for exact immutable V5/V7
  historical directories whose sealed domains each contain 28 names.
- M3S-v4 is retained as an immutable pre-transport stop. Its no-replace root
  is a real UID-501 mode-`0700` directory containing only empty private
  `home`, `tmp`, and `receipts`; driver and all receipts/results are
  absent. Exact local failure was
  `ReferenceError: TextEncoder is not defined` after root creation and
  before any wrapper or subprocess invocation. Its budget is consumed with no
  retry, repair, append, replacement, chmod, deletion, or reuse. Its accepted
  document preimages were ExecPlan 2,496,447 bytes /
  `9464cc92cf4580a84e6d7615892a0967159e945e585be8652a9cf634088296ad`
  and STATUS 53,704 bytes /
  `6abbb5ee5eec7fe63e4835eea413bd3206cdb98c9fe9c070e54002ac09c380eb`.
- Complete M3S-v5 source is frozen in the sole ExecPlan: writer 9,473 bytes /
  `32a9cfbf71a7a955eea197f30fe23ea1ccbdcb2cca7d8307d03d218204d439a9`;
  driver 234,208 bytes /
  `ce3232c5dab7b00f54afdcac7d7f9774c872475142c12fcb6a85ac9822cec08f`.
  V5 validates exact V1/V2/V3 receipts plus the V4 empty-root stop, preserves
  the 28-name historical/37-name successor separation and 26-validator
  traversal, versions active phases/results to V5, and requires pinned
  Python/POSIX-only UTF-8/canonical-JSON construction proof before root
  creation. Its fixed root is absent; this checkpoint grants no root,
  candidate, init, role, or `loop-run` authority.
- The first accepted V5 construction proof is retained as an interrupted
  zero-write pre-root orchestration stop: local command assembly used host
  `python3` with heredoc/stdin source, so the controller interrupted before
  wrapper or mutation. Documents/inventory/candidates remain exact, the V5
  root is absent, and its budget is unconsumed. Complete pre-root
  orchestration-v2 source is now frozen at 39,925 bytes /
  `e12c6cf010a71eaf7185d54b0e7b4fb5238f164c9888daa40308c3319524ca4e`.
  Its exact 32-string pinned-Python `-c` boundary constructs and retains all
  26/25/23 root-phase arrays before `mkdir`. Controller static review rejected
  v2 because its call scanner treated safe qualified `re.compile` as forbidden
  direct `compile`; v2 remains immutable and never ran. Replacement
  orchestration-v3 is frozen at 42,768 bytes /
  `73598cc2af02fe06c88bc316aec045b8dbc71b23d52ad5c919626f6e1bdffcad`,
  with exact self-policy positive/negative fixtures. No runtime authority is
  granted and the V5 root remains absent/unconsumed.
- The accepted outer-v3 action is retained as a zero-write pre-invocation stop:
  the command tool has no direct-argv API, so Main refused shell reconstruction.
  Execution-envelope-v1 is now frozen at 13,619 bytes /
  `15df754ec3d35379969dfd492e952f5731237e0a4284b1e89d08130bbdd36f0b`.
  It defines one `/bin/zsh` non-login command, 42 exact single-quoted tokens,
  token-12-only preservation of 1,077 source LFs and 30 quotes, canonical round
  trip, and 24 negative fixtures. It has not executed; V5 remains absent.

- Date: 2026-10-09.
- Original worktree: `/Users/junhuaxu/autoclip`, branch `main`, HEAD
  `2f361fcddc0e63ae62ee62826e27b54bb8204c53`.
- Current shape after the accepted four-path checkpoint and this source-freeze
  amendment: zero staged
  paths, 15 modified tracked paths, and 156 ordinary-untracked paths. The only
  additions relative to the accepted 154-path B2 delivery inventory are the
  authorized v2 requirement and non-authoritative trusted-context schema seed.
- The accepted M2B-v2 execution preimages were ExecPlan 465,977 bytes /
  `6579339b157a052e8a312842090c7d2d0305e107e5c75478fe31e3361083aea8`
  and STATUS 26,313 bytes /
  `674dd977bdbc0e68038e5355227bf28527523c9175cae93c084f5953ded13049`.
- The later candidate-recovery invocation was authorized against ExecPlan /
  STATUS SHA-256
  `8f62b479aec0d4751501954aefb3a041d4c42640c90f50d34d72957cea206f05`
  / `cb2b517f7963c55f2d2f162fd35f79e03c8a0115d6896edd0d98af5d923dfa39`.
- M1/B2 is complete. The sole B1→B2 addition is
  `docs/requirements/liveclip-agent-runtime-v2-acceptance.md`, mode `0644`,
  16,335 bytes, SHA-256
  `6c262edb9463583614979d9b2e24f12a94c8f1a40c43b4537f95381a9259c3f8`.
- M2 is complete. Sixteen external attempts are retained immutable; the
  accepted candidate is `candidate.dygENR4n`, and all earlier stopped attempts
  remain exact historical evidence in the sole ExecPlan.
- The first M3 run is retained terminal `BLOCKED`: exact run
  `20261009T124056Z-37111cbc` has final state 17,815 bytes /
  `cb6e8a2ff53902dc617281757a6d5a910069109b1e2637ef5929c914ca25a6e5`
  and eight-event log 2,278 bytes /
  `c3ff12b83e7e2bd5894a06d608bd4ab78222e6842fdfeeb41457b12ef28438c4`.
  Planner session `01a120b1-85ac-7432-be0f-1122f40e1142` returned READY
  artifact `c0491867e29734f68bde429514bd2187ee8dec809930c7b385c495c9d2d6a64f`.
  Coder session `01a120b3-f587-7682-80e4-635b1fcfd823` returned BLOCKED
  artifact `fc57f4c96a321017e221d12ee0ed5090673c5f91047cc6cc792154a86eec3470`;
  its event log is
  `eb6789590c6c321947ab806c18f52e04927a56704d82c14ff67fd51af4cc2837`.
  It changed no file and ran no test; no Reviewer, Tester, Runner, Gateway, or
  publication followed. The run and both sessions are immutable and have no
  reuse budget.
- The retained M2 candidate also has 132 ignored cache paths and three changed
  encoding `.pyc` files from the blocked invocation. They are retained without
  cleanup and are excluded from every successor. Git source and the delivery
  baseline remain exact.
- The successor design is frozen at
  `docs/requirements/liveclip-agent-runtime-v2-acceptance-v2.md` and
  `config/loop-engineering/trusted-context/liveclip-agent-runtime-v2-successor-v1.json`.
  The latter is explicitly `SCHEMA_ONLY_NOT_AUTHORITY`; a future builder must
  not copy it. A fresh candidate is reconstructed from immutable
  `candidate.OlsWg1/repo` plus exact B2 patch/71-path overlay, overlays only
  ExecPlan/STATUS/v2 requirement before setup, initializes one run, and only
  then creates the final run-bound record no-replace. Final record, policy,
  toolchain, candidate, and loop-run identities require later literal
  controller acceptance without rewriting the record. No successor candidate
  or second run exists.
- Controller accepted the four-path checkpoint at ExecPlan 1,527,917 bytes /
  `ff79038f45f1e16d1d27cbcabdd1b98330c2cd186e955c171b8d462658121939`,
  STATUS 50,132 bytes /
  `02a1be7a512d6b28389d0dee53bb8cd257c3c1955b460fa2c8bc1d01cb5a8a5a`,
  v2 requirement 8,771 bytes /
  `31e967e04b3f9987e5c0a9ac00b809c215aed543f9da035c3a06e73ebc976400`,
  and schema seed 6,328 bytes /
  `73988e662bc2d74b5a1be8393c16a33a17bd481e290d23c063f8be26adda2e16`.
- Complete M3S-v1 transport-writer and successor-preparation-driver source is
  frozen inside the Living ExecPlan: writer 9,473 bytes /
  `cc96a333e7a7b8a68873c23752f83806d9bf2af799f19c3b2715d8608fa4c28c`,
  driver 204,829 bytes /
  `c9e6b0898b4563d7be792d449f00c451f519932043b2824f53b8ad5177fbc5ea`.
  Its authorized root-only prerequisite is retained stopped and immutable.
  Transport rc0 created source receipt 12,629 bytes /
  `a80b99218f6bbcd6af03a21429b7a18bec9ec66f9b18eb9eeb0d246e9373df32`;
  self-check rc1 created result 3,497 bytes /
  `f6d7dd31336c445e48cdd034eb34c48a54db9493ba7d14c956c029e52973395f`
  with exact `RuntimeError: forbidden successor source token`. The scanner
  matched the contiguous V2 tokens embedded once each in its own forbidden
  tuple. Writer self-test, finalize/index, reserved result, allocation, and
  successor execution never ran. The V1 root budget is consumed with no
  repair, retry, replacement, or reuse.
- Complete M3S-v2 writer/driver source is now frozen separately in the sole
  ExecPlan under unique V2 markers: writer 9,473 bytes /
  `3d088cb3993c8595cb5e6f849022642e9cf9956f845d1f6d2c3fd42ae257b0ea`;
  driver 213,685 bytes /
  `d0ab0b9841a8f717e32871fc47d4e58ffa407b24b73edaf2ee4527dad0f969e4`.
  Its authorized transport passed, then self-check stopped on the exact
  `KeyError: 'uid'` identity-shape defect. The fixed V2 root and two receipts
  are consumed immutable evidence; writer self-test, finalize, final index,
  reserved result, candidate allocation, and successor execution did not run.
- The separately authorized V7 recovery is consumed and retained as immutable
  `candidate.z6EbTJew`. Its 18,963-byte outer result SHA-256 is
  `965410eea760647cb8c93b8ea4fd1f62911cf9c6095097692f8f9c32964a6565`,
  phase `M2_CANDIDATE12_RECOVERY_V7`, rc1 in 228.831454 seconds with clean
  wrapper boundaries. Materialization, candidate dry run, setup rc0 in
  169.945706 seconds, readiness PASS in 4.817772 seconds, exact five-profile
  staging, and doctor rc0 in 2.467332 seconds passed; doctor stdout was 182
  bytes / `bebb0f17dcd7676f619f279aaed9b2f10c60b1f61f38d3c093bcb0958f27d789`,
  stderr was `EMPTY`, and termination validation passed. It stopped only when
  the post-doctor preservation recheck treated the authorized current suffix
  as predecessor drift. Final index SHA-256 is
  `9ccbe08be4d85dd3da44d174daeaac5c8e31f8dbdb7bc967f4aad680ba1ab149`,
  verdict `M2_STOPPED`, with complete sealing and no errors.
- Complete V8 writer/driver sources and root-only/later-execute schemas are
  frozen in the sole ExecPlan. The controller-accepted root-only prerequisite
  is complete at fixed root `m2-candidate-bootstrap-v8`; its no-replace root
  budget is consumed and its reserved execution result was later consumed by
  the accepted M2 recovery. The
  first mkdir request was rejected before execution under Workspace
  permissions and consumed no budget. Trusted Main session
  `01a10318-0d21-7ff0-ad1f-39cb721c815c` was then explicitly switched to Full
  Access under standing authority, repeated all pre-root gates, and completed
  the root-only sequence. V8 requires exactly fifteen immutable predecessors
  before allocation and exactly those predecessors plus the one recorded
  current suffix afterward. Source identities are writer 9,519 bytes /
  `4caa96ec73cb8daa4b06dab4d9b85bac742a802eb8581561a5ff8c6c462c0c34`
  and driver 171,888 bytes /
  `9fde9fe529e45bdd02b077a1d04b6b19f985d35247baca519c913bb88147f483`.
  Root receipts are source 12,667 bytes /
  `477cea9ff8c5653f23e63be706f3631de45859a2da68fcd31a26db6342c5f31f`,
  writer self-test 40,631 bytes /
  `6d2e213bc491c20e9700324bbee46ea577b5a81459b39ca4675707704a22deae`,
  self-check 2,067 bytes /
  `8f48e0e561251032245d40a26e7e7cd243a9bfd6b9d51e6c103d86cf224a022d`,
  and final index 8,138 bytes /
  `8292fb7bea9de4bd20f6fcfdae7d73c3c5d45be91320683321728a9921a6a053`.
  Transport/self-check returned rc0 in 0.076077/43.913704 seconds with clean
  wrapper boundaries, the seven-case candidate-set matrix passed,
  preallocation was exactly fifteen, stderr selected `EMPTY`, and verdict is
  `M2B_V8_READY_FOR_CONTROLLER_REVIEW`.
- The consumed V8 recovery result is 18,103 bytes / SHA-256
  `ad14c8f8b08f0c7be98d74ced9316b803348772ac6af17c78ec30362d3e1ee69`,
  rc0 in 135.706981 seconds with no timeout, truncation, session, credential
  variables, capture error, or wrapper error. Its sole suffix
  `candidate.dygENR4n` has final index 12,784 bytes / SHA-256
  `ee23214f812a8e946fe0025008ef57d4aa2a5e643c13e3605245f9af8a0d1a7d`,
  verdict `M2_PASS`, complete sealing, and zero errors. Final repository is
  27,404 paths / 573,789,992 bytes /
  `093077b1bff4f830e01a2c7eb0b7d004ccf18f06204ef2e96cab6cdb48cc1743`;
  completed attempt is 27,444 paths / 587,853,366 bytes /
  `c5d16be1ce9c79e7fc0332240f42a4785364539e83c9cf5b129a13c1a7c5aec3`.
  Setup/readiness/toolchain-receipt/doctor-validation/preservation SHA-256 are
  `dc5976c779ede976530ec9da74ffec3f01d127f95c928a9914da6ab74b4adeb3`,
  `c37bef9c37c8c7ebdd498ba3c9e371f54fd8f71079f40c3db1796fd152f00d37`,
  `49194ea50952cb076522b0eebdf3f91ccb148fa4f6d2ef5646ad63aac4963c5a`,
  `f281cf8a5b599ab651a01d3aaaaa59e296255382b673f3d36f8bbfccfeb408da`,
  and `2b75bbd88121f4bfeaf936692a10a92de0620168a9734c78887d6c7c9e31a830`.
  The toolchain receipt's distinct embedded fingerprint is
  `5a6f3a3189d00575c7699418c94c0c1af377e467e1f2b523b606b8474397d63d`.
  V8 has no retry budget. The first M3 run is retained BLOCKED; its successor
  requirement/schema and complete M3S-v1 preparation source are frozen, but
  the external root, successor candidate, and new run do not exist.
- Controller accepted the bounded read-only recovery design against ExecPlan /
  STATUS SHA-256
  `2dbb9c8ff870b0fe6719dc1dd64cd2fd3e35b93a53f07716d39f1ca698a93084`
  / `173ab26781eaa2e1b5f883dac1fe075d10d082d1f9f9d6ec07fcf35c5f8f7f3c`.
  The sole ExecPlan freezes complete V3 writer/driver source and schemas. The
  fixed `m2-candidate-bootstrap-v3` root-only prerequisite is now sealed,
  immutable, and controller-accepted; its one-shot root budget is consumed.
  Frozen source identities are writer 9,519 bytes / SHA-256
  `fd30a91c02f35a9d703cbdf3955e491c96ebfdf9fd43973140e50e980b717dcb`
  and corrected driver 94,656 bytes / SHA-256
  `b1cc90ee2409b1f6612eb631f500868f1a5a0f7243ea7806f3c222d4ece04c06`.
  Controller static review caught and corrected the two duplicated V3
  receipt-phase fragments before execution.
- `candidate.xp23hqNY` is attempt nine and the retained recovery point. It
  passed canonical 2,322-record materialization, bounded setup, absolute alias
  and 102-link safety, candidate-local roots/assets, and direct readiness with
  fingerprint
  `b5fe2fcec70cbe44a4c0334959ee89abed5880b8a455dbcab88ac9b5684c51a3`.
  Its bounded doctor stopped only because the five reviewed profiles were then
  absent. It remains immutable and must not be reused.
- Controller-authorized attempt ten consumed its sole suffix as
  `candidate.iyme1x_i`. Canonical 2,322-record materialization and the dry-run
  contract passed at SHA-256
  `e6bc1213d482c38c78b97c3390ea35c05ca05efb2c1ff1d754e3894a04fd8044`,
  using patch/list `472638a7...` / `1cbfb3a7...`. The receipt-local wrapper
  returned 1 after 2.006929 seconds on an unterminated string literal before
  invoking Make. No `setup-result.json`, setup, `uv`/network/dependencies,
  readiness, or candidate doctor exists. The attempt is immutable, the suffix
  budget is consumed, M2 is stopped/incomplete, and M3 remains unstarted.
- Read-only diagnosis proved the nested JavaScript-template to Python-triple-
  quoted serialization changed the intended backslash-`n` into a literal LF
  and split `f.write` across source lines. The controller accepted the fixed-
  shim amendment at ExecPlan/STATUS SHA-256
  `29223e84e8f4dd6972b245d8d265edf3b30fd8d9175c57edf862384c05dbcf6b`
  / `fff23e6ef27e777826008980823e9ec03bd69795540f052fdea61f54ce426114`
  and authorized exactly one candidate-eleven suffix.
- Candidate eleven consumed that suffix as `candidate.3WBt3ldA`. All
  pre-suffix gates passed, including the accepted 167-byte compile probe
  SHA-256
  `3eb3586492977107500a4bd58d7e6184b4f45bdd44c942b83766440106abb253`.
  The first post-allocation receipt-bootstrap command instead used a distinct
  167-byte double-quoted literal SHA-256
  `4866e8e8c404448f99fbceee58c732645ff78cae223cacdb6a94f98b7aca234c`
  and its assertion returned 1 before operational receipt bootstrap or wrapper
  copy; a later fail-closed action sealed only the six evidence files below.
  Verdict: `STOPPED_POST_ALLOCATION_PRE_MATERIALIZATION`; no repository exists.
  There was no clone/materialization, patch/overlay, Make, `uv`, network,
  dependency, readiness, doctor, M3, role, test, inference, or evaluation.
- Candidate-eleven receipt SHA-256 values are stop
  `493e500527c85e856acb4b32112d931411b09c6374b0d238325f2b4c574a0057`,
  preservation
  `dd3805ee771b0ee9cb629feab78557fe295bde250848a5ff0ac35695f8a5343b`,
  final index
  `d2ba3bc4d27673f2c67b46ba34fe23d0a5d32fd65dd16d9789499af1ba99175d`,
  final-attempt manifest
  `6385df3cb688095ca086cb8a22d411027eb9e89b5da7612b84164642d79f4640`,
  and empty repository manifest
  `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`.
  The sealed final tree is 9 paths / 7,013 regular-file bytes / SHA-256
  `1b6a840cb4e1e77cf3e4577cbcb0ffaca9294bbd101b15523e641b0f596272df`.
- Read-only recovery analysis diagnosed the exact candidate-eleven mismatch:
  the accepted 167-byte single-quoted probe is SHA-256
  `3eb3586492977107500a4bd58d7e6184b4f45bdd44c942b83766440106abb253`;
  the independently retyped 167-byte double-quoted post-allocation probe is
  SHA-256
  `4866e8e8c404448f99fbceee58c732645ff78cae223cacdb6a94f98b7aca234c`.
  Equal length and semantics did not provide byte identity.
- Candidate-twelve recovery design B is now documented in the sole ExecPlan:
  a complete frozen external `candidate-driver.py` plus direct execution
  through the immutable attempt-nine wrapper. Recovery-level wrapper-only
  design A is incomplete; recovery-level shell-only design C is rejected. The
  exact fixed M2B root is
  `/Users/junhuaxu/Library/Application Support/LiveClip/engineering-candidates/agent-runtime-v2/a822890ace12/trusted-tools/m2-candidate-bootstrap-v1`.
  At that design checkpoint it was absent and the complete driver existed only
  as a frozen ExecPlan source range; the later completed M2B state is recorded
  below.
- The read-only M2B transport audit found that no current
  `tools/loop_engineering` CLI or reviewed macOS utility provides the required
  generic O_EXCL payload write plus complete file/directory fsync; internal
  helpers are not CLI authority. Transport option C is the sole narrow
  exception: the ExecPlan now freezes a complete 9,513-byte minimal writer and
  complete 72,757-byte deterministic driver plus exact schemas. Only that
  writer may use Python `-c`, once before any suffix, through the immutable
  attempt-nine wrapper. All other generated/reconstructed source is forbidden.
- Source identities are writer SHA-256
  `a85a7fe5bab9cdb3d5f4bee6c6742702f39e952ad5b9bb719e4f675c0ceb01f0`
  and driver SHA-256
  `b7b8827721d0903f4cd4a604b054982db618c74de077abbe6f12481ea780f8a2`.
  Controller read-only finalization independently extracted them, reproduced
  compile-only and Ruff F/B/S PASS, and reproduced exact normalization plus
  transport/self-check/finalize command hashes without executing either
  source. The reviewed preimages were ExecPlan 339,502 bytes /
  `fc9a75b9754a214f8f35831f8228db4151e1d6960600513b1594798da88fa076`
  and STATUS 20,673 bytes /
  `794d4e33f4a815feb3cf502871eba6c0f9b92797395fed9ae5b73935dffa4ef3`.
- The accepted M2B invocation stopped during read-only preflight, before root
  creation or source execution. Its raw seed dry run matched nine lines /
  2,278 bytes / SHA-256 `04574608...`; exact replacement with ASCII
  `<CANDIDATE_REPO>` produced nine lines / 1,390 bytes / SHA-256
  `a3e7625157819a5d66d14eeb8af2ab74f58ba1d3591ce098db9585734dbca969`,
  not the formerly frozen `dc9ad28f...`. `shasum` and OpenSSL agreed. Verdict:
  `STOPPED_PRE_ROOT_SEED_DRY_RUN_NORMALIZED_HASH_MISMATCH`. The fixed root is
  still absent at that historical stop, the one-shot mutation budget was then
  unconsumed, and the stopped authority was not reused under superseded
  document/source/command hashes.
- Final ExecPlan/STATUS hashes and literal command JSON cannot be embedded back
  into the same finalized documents. The plan freezes source, schemas, and the
  canonical JSON algorithm; the controller must compute and bind closed-
  document and exact argv-JSON hashes in memory. STATUS is not a command
  contract, no command-manifest file was added, and projection hashes are not
  used.
- Controller static review rejected M2B authority for the prior source freeze.
  The sole ExecPlan now carries the documentation-only correction: descriptor
  reads compare first/second/final descriptor and path identity; self-check,
  finalize, and execute enforce exact owned private M2B roots and phase receipt
  sets; finalize binds exact env/argv without a fifth receipt; and candidate
  failure sealing uses the accepted frozen preflight snapshot with independent
  best-effort no-replace steps and truthful incomplete-seal reporting. The
  driver contains one import block. At that historical checkpoint M2B remained
  absent and unauthorized.
- Controller second static review found one deterministic pre-execution
  blocker: on this host, pinned Python under the exact `env -i` contract adds
  `__CF_USER_TEXT_ENCODING=0x1F5:0x0:0x0`; no `LC_CTYPE` appears with fixed
  `LANG=C`/`LC_ALL=C`. The corrected driver requires uid `501`, binds hex
  `1F5`, admits exactly that one runtime-injected key, and still rejects every
  other extra name, credential-like name, and `CODEX_HOME`. Whole-environment
  equality and `env -i` remain strict; M2B was still unauthorized at that
  static checkpoint.
- Future M2B root creation is fixed to direct no-`-p` `/bin/mkdir` argv under
  umask `077`, with exact `0700` root/home/tmp/receipts checks, and consumes the
  one-shot budget. The wrapper exclusively creates `source-receipt.json` but
  does not fsync it; successful driver self-check/finalization must validate
  and fsync wrapper receipts unchanged before `final-index.json`. A failure
  retains the root and best-effort receipt without retry or durable PASS.
- This documentation-only transport correction began from controller-accepted
  ExecPlan/STATUS SHA-256
  `7f204839c0391a49dc449759785574bbd99188756fd2739916958bf1a9b031fd` /
  `70250398cf24642ad3bb4d1d8bf62fb884d5ae94743aaf744d1204e7cb43927a`;
  the fixed M2B root was absent and no mutation budget was authorized.
- This static-review correction began from controller-verified ExecPlan/STATUS
  SHA-256
  `4929f52523af654b1ceb4cb7bdbae7206e8844a2d55212c83fe3b7087abd6c29`
  / `eb3a88ae382284e44b3acb6e6a5f69b4fe125d0b29dd5ff8402c23e496a63530`,
  with branch/HEAD and 0/15/154 counts exact and the M2B root absent. It grants
  documentation edits only.
- This second static correction began from ExecPlan/STATUS SHA-256
  `4540b4b186b6a9124a2541c47b15a5483583174b02eddb81c83e4b913ba8f9e8`
  / `3289f80804d4941ce2cd8dff0a760dbf8737f8eddf10814e57718282d0bceced`;
  writer `9513`/`a85a7fe5...` and driver `72448`/`e74ce510...` matched, and
  the fixed M2B root was absent. This task grants documentation edits only.
- M2B is complete under independent controller acceptance. Its fixed root is
  real mode `0700`, uid `501`, with exactly `candidate-driver.py`, empty
  mode-`0700` `home` and `tmp`, and mode-`0700` `receipts`. The driver is
  regular non-symlink mode `0600`, 72,757 bytes, SHA-256
  `b7b8827721d0903f4cd4a604b054982db618c74de077abbe6f12481ea780f8a2`.
  Receipts are source 12,650 bytes / `d9108018fdc72a2dd19932e1f20c79a6a44a509fede323ce9b853fd39d37672d`,
  writer self-test 5,774 bytes / `2a6710c99dadfd85016bd9bdef6d4a62fb0cb75df749556a831b6899660ada9e`,
  self-check result 2,063 bytes / `879347e9dbb7994634a0b2595059bbe82f24ed876a3c8393135c72906a535361`,
  and final index 8,111 bytes / `2a2150509084af1a8a30a1bbc01d9143acead848dc1f95785cec592b6c90602c`.
  Transport/self-check were rc0 in 0.076131/0.078809 seconds with no timeout,
  truncation, session, credential variable, or wrapper error. Self-check is
  PASS and the accepted index verdict is `M2B_READY_FOR_CONTROLLER_REVIEW`.
  The index binds transport/self-check/finalize argv-JSON SHA-256 values
  `533dc5ba84c0dbcc428af834776e18e1f01c97c0e30e7ca60cf3eacbc37cb145`,
  `99ecee3bb4edbdb80c8413202eaf9ea57c16d19364133039a7f2ba77d1ad4ad5`,
  and `78b6a72b08a84ca0b6df01a86a8f22f08e8378daa0a1b5dbfa1c76a55f98d532`.
  Later `plutil` null/fragment probes were non-authoritative read-only failures;
  independent Python JSON parsing of all four unchanged receipts passed.
  The M2B one-shot budget is consumed. The later authorized candidate-twelve
  invocation consumed reserved `candidate12-execution-result.json` but stopped
  before `mktemp`; exact stop evidence follows.
- Candidate twelve is `STOPPED_PRE_ALLOCATION_SOURCE_PATCH_MISMATCH`. Its
  regular non-symlink mode-`0600`, 4,288-byte execution result SHA-256 is
  `32c6f90c3362f44c369123b95a7e88ad823159a904c4d9d78fd22d7d916d2932`.
  It records phase `M2_CANDIDATE12`, accepted 29-element / 1,553-byte argv JSON
  SHA-256 `7e81b82ed5c7e02f68e6203af045e6ffbf6b95366dc6d544649574ebab291319`,
  rc 1, and 18.029543 seconds with no timeout, truncation, session, credential
  variable, or wrapper error. Direct Git patch stdout remains 204,622 bytes /
  `472638a7f6c78634d3dbe5508716fc3a1328761dd4047eaf1b20c4d494a01254`;
  checked-in `run_bounded` merges the 106-byte macOS `confstr()` stderr
  warning, yielding 204,728 bytes /
  `4e62656b1a23ae71053c459a547614ff0cdf4088d3ae8d7400db5d44548ecf9a`
  and the fail-closed patch mismatch. No suffix, candidate receipt/index,
  setup, dependencies, readiness, or doctor exists. The invocation is
  exhausted; the mktemp-based suffix-consumption condition was not reached and
  is not retry authority.
- The accepted recovery analysis found no suitable existing trusted
  control-plane split-capture API. Checked-in `run_bounded` merges stderr;
  the product-media helper lacks the required control-plane schema; ad hoc
  capture is rejected; and changing checked-in process code is a separate
  formal engineering change.
- The source-freeze checkpoint froze a complete V2 writer and self-contained
  split-channel driver for the then-absent fixed root
  `/Users/junhuaxu/Library/Application Support/LiveClip/engineering-candidates/agent-runtime-v2/a822890ace12/trusted-tools/m2-candidate-bootstrap-v2`.
  Writer identity is 9,519 bytes /
  `eda1e429cdc99b41e122bcc30198eb18ac7797731c462c12316185f93e393c44`;
  driver identity is 86,091 bytes /
  `2abd73fd6ab5aea0232a9c80efa9e81e487d3b42223978089a4f60246a024bb8`.
  V1 source/root/index/exhausted result remain immutable. At that historical
  checkpoint no V2 source had executed and no root/receipt/suffix existed.
- The exact accepted-hash M2B-v2 prerequisite invocation is exhausted. Its
  read-only preflight stopped before root creation when the code-window nested
  probe produced accepted Git/Make stdout with empty stderr, while the frozen
  driver required the warning-only variant. The no-replace root budget remains
  unconsumed, but the stopped authority cannot be resumed or reused.
- Bounded read-only variance analysis found execution-context/CoreFoundation
  temp-lookup variance rather than source drift. Three code-window repetitions
  produced empty Git/Make stderr with unchanged accepted stdout; the controller
  independently reproduced the exact 106-byte Git warning SHA-256
  `54dc9366cf6d804bdf5ae1ffa172dab10fc68a63170232134cbe6981ee4634fb`
  and 107-byte Make warning SHA-256
  `9be89810bccd44cab5ea0ef848239780aa50c9b9bddc6f84b508bedbc56b689f`
  under the same seven-name child environment.
- The still-unexecuted V2 driver now fails closed on every stderr value except
  exactly empty (`0` bytes / SHA-256 `e3b0c442...`) or the matching frozen
  tool warning. Each selected Git or byte-bound Make gate records canonical
  policy `empty-or-exact-darwin-confstr-v1`, variant `EMPTY` or
  `DARWIN_CONFSTR_WARNING`, observed size, and observed SHA. Exact stdout,
  argv, CWD, environment, bounds, and all other gates remain unchanged; setup
  retains its existing bounded raw diagnostic-channel contract.
- M2B-v2 is now complete and independently accepted as a deterministic
  prerequisite. The immutable consumed root is
  `/Users/junhuaxu/Library/Application Support/LiveClip/engineering-candidates/agent-runtime-v2/a822890ace12/trusted-tools/m2-candidate-bootstrap-v2`.
  Root, empty `home`/`tmp`, and `receipts` are real uid-`501` mode-`0700`
  directories. `candidate-driver.py` is regular mode `0600`, 86,091 bytes,
  SHA-256
  `2abd73fd6ab5aea0232a9c80efa9e81e487d3b42223978089a4f60246a024bb8`.
  Sealed mode-`0600` receipts are source 12,662 bytes /
  `442394b83e6332f80a9f2bb0689b6738f33056b7d2132e64ecc9e06e602d0f20`,
  writer self-test 10,411 bytes /
  `dab8f3aa29901e87ddd757dc732d40e18a7584a5ddfe2e5d026112d0d2fa3589`,
  self-check result 2,066 bytes /
  `d8e45839edef15060afb4a6abeda39240e64541f7bcee27085cb3974c23af57c`,
  and final index 8,131 bytes /
  `e8410c9fee3e4841b8569ba69c35694d913152b26b375e175473c3ddb6720a08`.
  Source write/self-check were rc0, writer self-test has `error: null`, and the
  final verdict is `M2B_V2_READY_FOR_CONTROLLER_REVIEW`. The selected contract
  is `empty-or-exact-darwin-confstr-v1` / `EMPTY`, 0 bytes /
  `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`.
  Bound transport/self-check/finalize hashes are
  `77feaecc3bc239d05b49ea975aa1a58c1a5da9fd19846ee90081a3f0a5845981`,
  `f0ce61a21178a86b96e696f85f6106b2d911fe8e38efe2b1dc373b2118f555ce`,
  and `f522b21ab9519f7698763e7813a4c27d2d6246ed82e458be3df21f937c9f1fbe`.
  The root-only prerequisite was complete at that checkpoint. Its later
  recovery execution result and twelfth candidate are recorded immediately
  below.
- The one-shot M2B-v2 recovery invocation is consumed. Its regular mode-`0600`
  `candidate12-recovery-execution-result.json` is 10,071 bytes / SHA-256
  `7333d9a69f2799a196e645ae667e37b694ee653b0c012df49e0cfece40531eb9`.
  It records phase `M2_CANDIDATE12_RECOVERY`, rc `1`, elapsed `23.497345`, no
  timeout/truncation/session/credential variable/wrapper error, and the exact
  accepted 29-item / 1,553-byte argv SHA-256
  `298020e60025dff4b6d7efd2fba885127db7d443d4979608ffadef23dfeffdd0`.
  Suffix `candidate.UU7EAiJG` is consumed and immutable. Preallocation and
  canonical materialization passed; actual source/candidate manifest SHA-256
  is `e6bc1213d482c38c78b97c3390ea35c05ca05efb2c1ff1d754e3894a04fd8044`.
  The prompt's conflicting longer value is rejected as unsupported by both
  receipts. Stop receipt is 181 bytes /
  `8cf9e100976c247959c15ec6d0b648901dbc88c41a1adb494a273f85c8fe0a9f`,
  error `RuntimeError: stdout size mismatch`, verdict `M2_STOPPED`. Final index
  is 4,691 bytes /
  `4bcac4418cf7a6cf478f4bd39e622875ec6c46f95ade6388eae255b45f40b626`
  with complete sealing. Repository is 2,868 paths / 44,410,327 bytes /
  `4baa11929abbf7e1f82007e9e4ec0f59902343ec9775c6dd15f705ad1e969df8`;
  complete attempt is 2,883 paths / 47,382,876 bytes /
  `ce127bc2e21f2d0a089858eb965a8e0f9ccf33ecedd35bd9deb9ef04d64738f6`.
  At that historical V2-stop checkpoint exactly twelve candidate directories
  remained; the later V3 attempt raised the current count to thirteen.
- Official Astral `uv` 0.12.17 remains privately staged and verified. Its
  mode-`0700`, 37,062,400-byte arm64 executable SHA-256 is
  `0d7e9f718697816408bba1bc0a915d60e1f82ef23bf339ce88f00b9d2f26e0ad`;
  the archive SHA-256 is
  `85f00cbdc6dd3e97eba4c31b4d014375a9fdfe8f570023b84e5102fc3456896b`.
  Code-signature verification passed; artifact attestation was unsupported.
  Its only executions were attempts eight and nine's bounded setup commands;
  it was never added to PATH and `uvx` was not run.
- The trusted outer wrapper is now pinned to `/opt/homebrew/bin/python3.12`,
  resolving to Homebrew Python 3.12.14 arm64 at
  `/opt/homebrew/Cellar/python@3.12/3.12.14/bin/python3.12`, SHA-256
  `c6af311afeecacffa2c8c627894a4bf9d3e2c00e0d3dc91b26c881c4b0615d23`.
  Its credential-free import probe passed. It is wrapper-only; pinned `uv`
  must still create candidate-local managed Python and dependencies.
- M2P consumed its one mutation budget at retained root
  `environment-gate.profile-install.olrtg34r`. `loop-profiles` returned zero in
  0.14253508299589157 seconds and its post-install receipt proves exactly the
  five reviewed regular non-symlink mode-`0600` additions, unchanged
  `config.toml`, unchanged original, and identical pre/post metadata for the
  other 40 immediate Codex-home entries (SHA-256 `465a9ae4...`). The bounded
  original-worktree doctor returned zero in 8.323894000001019 seconds with
  exact `READY root=/Users/junhuaxu/autoclip codex=/opt/homebrew/bin/codex
  commands=4`.
- The retained M2P attempt remains `STOPPED_FINAL_PRESERVATION`. M2P-R then
  matched the repository queries and all seven indexed receipt/install/post-
  install/doctor/stop facts, but stopped before later gates because the live
  Codex-home name set had added exactly `memories_1.sqlite-shm` (regular
  `0644`, 32,768 bytes at controller observation) and
  `memories_1.sqlite-wal` (regular `0644`, zero bytes), with nothing removed.
  Contents were not read; no write/rerun occurred; the provisional READY
  verdict was not emitted.
- Controller reconciliation removes whole-live-Codex-home name/metadata
  equality from the LiveClip acceptance boundary. Active controller/writer
  sessions legitimately own dynamic SQLite/WAL/SHM/index/lock state, so a
  volatile-name allowlist will not be broadened or repeatedly enumerated.
  The independently sealed five-profile install boundary plus exact doctor
  READY and current exact static/protected identities are accepted as
  `M2P_PASS_RECONCILED_STATIC_TARGETS_DOCTOR_READY`. Neither stopped execution
  is retroactively PASS, unrelated runtime writes are not accepted, and no
  product engineering is accepted.
- M2P receipt SHA-256 values: preflight `4f8b5d37a3d731540c4d1c731c336c07502e55e5e478a6078c9ee966d4dfa508`,
  install result `0bb3f4106eb78870eced1097e3e8c3d6ea689ddb065093747ed0cff8b50163a9`,
  post-install `076b85dcd30fbb12c6f91be97097bb30ec55c08a7c5d62eaf681c1911c4b8541`,
  doctor result `070c1befe2fdbf549efcd0d1b2d5ad345eee6f66a9a537981efed4a05dcc3475`,
  stop `42fe10ccce844630b2ca1b37ca64ed3002366a7ce7fa3c9da9dda4e32e34f402`,
  final index `c67627b6ba064b177c228486852c24c5c4a12c226503b5d11277f68567b14da4`.
- All five installed profiles remain exact. Current `config.toml` is a regular
  non-symlink mode-`0600`, 1,471-byte file, inode `70627515`, with mtime,
  birth, and ctime `2026-10-05T21:07:39-0700`, SHA-256
  `5867648914af98477ad9f83e6e79ee48fce60b8dd42b7839bd73e335f1a654d0`.
  The controller correlated this current identity with the historical M2P
  1,473-byte/`32f2f367...` boundary by an in-memory allowlisted substitution of
  the single non-sensitive top-level `model_reasoning_effort="max"` scalar to
  historical `"xhigh"`. No credential or unrelated config value was printed,
  persisted, or used. Historical receipts remain unchanged; candidate twelve
  validates the current identity, and the five role profiles independently
  pin their reviewed reasoning settings.
- The current original differs from frozen B2 only at this STATUS and the sole
  Living ExecPlan. All eleven attempts and the trusted tool remain unchanged.
- The frozen B2 seed and 102-record original completed-run/delivery/source/
  transcript manifest remain protected and unchanged at SHA-256
  `d929781748edabdd562f2f386cdfc3f92d4f8cc1339e0249fc33e92b11364a31`.
- Installer and doctor retry budgets are zero. M2P is complete under the
  reconciled static-target/doctor verdict. At that checkpoint M2 remained
  incomplete; the later V8 candidate closes M2, and the first later M3 run is
  retained BLOCKED while fresh successor work remains unstarted.
  Attempts ten and eleven cannot be repaired or reused. Candidate
  eleven's suffix budget is consumed. Candidate-twelve M2B is complete and
  immutable with its budget consumed; its authorized execution invocation is
  exhausted at the preallocation stop. No suffix was allocated, so the
  mktemp-based suffix condition was not reached, but no retry is authorized.
- Candidate-twelve reconciliation pre-edit correlation: Living ExecPlan
  SHA-256
  `53d7a446d5e6e4e2b5952a2bd02dcf66d9b11a460f8fb663d1ccbd86f1b12859`;
  STATUS SHA-256
  `46c3a12557fa2a727be2c2261f64d1d19c7022ba78db032c7dcb64eb2dd82823`.

## Completed Agent evidence

`agent_v2_oauth_full_v4_20260928` completed at turn 83 with 83 events and 61
artifacts. It selected 30 candidates: 20 `short_highlight` and 10
`mini_lesson`.

Result:
`data/evaluations/agent-v2-oauth-full-v4-20260928/agent-run-result.json`

Result SHA-256:
`0c226f6aa8ca52c15441fabb2a6be316f16cf09288be90c9d1d8370df3f25e6a`

Run identity SHA-256:
`e16912ef6dd5b4569e5ce90cc35def0171ffc8142ffa705efd6e69a6bcf62440`

The five-file completed bundle, 95-file delivery tree, source, transcript, v1
compatibility path, and dirty-worktree inventory are protected. The completed
inference is not authorized to resume or rerun.

## Acceptance status

- M3S-v13 root-only prerequisite: `M3S_V13_READY_FOR_CONTROLLER_REVIEW`,
  consumed and immutable.
- M3S-v13 credential-free candidate recovery:
  `M3_SUCCESSOR_PREPARATION_V13_READY_FOR_CONTROLLER_REVIEW`, consumed and
  immutable as `candidate.KWbe2iGW` / `20261012T225001Z-e23eba62`.
- M3S-v13 auth handoff: `READY_FOR_CONTROLLER_REVIEW`, consumed and immutable
  at the exact sanitized receipt identity above.
- M3S-v13 formal dispatch: consumed terminal `blocked` at Planner cycle 2 /
  code cycle 0 with exact evidence above; no retry or reuse.
- M3S-v14 design: static closure only. Root, result, suffix, init, auth, and
  formal budgets remain unconsumed; next boundary is separately accepted
  root-only creation with a preaccepted canonical controller receipt.
- Completed product-model inference: `COMPLETED`; immutable evidence only.
- M1 bounded requirement: `PASS`.
- M2 source-equivalent pre-setup candidate: `PASS` in `candidate.OlsWg1` and
  `candidate.5jh3bylk`.
- M2 `candidate.c79YYSLQ` materialization: `PASS`; canonical raw-manifest gate:
  `STOP_NONCANONICAL_CLASS_TOKEN`.
- M2 `candidate.o99gfxup` canonical materialization: `PASS`; exclusion gate:
  `STOPPED_PRE_SETUP_FALSE_POSITIVE`.
- M2 `candidate.jyq_n37h` canonical materialization and corrected exclusion
  predicate: `PASS`; setup: `STOPPED_PRE_UV_UNQUOTED_PATH`.
- M2 `candidate.cQnaAbOf` canonical materialization/pre-use/setup:
  `PASS`; mandatory post-setup safety:
  `STOPPED_BROKEN_RELATIVE_MANAGED_PYTHON_ALIAS`.
- M2 `candidate.xp23hqNY` canonical materialization/setup/link safety/readiness:
  `PASS`; bounded doctor: `STOPPED_MISSING_FIVE_REVIEWED_PROFILES`.
- M2 `candidate.iyme1x_i` canonical materialization and dry run: `PASS`;
  setup execution: `STOPPED_BEFORE_SETUP_EXECUTION` because the receipt-local
  wrapper was syntactically invalid. Make/uv/readiness/doctor: not run.
- M2 `candidate.3WBt3ldA` pre-suffix gates: `PASS`; post-allocation receipt
  bootstrap: `STOPPED_POST_ALLOCATION_PRE_MATERIALIZATION` because the probe
  bytes differed from the accepted compile probe. Repository/materialization/
  setup/uv/readiness/doctor: not run.
- Candidate-twelve M2B prerequisite:
  `M2B_PASS_CONTROLLER_ACCEPTED`; source ranges, current config gate,
  phase-root checks, UID-bound macOS environment entry, failure sealing, and
  schemas remain frozen; the exact external driver and four receipts are
  sealed and accepted. The reserved execution result now exists with the exact
  accepted preallocation stop above; no suffix exists.
- Candidate-twelve execution: `STOPPED_PRE_ALLOCATION_SOURCE_PATCH_MISMATCH`;
  invocation exhausted, no `mktemp`, candidate, setup, readiness, or doctor.
- M2B-v2 split-channel recovery:
  `DETERMINISTIC_PREREQUISITE_PASS_CONTROLLER_ACCEPTED`; the root-only budget
  is consumed and its immutable prerequisite index remains sealed.
- M2B-v2 candidate recovery: `M2_STOPPED`; result and suffix budgets consumed,
  preallocation/materialization PASS, candidate dry-run raw stdout-size gate
  STOP, complete sealing, no retry authority. No pre-setup receipt, setup,
  dependencies, readiness, doctor, M3, role, engineering test, render, human
  review, or model inference exists for this attempt.
- M2B-v3 recovery source/schema freeze and root-only prerequisite:
  `M2B_V3_PREREQUISITE_PASS_CONTROLLER_ACCEPTED`.
  V3 authenticates the sealed seed dry-run, durably records candidate raw
  stdout/stderr before assertions, requires exact eight-occurrence canonical
  normalization and independent raw reconstruction, and retains the exact
  empty-or-107-byte-warning Make stderr contract. The caught duplicate phase
  names remain recorded as a corrected discovery. The immutable mode-`0700`,
  uid-`501` root contains the mode-`0600`, 94,656-byte driver SHA-256
  `b1cc90ee2409b1f6612eb631f500868f1a5a0f7243ea7806f3c222d4ece04c06`,
  empty `home`/`tmp`, and exactly four sealed mode-`0600` receipts:
  `source-receipt.json` 12,662 bytes / `f7cae78d...`,
  `writer-self-test.json` 13,453 bytes / `4a397adb...`,
  `self-check-result.json` 2,065 bytes / `5d67bdd0...`, and
  `final-index.json` 8,134 bytes / `411360b9...`. Transport/self-check returned
  zero in 0.075696/0.34996 seconds with no timeout, truncation, session,
  credential variable, or wrapper error; selected stderr was `EMPTY`; final
  verdict is `M2B_V3_READY_FOR_CONTROLLER_REVIEW`. At that prerequisite
  checkpoint the reserved recovery result was absent, twelve candidates
  remained, and no excluded phase ran.
  The immutable root is
  `/Users/junhuaxu/Library/Application Support/LiveClip/engineering-candidates/agent-runtime-v2/a822890ace12/trusted-tools/m2-candidate-bootstrap-v3`;
  its bound transport/self-check/finalize argv SHA-256 values are
  `e45115085e1e94d0334fde6214b0e357dd635ad3b645e0763a5c753199e42f20`,
  `16b6df29402f8633ec792d06551eae6b26fae0a866fae42156a7fa5542aed49e`,
  and `32ef781cc2d943f7e0e0eb25c24279bb14f74b4b00f815c90e661f091ecab479`.
- M2B-v3 candidate recovery: `M2_STOPPED`. The first orchestration helper
  failed on missing `TextEncoder` before any subprocess or receipt and consumed
  no budget; exactly one immutable-wrapper invocation then ran. Its consumed
  mode-`0600` outer result is 15,045 bytes /
  `98152097833d34293d016fec5c9786801c981d8317ea820da032835fb8edb0bc`,
  phase `M2_CANDIDATE12_RECOVERY_V3`, rc1 in 88.34704 seconds, with no timeout,
  truncation, session, credential variable, or wrapper error; accepted 29-item
  argv SHA-256 is
  `59cd57bfe4fbe8d4a0979c1d3c3611d916a9a0d051e61a7137934368b2abf962`.
  Sole suffix `candidate.22BiM8pO` makes candidate count thirteen. Canonical
  materialization, corrected V3 dry run, setup rc0 in 43.514753 seconds,
  post-setup safety, and readiness with no issues in 4.888082 seconds passed;
  fingerprint is
  `0102ec32fe95bffa83e9213ac73808d33050b7426eedf1eeb7e2ed43330d7077`.
  Persisted `/usr/bin/make loop-doctor` returned nonzero before
  `doctor-result.json`; exact doctor channels and deeper cause are unknown.
  Stop receipt is `4e3c3d7a...`; final index is 9,295 bytes /
  `b0cf3644d1246085f09f63d8d4d4c1f725299439b4564785c643631e49f31ae2`,
  phase `M2_CANDIDATE12_RECOVERY_V3_FINAL_INDEX`, verdict `M2_STOPPED`, empty
  sealing errors. All 22 receipts are regular mode `0600`; result and suffix
  budgets are consumed and no retry/repair authority exists.
- The bounded read-only doctor-gap analysis established a sufficient static
  cause without overstating lost evidence: V3 validated the five profiles in
  `/Users/junhuaxu/.codex` but launched doctor with candidate-private HOME;
  `_codex_home()` therefore selected the sealed private `.codex`, whose only
  entry is `tmp`. Exact V3 doctor stdout/stderr, inner timing/rc, and any
  additional findings remain unknown because no doctor result/raw channels
  were persisted.
- Complete V4 recovery sources and schemas are now frozen only in the sole
  ExecPlan. V4 stages exactly the five reviewed profiles—no config,
  credentials, or unrelated operator-home content—into a new candidate-private
  Codex home and durably records raw doctor channels plus PASS/FAIL validation
  before raising. Writer identity is 9,519 bytes /
  `fe9ef442e0862c84633f28e82188c4e3f94edc4b5205df465760c16b2ef6a491`;
  corrected driver identity is 128,626 bytes /
  `deed4de68c930d5d03e74fd1156008f77edeb24185a5e97711fa9cba8a2a80bf`.
  Controller static review caught stale V3 dry-run phase names and a doctor
  lifecycle path that could escape after command persistence without complete
  evidence. The corrected V4 driver rejects stale active predecessor phases
  and, except for true receipt/fsync failure, persists bounded raw channels,
  structured capture, and FAIL validation for every doctor lifecycle stop.
  Follow-up review found and corrected a remaining edge: initial poll failure
  now still attempts recorded-pid TERM→KILL, and final sealing cross-validates
  capture/validation lifecycle evidence. A spawned or unknown child without
  proven termination forces the named pre-index sealing error and cannot yield
  `sealing_complete=true`; a fully evidenced no-child spawn failure may seal.
  A pre-doctor stop with neither capture nor validation receipt now yields a
  complete `DOCTOR_PHASE_NOT_STARTED` decision with `safe_to_seal=true`, null
  child state, and no termination claim, so earlier-stage stops can seal
  normally while partial receipt pairs remain incomplete.
  Final receipt correlation now includes `doctor-command.json`: the safe
  no-phase record requires command/capture/validation all absent, while any
  command-only, pair-without-command, fixed-command mismatch, or other partial
  core forces pre-index incomplete sealing.
  The V1/V2/V3 source ranges were re-extracted and match their exact accepted
  identities after restoration. Controller independently accepted the
  corrected V4 source/schema design after static review against pre-
  reconciliation ExecPlan 769,971 bytes /
  `dc4f0747d1d432f44492565f60ca96efab1099555508c732bbe5ad0a826bd14c`
  and STATUS 36,510 bytes /
  `d6c0bb8e88a964d16481c8d34837ac266ba11e3ba58199624246484c015be411`.
  The accepted corrections cover stale V3 phases, total doctor capture,
  poll-failure TERM→KILL, unproven-child sealing, the pre-doctor safe schema,
  and command/capture/validation correlation. This is static design acceptance,
  not runtime PASS.
  The later literal V4 root-only authority passed preflight and created the
  fixed root, but exact `M2B_V4_SOURCE_WRITE` returned rc 1 because the
  frozen writer asserted stale `M2B_V3_SOURCE_WRITE`. Retained
  `source-receipt.json` is 11,856 bytes / SHA-256
  `c620f8b38f5c50261364041392bcc613e46d8a0789e6a0b63d9c99d19635ac5a`.
  No driver, self-check, final index, execution result, or candidate exists.
  The V4 root budget is consumed and its root must remain unchanged.
- The M2B-v5 root-only prerequisite is complete and independently controller-
  accepted under the fixed no-replace `m2-candidate-bootstrap-v5` namespace.
  V5 writer identity is 9,519 bytes /
  `64d942ba1e58d2ba656b0b866261ecb9fa5f6dd5d986d00538a8a9b8eb1bd457`;
  driver identity is 131,688 bytes /
  `94b2389bcf4a32975e75417ff96bf5095fc840bd8f8823b9eee24bc9a584de1a`.
  The uid-`501`, mode-`0700` root and its `home`, `tmp`, and `receipts`
  directories are immutable; `home` and `tmp` are empty. Its four regular
  mode-`0600` receipts are source 12,666 bytes /
  `dc205075bd8d2390d5f31ad2ae036031843968bca416d958720b1c657c0b6ae9`,
  writer self-test 19,244 bytes /
  `c9ff289716121d30fdd6f0e47b9a4a471d43fecb84096615fded7bd219f46f4e`,
  self-check 2,066 bytes /
  `3fd414adb993e06b3f9ef5beb2415af688852eff45a72f690e16044f56bf713a`,
  and final index 8,137 bytes /
  `98d083d144bb13aa86e9be0b041f8bc70b53d04d692d1b8482c1227ed5b99043`.
  Transport/self-check/finalize argv hashes are
  `23fb4830637cc750abd09ac98241ecf0d69176d000372b60cbd617126783db8c`,
  `f449f626f67c44405e87885382ae6fd117a4f563eed7c74cf378b0b2b8a9d95d`,
  and `2b518599ba626aa73b6c8ee66a785db5a5b2825f1b3012bca710f09a4a35805d`.
  Both wrapper phases were clean, writer self-test had no error, stderr
  selected exact `EMPTY`, and final verdict is
  `M2B_V5_READY_FOR_CONTROLLER_REVIEW`. The root budget is consumed. At that
  prerequisite checkpoint the reserved result was absent, 13 candidates
  remained, and no candidate phase had run.
- The separately authorized V5 recovery is consumed and retained as
  `candidate.bSEqMEit`, the fourteenth immutable candidate. Outer result
  `candidate12-recovery-v5-execution-result.json` is 18,957 bytes / SHA-256
  `eaf2b63ba9e627a44e4edb378ad980842f513a8f3d4cbfbcbc1ea8c2bdb9c487`,
  rc1 in 209.426602 seconds with no timeout, truncation, session, credential
  variable, or wrapper error. Materialization, candidate dry run, setup,
  readiness, profile staging, doctor capture/validation, and doctor
  termination passed. Post-doctor preservation stopped on exact error
  `RuntimeError: conflicting process detected`; fallback preservation is
  `FROZEN_PREALLOCATION_EVIDENCE`, which does not identify a process. Stop
  receipt is 189 bytes /
  `bc3304c40fdc1735792c9b04c0c5a0c0487262603d728032ffb54b9327d87bba`;
  final index is 13,196 bytes /
  `e7823e20c56b02ab6e6ab3de5389f120a5c8bbf41aad1f299e6ba9e260019090`,
  verdict `M2_STOPPED`, with complete sealing and no errors. The complete
  27,445-path / 587,827,527-byte attempt tree is
  `7582014c32feac65f543d2d1f6fe0aca612ff04f51bdcb7a1acff45740becbc5`.
  A controller-observed overlapping monitoring shell is correlation only, not
  receipt proof; future active monitoring is restricted to tmux capture and
  file existence/stat checks without protected-pattern command lines.
- The V6 root-only prerequisite is a consumed immutable stop. Its 144,299-byte
  driver is SHA-256
  `ba3f3ad7f7adfed16d174703a2224258436c022b4b39029c503ec2b7537080c2`;
  source receipt is 12,667 bytes /
  `046407f317ad6f6cf8daabd9c4d472768cee8361a5a2a7fbee1d392871b25f`,
  phase `M2B_V6_SOURCE_WRITE`, rc0 in 0.072293 seconds; self-check receipt is
  3,184 bytes /
  `943dcd325e1fa854b30a684e1e2a42732b8ff31335270ff1eee5a2533a5c058c`,
  phase `M2B_V6_SELF_CHECK`, rc1 in 0.291967 seconds. Both wrapper boundaries
  were clean. Exact failure was `KeyError: 'output_truncated'` while reading
  immutable V5 `setup-result.json`, which instead has false
  `stdout_truncated`, `stderr_truncated`, and `aggregate_truncated`. No writer
  self-test, V6 final index/result, or candidate exists. Candidate count is 14.
- The sole ExecPlan preserves the accepted V7 source at writer 9,519 bytes /
  `72c42e753aca1375648133796617daf7bf3de47a76544a33bba08f77e49a0317`
  and driver 153,991 bytes /
  `0d9406899c636ea3115d412165727d5b856de308278f63ded143bb9a1323116b`.
  V7 exact-key validation matches every immutable V5 receipt object and nested
  field it reads, uses the real split-channel setup schema, validates the V6
  stop, and versions all active phases/namespaces. Its fixed root
  `/Users/junhuaxu/Library/Application Support/LiveClip/engineering-candidates/agent-runtime-v2/a822890ace12/trusted-tools/m2-candidate-bootstrap-v7`
  is uid `501`, mode `0700`, complete, immutable, and independently
  controller-accepted with verdict
  `M2B_V7_READY_FOR_CONTROLLER_REVIEW`; private `home`/`tmp` are empty.
  The four regular mode-`0600` receipts are source 12,667 bytes /
  `be8674ec41b84f9a7d18cb8a18115c5f4f40e64dd65fc9605a15294d9982bd37`,
  writer self-test 28,190 bytes /
  `99b0357243a437aa14b194e5b4f04f106b26b43d8ddb34e721d1c2cb9cebceda`,
  self-check 2,066 bytes /
  `cbdb06880e0f4eff63970dff1cb5aed954cb5fc5d88f47066ab5dec6f9276333`,
  and final index 8,138 bytes /
  `e30176450d644b273d873bbe1ba94cce37b6d80bab02947dc3c705e31a2beaa4`.
  Transport/self-check/finalize argv hashes are
  `20552e8eb815e96b9b0a141a85657fbbf39f2db91f57b01ba8d7577c120ea684`,
  `89e0ff6df941552f78eb79697c115c15d327891727f732ce8d08aa976efab792`,
  and `f261c58e5fc2b9c0f03dfecb6882c0bafad4e396b83112fb7e14541e909493ce`;
  wrapper outcomes were clean and stderr selected exact `EMPTY`. The root-only
  budget is consumed. The later separately authorized V7 recovery consumed
  `candidate12-recovery-v7-execution-result.json` and the sole suffix
  `candidate.z6EbTJew`; both are immutable, and candidate count at that V7
  checkpoint was 15. The later accepted V8 suffix raises the current count to
  16.
- Historical preimage command identities are transport 26 items / 10,943 bytes
  / `3a67c5421f73073a8f7f1d5c9bfda07d9c8f909ed5c7bbe17b9530f66dbf186a`,
  self-check 25 items / 1,305 bytes /
  `b34aad4c579e838a8043c8828ceaf464e3b7034d958b49599aaabadaa10d336e`,
  and finalize 23 items / 1,428 bytes /
  `f3136f0e93ef53ee858f18d1d85c69f5ad3cd30d071fc3a2eb023c4d47b131a8`.
  They do not authorize the changed postimage.
- Pinned M2 `uv` supply: `VERIFIED`; bounded setup execution:
  `PASS_IN_ACCEPTED_CANDIDATE`; `uvx`: not run.
- Pinned outer Python 3.12 wrapper bootstrap: `PASS_USED_FOR_BOUNDED_WRAPPER`.
- M2 dependency setup/link safety/readiness/toolchain fingerprint:
  `PASS_IN_ACCEPTED_CANDIDATE`.
- M2P retained execution: `STOPPED_FINAL_PRESERVATION`; M2P-R:
  `STOPPED_NAME_SET_DRIFT`; controller prerequisite verdict:
  `M2P_PASS_RECONCILED_STATIC_TARGETS_DOCTOR_READY`.
- M2 overall: `PASS` at immutable `candidate.dygENR4n`; attempt-ten,
  candidate-eleven, V1 M2B, candidate-twelve, M2B-v2, V3, V4, V5 recovery,
  V6 root-only, and V7
  root/result/suffix budgets described above are exhausted. `candidate.bSEqMEit`
  and `candidate.z6EbTJew` are respectively the fourteenth and fifteenth
  immutable stopped suffixes. No V7 retry or replacement authority exists.
  The V8 root, consumed result, and accepted suffix are immutable; no V8 retry
  exists. Candidate count is 17 after the successful immutable V12 successor
  `candidate.mRMO7MQ6`. M3 retains one blocked predecessor and the consumed
  V11 preallocation stop. V12 root/result/suffix/init are consumed, sealed,
  and immutable. Its sole formal run was dispatched once and is now consumed
  terminal `blocked` at Planner cycle 1/code cycle 0. Candidate and run are
  retained and non-reusable.
- Formal engineering validation did not proceed beyond the failed Planner
  authentication attempt. M2
  and V12 candidate-preparation setup, link/root safety, readiness, reviewed-
  profile staging, doctor, preservation, source compile/AST/Ruff/static, and
  document/inventory checks passed; none is a formal deterministic Runner
  `lint`/`e2e`/`test` PASS. There is no Reviewer, Tester, Runner, Gateway, or
  formal product-code acceptance evidence for the consumed run.
- Technical/provisional benchmark: not yet performed.
- All-30 real-media render/package: not yet performed.
- Independent technical/visual evidence review: not yet performed.
- Human editorial listening/audio quality: `PENDING_HUMAN`.
- Audio-grounded subtitle calibration: `PENDING_HUMAN`.
- Default promotion, v1 parity, editorial/audio PASS, and full benchmark PASS:
  not claimed.

## Next action

Stop at the closed M3S-v37 documentation boundary. Controller may independently
reconstruct the final documents, sealed V37 root/driver/index/controller
receipt, immutable wrapper/seed, 21 predecessors, three reserved absences, and
the exact frozen verifier and prepare constructions. Only a later exact
accepted-hash instruction may dispatch the allocation-free verifier once.
Verifier PASS is not prepare authority. A later separate instruction may
dispatch the already frozen prepare bytes only if both documents remain
byte-for-byte unchanged after accepted verifier PASS.

Candidate `.5nZWpynN`, its blocked run, every predecessor, the V31/V32 roots,
the consumed V32 result,
and M3A-v1 authentication are retained and non-reusable. This documentation
cycle does not authorize another root execution, verifier, prepare, candidate
allocation, final-acceptance
transport, authentication, formal roles, tests, rendering, evaluation,
inference, publication, cleanup, commit, push, source-media mutation,
`--last`, or `resume_liveclip.sh`.

### Superseded M3S-v5 next action

Controller performs one bounded read-only review of the closed M3S-v5
postimage. It must preserve and correlate the three consumed receipt-bearing
stops, the consumed V4 empty-root stop, and the interrupted zero-write V5
construction proof and direct-argv stop; extract all thirteen V1–V5
writer/driver/orchestration/envelope ranges without normalization; verify source identities plus
compile/AST/security/schema/Ruff evidence; prove v2 rejection, the v3
full-source zero-violation policy result, all direct-builtin/unsafe-command
negative fixtures, and the 32-string literal
`-c` outer boundary, prohibited-mechanism fixtures, pre-`mkdir`
construction/retention of all 26/25/23 arrays, 28/37 receipt separation and
26-call traversal; and confirm 0/15/156, Appendices 15/153, sixteen
candidates, protected/M2/blocked evidence, schema-seed non-authority, and V5
root absence.

It must also derive and parse the exact 42-token UTF-8 execution envelope,
prove that all 1,077 LFs occur only inside the exact source token, reproduce
all 30 source quotes, and reject the 24 malicious grammar fixtures.

Only after accepting that postimage may the controller derive the canonical
32-element orchestration-v3, nested 26/25/23 root-phase argv hashes, and exact
envelope bytes/size/hash in memory against the closed documents. A later
literal accepted-hash instruction may submit only that exact command string
through `/bin/zsh` non-login at the immutable seed workdir; its frozen source performs
the zero-write proof, then may create only the fixed no-replace
`m3-successor-preparation-v5` root and run transport, self-check, and
finalize. V1/V2/V3/V4 are immutable and cannot be reused. Candidate
allocation and successor preparation require a separate sealed-index/document/
execute-argv authority and must stop at
`M3_SUCCESSOR_PREPARATION_V5_READY_FOR_CONTROLLER_REVIEW` without a role or
`loop-run`.
Never reuse the blocked run or Coder session, infer latest, or use `--last`.

Resume instruction:

```sh
cd /Users/junhuaxu/autoclip && \
/opt/homebrew/bin/codex \
'Read AGENTS.md, .agent/PLANS.md, docs/exec-plans/liveclip-agent-runtime-v2.md, and STATUS.md. M2 is complete; V29 root-only is sealed accepted immutable evidence and V29 candidate recovery is the sole current boundary. Preserve every predecessor and the absent V29 successor/auth results. Independently reconstruct and accept the final post-root documents, sealed root/final-index/controller/root-argv, immutable wrapper/seed, exact 20 predecessors, 27-string execute argv, 17-string direct-wrapper vector, and literal envelope before any dispatch. Do not execute recovery without separate exact authority. Never access auth, mutate or reuse a predecessor/root/candidate/run, allocate more than one suffix/run, infer/resume a session, use --last, run a formal role or product inference/render/evaluation, publish, clean, commit, push, mutate source media, or run resume_liveclip.sh.'
```
