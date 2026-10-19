# Agent Runtime v2 formal-loop successor requirement

This is a bounded formal-loop requirement, not an ExecPlan. The sole
authoritative Living ExecPlan is
`docs/exec-plans/liveclip-agent-runtime-v2.md`. This requirement incorporates
the complete engineering outcome, Coder allowlist, compatibility constraints,
Runner commands, acceptance distinctions, and prohibitions from
`docs/requirements/liveclip-agent-runtime-v2-acceptance.md`, exact SHA-256
`6c262edb9463583614979d9b2e24f12a94c8f1a40c43b4537f95381a9259c3f8`.
If that file or hash differs, stop. Nothing here expands its product scope or
write allowlist.

## Why this successor exists

Formal run `20261009T124056Z-37111cbc` is retained terminal `BLOCKED`. Its
fresh Planner was ready, but its isolated Coder correctly stopped without
writing because the execution snapshot exposed only toolchain fingerprints,
not a trusted correlation among the frozen B2 source, accepted M2 candidate,
formal run, and sealed toolchain. The blocked run and its sessions are
evidence, never resumable inputs.

The successor must make that correlation visible without changing the
checked-in Planner/Coder/Reviewer/Tester/Runner/Gateway workflow. It does so
with one controller-accepted, data-only record at:

`config/loop-engineering/trusted-context/liveclip-agent-runtime-v2-successor-v1.json`

The repository copy at that path is only a schema seed with authority state
`SCHEMA_ONLY_NOT_AUTHORITY`; it is not authority.
The fresh builder must not copy it. After `loop-init` creates exactly one new
run and Trusted Main reads the run ID from its exact `state.json`, Trusted Main
must exclusively create the candidate-local final record at the same relative
path. Only that run-bound record, together with later literal controller
acceptance of its exact hash and the final policy/toolchain/candidate hashes,
may satisfy the provenance prerequisite.

## Frozen predecessor evidence

The blocked predecessor is exactly:

- Run ID: `20261009T124056Z-37111cbc`.
- Final `state.json`: 17,815 bytes, SHA-256
  `cb6e8a2ff53902dc617281757a6d5a910069109b1e2637ef5929c914ca25a6e5`.
- `events.jsonl`: 2,278 bytes, eight events, SHA-256
  `c3ff12b83e7e2bd5894a06d608bd4ab78222e6842fdfeeb41457b12ef28438c4`.
- Planner session: `01a120b1-85ac-7432-be0f-1122f40e1142`; artifact SHA-256
  `c0491867e29734f68bde429514bd2187ee8dec809930c7b385c495c9d2d6a64f`.
- Coder session: `01a120b3-f587-7682-80e4-635b1fcfd823`; artifact SHA-256
  `fc57f4c96a321017e221d12ee0ed5090673c5f91047cc6cc792154a86eec3470`;
  event-log SHA-256
  `eb6789590c6c321947ab806c18f52e04927a56704d82c14ff67fd51af4cc2837`.
- Coder verdict: `BLOCKED`, with no changed files and no tests.
- Reviewer, Tester, Runner, Gateway, and publication evidence: absent.

The new run ID must differ from the blocked ID. Neither predecessor session
may be resumed or supplied to a new role. Never use `--last`.

## Frozen source and accepted candidate evidence

The successor source kind is
`FROZEN_B2_RECONSTRUCTION_NOT_DYG_COPY`: it is reconstructed from frozen
original B2 bytes, not copied from the post-M2 filesystem of
`candidate.dygENR4n`:

- Branch/HEAD: `main` at
  `2f361fcddc0e63ae62ee62826e27b54bb8204c53`.
- Immutable B2 seed repository:
  `/Users/junhuaxu/Library/Application Support/LiveClip/engineering-candidates/agent-runtime-v2/a822890ace12/candidate.OlsWg1/repo`.
- Canonical B2 manifest: 2,322 records, comprising 2,251 tracked and 71
  ordinary-untracked records, SHA-256
  `e6bc1213d482c38c78b97c3390ea35c05ca05efb2c1ff1d754e3894a04fd8044`.
- Tracked patch SHA-256:
  `472638a7f6c78634d3dbe5508716fc3a1328761dd4047eaf1b20c4d494a01254`.
- Exact 71-path overlay-list SHA-256:
  `1cbfb3a787026491c1c979ce3f263adece51af8cc1210c94094dd7bf2ee3cec7`.
- Accepted M2 candidate: `candidate.dygENR4n`; outer-result SHA-256
  `ad14c8f8b08f0c7be98d74ced9316b803348772ac6af17c78ec30362d3e1ee69`;
  final-index SHA-256
  `ee23214f812a8e946fe0025008ef57d4aa2a5e643c13e3605245f9af8a0d1a7d`;
  repository identity
  `093077b1bff4f830e01a2c7eb0b7d004ccf18f06204ef2e96cab6cdb48cc1743`;
  complete-attempt identity
  `c5d16be1ce9c79e7fc0332240f42a4785364539e83c9cf5b129a13c1a7c5aec3`.
- Protected completed result SHA-256:
  `0c226f6aa8ca52c15441fabb2a6be316f16cf09288be90c9d1d8370df3f25e6a`.
- Protected 102-record manifest SHA-256:
  `d929781748edabdd562f2f386cdfc3f92d4f8cc1339e0249fc33e92b11364a31`.

`candidate.dygENR4n` now retains 132 ignored cache paths and three changed
managed-Python bytecode files created around the blocked run. They are
historical drift, not source. They must not be cleaned, copied, normalized, or
used to construct the successor. Git source and the delivery B2 baseline
remain unchanged.

## Exact successor overlay and trust boundary

Relative to exact B2, the final successor repository may differ initially at
only these four control/document paths:

```text
docs/exec-plans/liveclip-agent-runtime-v2.md
STATUS.md
docs/requirements/liveclip-agent-runtime-v2-acceptance-v2.md
config/loop-engineering/trusted-context/liveclip-agent-runtime-v2-successor-v1.json
```

The first three are copied from a controller-accepted delivery postimage
before setup. The fourth must remain absent through materialization, setup,
readiness, doctor, and `loop-init`; it is created once afterward with
`O_CREAT|O_EXCL|O_NOFOLLOW`, mode `0600`, full-write verification, file
`fsync`, reopen identity/hash verification, and parent-directory `fsync`.
The repository schema seed at that path is never copied into the successor.

The final record is non-executable evidence. It supplies no commands and does
not authorize product behavior. Its authority derives only from Trusted Main
construction, literal controller acceptance of its exact bytes after closure,
and the existing loop policy snapshot that freezes every file under
`config/loop-engineering`. The fresh Planner and Coder must verify the record,
the requirement, their prompt run ID, candidate root, B2 identities, accepted
M2 evidence, blocked predecessor, and current toolchain snapshot before any
product edit. A mismatch is `BLOCKED`, never a reason to widen authority.

## Fresh-run rules

`loop-init` is the only action allowed before the final record exists. It
invokes no role. Trusted Main must discover exactly one generated run ID from
the sole new `.loop/runs/<run-id>/state.json`; it must match
`YYYYMMDDTHHMMSSZ-[0-9a-f]{8}`, be different from the predecessor ID, and be
`received` with zero plan/code cycles, no Coder session, no artifacts, no
command results, no error, exact candidate root/HEAD, and this requirement's
exact text/hash subject only to the initializer's documented terminal-LF
strip.

The final trusted-context record then binds that run ID and the initial state
path, size, mode, and SHA-256. It never embeds its own SHA or any fingerprint
that includes its own bytes. After it is sealed, the controller computes and
binds externally the record hash, candidate worktree fingerprint, policy
snapshot identity, ToolchainManager source/snapshot identities, and exact
`loop-run` argv identity. No file is rewritten to store those derived hashes.

Only one exact `loop-run` may follow. Planner, Reviewer, Tester, and Gateway
remain fresh read-only roles. The Coder is a new isolated non-ephemeral
session; only its exact newly recorded session ID may be resumed within the
same checked-in two-plan/three-code-cycle budget. The blocked Coder session is
never reusable.

## Acceptance and stopping conditions

Before any product edit, both Planner and Coder must report the exact trusted
record path/hash, successor requirement hash, fresh run ID, candidate root,
B2 manifest/patch/list identities, accepted M2 final index, blocked predecessor
state and Coder artifact identities, and current sealed toolchain source and
snapshot fingerprints. The formal workflow and original Coder allowlist are
unchanged.

Stop without repair or replacement on source, receipt, root, requirement,
state, policy, toolchain, session, profile, allowlist, environment, or
protected-evidence drift; any copied cache/dependency/`.loop`/data/input path;
any remote or unsafe link; an extra run ID; old-session reuse; credential
request; model-product inference; interruption after `RECEIVED`; exhausted
budget; or a terminal state other than correlated `DONE`.

The formal loop performs engineering work and deterministic Runner checks
only. It does not access the completed product evidence, render media, run a
benchmark, perform human editorial/audio review, infer with a product model,
publish to the delivery worktree, commit, or push. Human editorial/audio and
subtitle calibration remain `PENDING_HUMAN`; default promotion, v1 parity,
editorial/audio PASS, and full benchmark PASS remain unclaimed.
