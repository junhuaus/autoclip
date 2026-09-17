# SD-6: Real model, content and performance acceptance

Prepared 2026-09-13 during SD-3 formal `09cfe619`; updated 2026-09-17.
SD-3, SD-4 and all bounded SD-5 A/B1/B2 engineering slices are accepted
and published. [SD-5 B2 evidence](../verification/stable-delivery-sd5b2-accepted-2026-09-14.md)
includes local synthetic CLI/Web/Worker/ZIP and current artifact checks;
it is not real model/content/audio or long-input acceptance. One bounded
five-minute real short-profile batch has now passed; the broader acceptance
matrix in this plan remains open.

## Existing reference verified without processing

Read-only QA20260913122428Z-e03f PASS2.195s verified the three complete file hashes recorded
by the historical mini-lesson experiment. Evidence is retained at
`.loop/development/sd6-acceptance-preparation/existing-reference-inventory.json`.

- Source: `input/8-30.ts`, 3,143,702,536 bytes, 6,634,001 ms (about110min34s),
  SHA256 `818b669972b4e3f75f5358685ec231cd7daaaaa250c6525188291151c1109943`.
- Historical run: `30eba26459e34b8187fa15900670c78a`, project
  `e725b1a24c2d4975b1399674517219f1`, generation1. Its contract remains historical.
- Transcript:835segments; JSON SHA256
  `0bf44cf62d59ee90721d9365c55d4aa78573831f5f70fe72fba35520013e1a39`, SRT SHA256
  `d9af85b05e0a23d0e2d1b81e1000bb61d0ccaee75662ed626f70b0d94b384ea1`.

No credentials were read, no model was called, and no user database or source file changed.
This input is shorter than two hours and cannot establish either the2h or4h performance case.
An additional read-only `ffprobe` inventory on 2026-09-13 checked all eight `input/*.ts`
files. Their durations range from about 1.295 to 1.953 hours; the longest is
`input/8.25.ts` at about 1 hour 57 minutes. No currently inventoried input
reaches the distinct 2-hour or 4-hour acceptance case. Source files were not modified.
The old experiment's six fixture anchors are useful references, not approved independent human
ground truth. Its78ASR calls and failed28local Discovery starts cannot establish current
V12/V13 semantic quality, current provider capability, current price or measured improvement.

## Preparation and bounded execution

After SD-5 engineering acceptance, bind the exact accepted source, both proposed release
profiles, model/settings, host, source and transcript identities in an immutable batch plan.
Provide a concrete first batch with estimated initial/repair/transient-call bounds, token/cost
and wall-time limits before requesting any missing real-execution authorization. Stop at the
recorded limits; do not enlarge them automatically or use the previously exposed key.

Use a supported product execution environment separate from the developer Runner. Do not
change Runner network restrictions or launch business inference through a development role.
Authenticate provider capability with actual bounded evidence; a version/login probe alone
is insufficient. Create new current-contract runs without migrating or overwriting the
historical project. Reuse ASR only when its immutable source/config identity permits it.

Freeze human reference labels before looking at new outputs. For each proposed release
profile, run at least three independent semantic evaluations over the same frozen transcript,
with semantic caches disabled for stability measurement. Keep recovery/cache tests separate.
Report every failure/timeout, exact invalid-response numerator/denominator, actual calls,
repairs, tokens/cost and latency. A local launch failure is not a model response.

Exercise one real source-to-ASR-to-semantics-to-MP4/SRT/Delivery flow and one injected-failure
recovery per profile, plus another source for generalization. Confirm stable project/run/
generation/delivery identity, preserved manual exclusions and authenticated cache reuse.
Inspect and listen to every automatically delivered clip; verify source boundaries, central
objective, stitching, meaning, risks and subtitles. Full media decode, manifests/checksums and
ZIP validation supplement human content/audio assessment, not replace it.

For2h/4h representative inputs, measure cold and recovery cases on the same host and fixed
model/ASR/settings as the frozen baseline. Record stages, queue/model/repair/cache time,
peak memory, disk and packaging cost. Preserve the roadmap's quality/performance thresholds
and denominators; if the baseline cannot finish, report no comparable relative speedup.

## Status and independent work

- [x] Verify the existing historical reference bytes without model calls or mutation.
- [x] Complete SD-4/5 bounded engineering with formal gates and original publication (2026-09-14).
- [x] Run bounded local model-channel smokes on 2026-09-14: 30-second MLX ASR on the read-only source and one tool-disabled Codex editorial call on synthetic Chinese text.
- [x] Freeze the first five-minute probe configuration and source/excerpt/model identities (2026-09-15).
- [x] Prepare and execute the first explicitly bounded short-profile probe under the recorded continuous authorization; it failed closed before inference on exact Codex CLI version drift.
- [x] Formally accept and publish the Codex CLI 0.154 `tool-free-v3` profile with byte-exact version validation (2026-09-15).
- [x] Complete one bounded second-excerpt short-profile source-to-MLX-to-Codex-to-MP4/SRT/ZIP flow and independent package/media inspection (2026-09-15).
- [x] Execute the separately guarded mini attempt and preserve its eight-launch deterministic exhaustion without retry or false success (2026-09-15).
- [x] Formally accept and publish the SD-6B Link Review truth-table Prompt correction with fixed Runner and Gateway evidence (2026-09-15).
- [x] Preserve bounded mini attempts 3--6, including the managed-sandbox Metal failure and three real content-negative outcomes, without claiming Delivery (2026-09-15).
- [x] Formally accept, publish and regression-test the Global Review final-Boundary decision clarification identified by mini attempt 5 (successor 5, 2026-09-16).
- [ ] Freeze human labels and collect real per-profile semantics, media and recovery evidence.
- [ ] Collect distinct2h/4h and generalization evidence; report measured quality/performance.
- [x] Finish SD-7 reproducibility and recovery engineering.
- [x] Publish current bounded evidence and limitations.

Missing bounded authorization, supported inference environment, human labels/audio review or
long inputs leaves `BLOCKED_REAL_MODEL_ACCEPTANCE` for those cases. Continue independent
engineering and documentation, and keep unaccepted profiles explicitly experimental.

2026-09-14 current readiness: original `make doctor` was READY on Apple
Silicon, with only the documented FFmpeg text-filter fallback. Local MLX
smoke QA `20260914234828Z-5d3d` transcribed the 330–360-second read-only
source slice in 13.369 seconds of model inference (nine segments; no word
timing). Codex CLI smoke QA `20260914234954Z-ee7d` completed one tool-disabled
editorial call using saved login on synthetic Chinese text. These establish
bounded local model-channel operation only; neither is a real source-to-package
batch, an accuracy score or human listening. Doctor reported an OpenRouter
configuration but did not validate that its Key was regenerated. The
previously exposed Key is never eligible for a real smoke or batch. Next:
freeze a bounded real batch plan with explicit limits and obtain distinct
2h/4h inputs and independent human labels for their acceptance cases.

## Bounded real-source probes

All probes use read-only `input/8-30.ts`, source SHA-256
`818b669972b4e3f75f5358685ec231cd7daaaaa250c6525188291151c1109943`.
Each derived excerpt, database and generated-media tree is isolated below
ignored local evidence. The source hash is rechecked after extraction. The
provider is `mlx-codex`: locally pinned full-precision MLX ASR, saved Codex
login, no injected OpenRouter/OpenAI ASR key and explicit `gpt-5.6-sol`
editorial model.

The exploratory policy fixed short-profile launches at six, mini-profile
launches at eight and each wall clock at 25 minutes. A wrapper pins the Codex
entrypoint bytes and atomically consumes its owned counter before every
`exec`. Version/login probes do not consume the cap. A cap, timeout,
deterministic failure or missing Delivery ends the attempt with its true
status; counters are never reset and limits are not silently extended.

### Historical version-drift failure

The first no-clobber excerpt covers seconds 330--630. It is 300.0 seconds,
H.264/AAC, 319,545,707 bytes, fully decodes and has SHA-256
`53e93648a33b20b87ca52652cd7d4b5e4c0f3d948890f2cf70c558e098a184eb`.
QA `20260915T030822Z-f274` ended after 6.766 seconds with
`CODEX_CLI_NOT_READY`, zero guarded launches, no Delivery and no cloud key.
Installed, authenticated CLI 0.154.0 did not match the then-current reviewed
0.147.0 pin. That immutable FAIL led to SD-6A; it was not a model response.

ADR049 and formal successor `20260915T033147Z-feb147f9` subsequently accepted
and published exact 0.154.0 profile `tool-free-v3`. Only local
`code_mode_host` is enabled, 88 authority-bearing features are explicitly
disabled, all 140 installed features are classified, and version output is
captured and validated as exact bytes. The earlier failed guard and receipt
remain unchanged.

### First post-publication content result

QA `20260915T041716Z-6a01` repeated the short profile on seconds 330--630 with
a fresh six-launch guard. Four MLX calls produced 94 transcript segments and
four Codex semantic calls succeeded without repair. The only candidate scored
52 and was correctly rejected for irrelevant internal content and equipment
interruption under the strict score-above-75 gate. The run is an immutable
FAIL with no Delivery. It demonstrates provider operation, not acceptable
content.

A second excerpt was selected only from preserved historical timing evidence,
before inspecting new output. It covers seconds 2050--2350, is 300.0 seconds,
H.264/AAC, 327,895,093 bytes, fully decodes and has SHA-256
`c489e92823081f085c40c066ff09211c23d4f02bfbdc52b7ab9ac9243c085162`.
QA `20260915T042327Z-2050` records extraction and unchanged source identity.

Short-profile QA `20260915T042454Z-6a02` passed in 271.187 seconds. Four MLX
calls produced 129 transcript segments; all four Codex calls succeeded with no
repair, using 58,523 input, 7,331 output and 3,747 reasoning-output tokens. Two
clips scored 93 and 91, with planned durations about 50.98 and 45.46 seconds.
Delivery `ba63e3ad83c34b9e902c090ad5e3d5c2` version 1 succeeded. Manifest
SHA-256 is
`f37fa7d80187f131610c6318b3e90a308e4a148ff6bbc50f00fb3e68c24c9ceb`;
ZIP SHA-256 is
`86e4eaba6dcac17c57546d5d12621148c4aebb15208d49faf12919de05179609`.

Independent QA `20260915T043145Z-d602` passed SQLite quick/foreign-key checks,
seven deterministic safe ZIP members, CRC and local-byte equality, full decode
of both H.264 1080x1920/AAC clips and all SRT bounds. Two contact sheets were
visually inspected: portrait orientation is correct and no black, frozen or
corrupt frames were observed. The second clip includes source-camera movement
that partly moves the presenter out of frame. Subtitles are validated sidecars,
not burned in. No human audio listening or editorial acceptance was performed.

### Mini attempt and remaining work

Mini-profile QA `20260915T043321Z-b801` used the same second excerpt and its
separate immutable eight-launch guard. In 452.797 seconds, four MLX calls and
all eight permitted Codex launches completed: two discovery initial calls,
one successful discovery repair and five link-review initial calls. Both
discovery units ultimately succeeded. Of 22 link-review units, two succeeded,
three exhausted after a repair was needed and 17 exhausted without a permitted
call after the cap. The candidates stage failed deterministically with
`CANDIDATES_PROVIDER_INVALID` and safe message `Semantic unit exhausted;
unchanged recovery cannot repeat its calls`. No render or Delivery was
created. The probe used 123,239 input, 21,505 output and 8,855
reasoning-output tokens. Its consumed guard and FAIL remain unchanged.

Read-only QA `20260915T045601Z-bgt2` then derived the actual and schema-level
fan-out without model calls or mutation: five logical windows held 16
fragments, initial routing produced 22 links, all adjacent fragment pairs cap
at 45, and downstream schemas make the theoretical one-repair ceiling 1,408
calls. A new written attempt-2 plan therefore fixed 64 launches and the same
25-minute wall clock as a finite stop budget, not a completion guarantee.

Mini attempt-2 QA `20260915T045700Z-mn02` stopped after 426.218 seconds and
only 9/64 launches. Both Discovery units succeeded after one repair each and
three Link Reviews succeeded. A fourth Link Review used linking relationship
`next_step_same_lesson` while its boolean judgments were not both true; its
only repair changed a boolean but kept the linking enum. The strict validator
rejected both outputs and candidates failed with
`CANDIDATES_PROVIDER_OUTPUT_INVALID`. No render or Delivery exists. This is a
Prompt clarity gap rather than budget exhaustion; ADR050 and the SD-6B plan
require a formal Prompt-only truth-table correction before another real run.

Formal SD-6B run `20260915T050655Z-621eb79d` reached DONE after the exact
recorded Coder repaired its initial fixed-Runner failures. Fresh Reviewer and
Gateway decisions passed, and the final sealed source passed lint, E2E and the
full test suite. Trusted Main published only the Link Review Prompt, shared
repair Prompt and direct regression test. The earlier attempt-2 failure and
all superseded Runner failures remain immutable. Focused postpublication QA
passed 45 tests.

Mini attempt 3 used a fresh 64-launch guard but the managed execution sandbox
exposed no Metal device to MLX. It stopped in 2.403 seconds with zero model
calls, no counter consumption and no Delivery. The failure is preserved in
`docs/verification/sd6-mini-attempt3-sandbox-failure.json`; it is environment
evidence rather than an ASR or semantic result.

Attempt 4 reran the same 2050--2350 excerpt in the supported host environment.
All six product stages completed, local MLX succeeded four times and Codex used
27/64 launches. Discovery, 13 Link Reviews and nine Topic Chains succeeded,
and the corrected relationship contradiction did not recur. The model proposed
no complete mini candidate above the deterministic editorial threshold, so no
render or Delivery was created. The true negative outcome is preserved in
`docs/verification/sd6-mini-attempt4-content-rejection.json`.

Attempt 5 used the independently frozen 1870--2170 learning-step anchor. It
completed all six stages with four successful MLX calls and 31/64 Codex
launches, producing two approximately 90-second candidates. The score-88
candidate was correctly blocked for `asr_meaning_reversal` and manual risk.
The score-86 candidate retained Boundary Review's repaired cues 88--126 but
Global Review copied the upstream `repair_boundary` value, causing the exact
`content_keep_gate` rejection. No Delivery exists. ADR051 and the separate
Global final-decision plan freeze a Prompt-only correction; validators, risks,
scores, retries and selection remain unchanged. Evidence is
`docs/verification/sd6-mini-attempt5-content-rejection.json`.

Attempt 6 used the frozen 1550--1850 air-mix anchor selected before inference.
The derived H.264/AAC excerpt fully decoded and the source hash stayed exact.
Four MLX calls succeeded; 16 Codex calls succeeded and two initial Discovery
outputs were structurally invalid before their permitted repairs. Ten Topic
Chains were all rejected as either `no_complete_profile_candidate` (six) or
`topic_not_closed` (four). All product stages completed with zero candidates
and no Delivery after 18/64 launches. This is a preserved content-negative
result, not a reason to select another window after inspecting output. Evidence
is `docs/verification/sd6-mini-attempt6-content-rejection.json`.

Global final-decision successor 5 `20260916T223427Z-6f412cde` is formally
DONE and published after five preserved BLOCKED predecessors. Its fixed Runner
lint, E2E and full-test gates passed on source fingerprint
`1752f61cb22243f7e96598b1950663160c1aecb27ab94f9d041c2fee278ebc21`;
fresh Reviewer and Gateway passed. Main's independent audit, compare-and-swap
publication and postpublication 18/18 Prompt plus 48/48 affected-Web
regressions passed. The accepted correction supplies no real mini result.

Attempt 7 was then frozen against that accepted source with a fresh 64-launch
guard and 25-minute cap. QA `20260916T232333Z-ma7f` proved the counter absent
and recorded zero model calls. Hardware preflight QA
`20260916T232354Z-mp07` was interrupted before it completed; no process or
counter remained afterward. Attempt 7 is unconsumed. A different Mac must
restore the exact ignored source and model, reconstruct the frozen run from
committed evidence, and pass a fresh host hardware preflight before inference.
See `liveclip-sd6-resume-another-mac.md`.

This evidence proves one bounded real five-minute short flow through local ASR,
Codex semantics, rendering and packaging, plus bounded negative mini evidence.
It does not prove mini-lesson real acceptance, the full 110-minute source,
independent 2h/4h cases, repeated semantic stability, another-source
generalization, frozen human-label quality, human listening or Apple M3
long-run performance. The call-bound rationale is frozen. Changing a consumed
guard, rerunning an unchanged failure, or selecting another window after seeing
prior output is prohibited.

## Cross-Mac resume check, 2026-09-17 03:32 UTC

QA `20260917T033200Z-a7ready` reconciled all 1,107 inherited request/report
pairs and recorded the current prerequisite block. This clean `main` checkout
at `6a3b949b2dd852fc6cf11ec648620bd569ddb8de` has no `input/8-30.ts`, no
`data/models/whisper-large-v3-mlx`, no `.venv/bin/python` and no `.loop`.
Neither FFmpeg nor ffprobe is on PATH. The process reports Darwin/x86_64;
`hw.optional.arm64` and `sysctl.proc_translated` queries were denied, so this
check does not establish physical host architecture or Metal availability.
See [the prerequisite receipt](../verification/sd6-mini-attempt7-resume-blocked.json).

Attempt 7 remains unconsumed. No guard, run database or Delivery was created,
and no model or credential was accessed. Setup, doctor and full hardware
preflight were not run: installation cannot restore the missing user media,
and supported hardware is unverified. Product code and control-plane policy
remain unchanged; this documentation check is not deterministic Runner acceptance.

Next task: restore the exact source and pinned model on a supported Apple
Silicon host, install the documented local toolchain, then reconstruct and
freeze attempt-7 controls and register/pass its complete hardware preflight
before the single 64-launch/25-minute attempt. Preserve the prior freeze and
interrupted preflight as historical evidence. Do not mark SD-6 complete.

## Attempt-7 prerequisite recheck, 2026-09-17 04:01 UTC

QA `sd6-attempt7-prerequisite-recheck-20260917` reconciled 1,109 inherited
request/report pairs at main `f27a03df7d95e14a6cfc395980a9184a9052d2f7`.
Read-only hardware queries outside the sandbox returned
`hw.optional.arm64=1` and `sysctl.proc_translated=1`: Apple Silicon is
confirmed, with this process running under Rosetta. Codex is exactly 0.154.0.
This resolves the earlier architecture uncertainty, but does not prove Metal.

The exact source, documented pinned model, project virtual environment, uv,
FFmpeg and ffprobe remain unavailable. A recursive filename-only search of
common local source locations was interrupted without a completed inventory;
absence elsewhere is not established. Setup and full hardware preflight were
not run. Source restoration remains an external prerequisite. No model or
credential was accessed, no guard was created or consumed, and no Delivery
exists for this attempt. SD-6 remains incomplete.

Restore the exact source and pinned model, prepare a native arm64 toolchain,
then reconstruct/freeze attempt 7 and register/pass its full hardware preflight
before the single 64-launch/25-minute run. Preserve all historical evidence.
Receipt: [prerequisite recheck](../verification/sd6-mini-attempt7-prerequisite-recheck.json).
