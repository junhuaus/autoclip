# SD-6A Codex CLI 0.154 compatibility Living ExecPlan

Prepared and completed 2026-09-15. This plan follows `.agent/PLANS.md` and
supports the bounded real-content work in
`docs/exec-plans/liveclip-sd6-real-acceptance.md`.

## Purpose / Big Picture

A user with Codex CLI 0.154.0 and saved ChatGPT login can run LiveClip's
editorial stage through an exact-version, fail-closed, tool-free boundary.
LiveClip binds the executable and profile identity into the Pipeline contract,
accepts only structured editorial output, and grants no model-authored command,
file, network or external-tool authority.

## Context and Orientation

The adapter and argv/security contract live in
`src/liveclip/providers/llm/codex.py`; direct tests live in
`tests/unit/test_codex_llm.py`. ADR008 defines the product boundary, ADR031
records why 0.154 needs local `code_mode_host` transport even when code mode
and tools are disabled, and ADR049 records this profile's acceptance.

QA `20260915T030822Z-f274` first exercised a hash-pinned five-minute excerpt.
Readiness rejected the then-current 0.147 product pin against installed 0.154.0
in 6.766 seconds, before ASR, semantic inference or Delivery. It spent zero
Codex launches, injected no cloud key and did not fall back.

## Scope and non-goals

The implementation changed only the exact supported CLI/profile declaration,
the minimum local transport flag required by 0.154, explicit authority-feature
disables, byte-exact version capture and direct tests. It did not change
prompts, schemas, model choice, semantic algorithms, ASR, retries, credentials,
Runner policy or the developer control plane.

This slice does not prove human content/audio quality, full-input behavior,
repeated semantic stability, generalization or 2h/4h performance.

## Progress

- [x] Preserve the initial real-probe version-drift FAIL with zero inference.
- [x] Inventory all 140 installed 0.154 features and classify them completely
  and disjointly; explicitly disable 88 authority-bearing features.
- [x] Preserve first formal `20260915T031428Z-183c2855` as terminal BLOCKED
  after Reviewer found text-mode bare-CR normalization; publish nothing.
- [x] Run the byte-exact successor through fresh roles. Formal
  `20260915T033147Z-feb147f9` is DONE; its sole recorded Coder is
  `01a0a322-3b79-7b32-8cc4-f08c5361d246`.
- [x] Pass fixed Runner lint/e2e/full-test and fresh Gateway from one sealed
  source/toolchain identity.
- [x] Independently audit DONE and publish exactly two authorized paths by CAS.
- [x] Append formal QA without relabeling earlier failures and pass 71 focused
  post-publication Codex/readiness tests.
- [x] Repeat the bounded short real probe on a historically indicated excerpt;
  produce and independently inspect a succeeded immutable Delivery.
- [x] Run the mini profile only after short acceptance and preserve its fixed
  eight-launch deterministic exhaustion as FAIL without unchanged retry.

## Work breakdown and ownership

Main owned requirements, ADR, this plan, STATUS, candidate freeze, QA, audit
and publication. The isolated Coder owned only
`src/liveclip/providers/llm/codex.py` and `tests/unit/test_codex_llm.py`.
Planner, Reviewer, Tester and Gateway were fresh and read-only. The Runner used
only checked-in allowlist IDs under its deny-default macOS sandbox.

## Formal validation

Successor source fingerprint was
`a888cc7ba87435a6c9ade20a76374cf6704110b035c4d4738edc90b83c604b06`;
toolchain fingerprint was
`539a2d0227084d6f129cdef225671a2540ae4944cf9e3575352031da90426449`.
All fixed Runner results used both identities:

- lint `20260915T034130Z-a9f8`: PASS;
- e2e `20260915T034211Z-5a6c`: PASS;
- full test `20260915T034623Z-5636`: PASS, including 2,467 Python tests,
  80 Web tests, three required browser scenarios, Completion and B2 package
  verification, full MP4 decode, cleanup and wrong-producer rejection.

Reviewer returned PASS with zero findings, Tester returned READY and Gateway
returned PASS. Main's audit receipt is
`.loop/development/sd6-codex-0154/successor-done-source-receipt.json`.
It checks the exact Coder, two-path delta, formal roles/Runner/Gateway, full
feature partition, byte capture, actual-child bare-CR regression and preserved
FAIL/BLOCKED lineage.

Trusted publication receipt
`.loop/development/sd6-codex-0154/original-successor-publication-20260915T041638Z/receipt.json`
records successful no-clobber compare-and-swap publication of exactly the two
authorized paths. Post-publication QA `20260915T041645Z-c154` passed 71 tests.

## Real-probe observations

The first post-publication retry on source seconds 330--630 completed all four
MLX and four Codex calls but correctly rejected its only candidate at score 52;
QA `20260915T041716Z-6a01` remains FAIL with no Delivery.

A second no-clobber excerpt from seconds 2050--2350 has SHA-256
`c489e92823081f085c40c066ff09211c23d4f02bfbdc52b7ab9ac9243c085162`
and full-decode PASS. Short-profile QA `20260915T042454Z-6a02` passed with
129 transcript segments, four successful MLX calls, four successful Codex
calls, two selected clips scoring 93 and 91, and succeeded Delivery
`ba63e3ad83c34b9e902c090ad5e3d5c2`. The ZIP SHA-256 is
`86e4eaba6dcac17c57546d5d12621148c4aebb15208d49faf12919de05179609`.
Independent QA `20260915T043145Z-d602` passed SQLite, foreign-key, manifest,
ZIP CRC/member-hash, full MP4 decode, SRT-bound and contact-sheet checks.

Mini QA `20260915T043321Z-b801` truthfully failed after consuming its immutable
8/8 launch guard: two discovery units succeeded, while only two of 22 link
review units completed. The candidates stage ended with deterministic
`CANDIDATES_PROVIDER_INVALID`; no render or Delivery exists. The consumed
counter is preserved and an unchanged retry is prohibited.

A later independently planned 64-launch attempt also remained FAIL, but stopped
at only 9 launches on one Link Review relationship/boolean contradiction after
its single repair. ADR050 routes that narrow Prompt clarity issue through a new
formal slice; it does not reopen this accepted CLI compatibility decision.

## Idempotency, recovery and rollback

Candidate/run/session IDs and QA records are append-only. Consumed real-probe
guards are never reset or reused. Rollback restores the two published files
from the CAS receipt. Persisted Pipeline contracts distinguish the historical
0.147 profile from 0.154 `tool-free-v3`.

Every later CLI version must receive a new exact inventory, classification,
profile identity, formal acceptance and post-publication probe. Do not spoof a
version, widen a range, expose credentials or relax model authority boundaries.

## Surprises and Discoveries

- Exact-version rejection correctly isolated a compatibility gap while saved
  login remained healthy and spent no inference budget.
- A mock subprocess result could not test Python universal-newline behavior;
  byte capture and an actual child process were required.
- A five-minute mini source can fan out to 22 link reviews. The original
  eight-launch exploratory estimate was insufficient and its exhaustion is
  observable separately from model-invalid output.

## Outcomes and Retrospective

Codex CLI 0.154 compatibility is accepted, published and proven on one bounded
real short-profile source-to-package flow. The mini profile, human quality,
repeated evaluations, another source, full 110-minute input and distinct 2h/4h
performance cases remain SD-6 acceptance work rather than hidden gaps.
