# SD-6A Codex CLI 0.154 accepted evidence

Date: 2026-09-15

## Accepted product change

Formal successor `20260915T033147Z-feb147f9` is DONE and published. Its sole
isolated Coder was `01a0a322-3b79-7b32-8cc4-f08c5361d246`. It changed exactly:

- `src/liveclip/providers/llm/codex.py`
- `tests/unit/test_codex_llm.py`

The product accepts exact Codex CLI 0.154.0 as profile `tool-free-v3`.
`code_mode_host` is the only enabled installed feature; 88 known
authority-bearing features are explicitly disabled. The checked inventory and
classification partition all 140 installed feature names without overlap or
omission. Version output is captured as bytes and accepts only exact ASCII
`codex-cli 0.154.0` with no terminator, LF or CRLF. Bare CR, non-ASCII,
additional bytes and all other versions fail before inference. An actual child
process regression covers the bare-CR case.

All previous safeguards remain: ignored user config/rules, private ephemeral
working directory, read-only sandbox, approval `never`, transcript only on
bounded stdin, strict schema and EditPlan validation, one repair, bounded JSONL
capture, hard rejection of tool events, credential/proxy removal and per-call
executable identity recheck.

## Formal assurance and publication

The first formal attempt `20260915T031428Z-183c2855` remains terminal BLOCKED
and unpublished because its Reviewer found text-mode bare-CR normalization.
Tester returned BLOCKED; no Runner or Gateway ran. Its lineage is preserved in
`docs/verification/sd6a-first-blocked-lineage.json`.

The accepted successor used source fingerprint
`a888cc7ba87435a6c9ade20a76374cf6704110b035c4d4738edc90b83c604b06`
and toolchain fingerprint
`539a2d0227084d6f129cdef225671a2540ae4944cf9e3575352031da90426449`.
Fresh Planner, sole Coder, Reviewer, Tester and Gateway artifacts are below
`.loop/development/sd6-codex-0154/successor/.loop/runs/20260915T033147Z-feb147f9/`.
Reviewer returned PASS with no findings, Tester returned READY and Gateway
returned PASS.

Deterministic Runner evidence from the same identities:

- `20260915T034130Z-a9f8`: `make lint`, PASS;
- `20260915T034211Z-5a6c`: `make e2e`, PASS;
- `20260915T034623Z-5636`: `make test`, PASS in 1,640.889 seconds.

The full test passed 2,467 Python and 80 Web tests, three required browser
scenarios, Completion and B2 retained-artifact checks, unique manifests, ZIP
verification, full MP4 decode, cleanup and wrong-producer rejection.

Independent Main audit receipt
`.loop/development/sd6-codex-0154/successor-done-source-receipt.json` has
SHA-256
`0a51b38a16854687b888f3d0aa6602e481644880c493853b3d909770746f4f62`.
It verifies the exact session, roles, source/toolchain identities, two-path
delta, 140-feature partition, 88 disables, byte capture, actual-child test and
preserved historical failures.

Trusted compare-and-swap publication receipt
`.loop/development/sd6-codex-0154/original-successor-publication-20260915T041638Z/receipt.json`
has SHA-256
`a6dc8b99e0f81feb479ece2138e7c59dab125dc29f2b526731ff55a005eb1b67`
and records successful atomic publication of only the two authorized paths.
Post-publication QA `20260915T041645Z-c154` passed 71 Codex/readiness tests.

Published file hashes at that check:

- `src/liveclip/providers/llm/codex.py`:
  `ee6f49a6a4085e0cff9252499e97491d92c300e059694e0de0bf216568d54446`
- `tests/unit/test_codex_llm.py`:
  `1f480272bbb95ae5bb6d024c24291e774f4b09d9a98f4618fa756a8c8d639236`

## Bounded real-source evidence

The read-only source `input/8-30.ts` has SHA-256
`818b669972b4e3f75f5358685ec231cd7daaaaa250c6525188291151c1109943`.
No probe injected a cloud ASR key.

The initial 330--630 second probe `20260915T030822Z-f274` remains FAIL: exact
version drift stopped it with zero Codex launches. After publication, retry QA
`20260915T041716Z-6a01` made four successful MLX and four successful Codex
calls, but its only candidate scored 52 and correctly failed the score gate;
there was no Delivery.

The independently extracted 2050--2350 second excerpt has SHA-256
`c489e92823081f085c40c066ff09211c23d4f02bfbdc52b7ab9ac9243c085162`
and full-decode PASS. Short-profile QA `20260915T042454Z-6a02` passed:

- 129 transcript segments; four of four MLX calls succeeded;
- four of four Codex calls succeeded with no repair;
- 58,523 input, 7,331 output and 3,747 reasoning-output tokens;
- two selected clips scored 93 and 91;
- Delivery `ba63e3ad83c34b9e902c090ad5e3d5c2` version 1 succeeded;
- manifest SHA-256
  `f37fa7d80187f131610c6318b3e90a308e4a148ff6bbc50f00fb3e68c24c9ceb`;
- ZIP SHA-256
  `86e4eaba6dcac17c57546d5d12621148c4aebb15208d49faf12919de05179609`.

Independent QA `20260915T043145Z-d602` passed database integrity, safe ZIP
members, CRC/member hashes, local-byte equality, full decode of both portrait
H.264/AAC clips, SRT cue bounds and two contact-sheet inspections. No black,
frozen, corrupt or rotated frame was observed. Source-camera motion partly
moves the presenter out of the second clip. Subtitles are sidecar SRT files.
No human audio listening or editorial acceptance was performed.

Mini QA `20260915T043321Z-b801` remains deterministic FAIL. Its eight-launch
guard was fully consumed by two discovery initial calls, one discovery repair
and five link-review initial calls. Two discovery units succeeded; only two of
22 link-review units succeeded, three exhausted after repair was needed and 17
exhausted without a permitted call. Candidates failed with
`CANDIDATES_PROVIDER_INVALID`; no render or Delivery exists. The guard is not
reset and the unchanged attempt is not retried.

After a read-only fan-out analysis and a new frozen 64-launch plan, mini QA
`20260915T045700Z-mn02` failed independently at 9/64 launches. Both Discovery
units succeeded after repair and three Link Reviews succeeded; one Link Review
remained structurally inconsistent after repair because a linking relationship
enum contradicted boolean judgments that were not both true. No Delivery was
created. This leaves the accepted 0.154 adapter intact and routes a narrow
Prompt-contract clarification through ADR050 and a new formal SD-6B slice.

## Evidence integrity and acceptance boundary

At real-probe closure, `qa/pipeline.jsonl` contained 1,055 unique request IDs
and `qa/test-report.md` contained the same 1,055 unique headings, with no
missing, extra or duplicate ID. Later documentation checks remain append-only
and paired. Version drift, first-source content rejection and mini guard
exhaustion remain FAIL, alongside the preserved SD-7 historical FAILs.

Accepted: Codex 0.154 compatibility and one bounded five-minute real
short-profile source-to-package flow.

Still open: mini-lesson real success, human content/audio quality, repeated
semantic stability, independent frozen labels, another-source generalization,
the full 110-minute source, distinct 2h/4h inputs and long-run Apple M3
performance. The supplied source is about 110 minutes 34 seconds and cannot
establish either 2h or 4h acceptance.
