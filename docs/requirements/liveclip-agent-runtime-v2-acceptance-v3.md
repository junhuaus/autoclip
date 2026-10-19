# Agent Runtime v2 bounded-tree successor requirement

This is a bounded formal-loop requirement owned by Trusted Main. It is not an
ExecPlan and it grants no execution authority. The sole authoritative Living
ExecPlan is `docs/exec-plans/liveclip-agent-runtime-v2.md`.

This requirement incorporates, without weakening, the complete product
outcome, compatibility rules, Runner commands, acceptance distinctions, and
prohibitions from these immutable predecessors:

- `docs/requirements/liveclip-agent-runtime-v2-acceptance.md`, 16,335 bytes,
  SHA-256
  `6c262edb9463583614979d9b2e24f12a94c8f1a40c43b4537f95381a9259c3f8`;
- `docs/requirements/liveclip-agent-runtime-v2-acceptance-v2.md`, 8,771 bytes,
  SHA-256
  `31e967e04b3f9987e5c0a9ac00b809c215aed543f9da035c3a06e73ebc976400`.

If either predecessor differs, stop. This requirement supersedes only the
immediate predecessor closure, trusted-context version, and exact Coder
allowlist stated below. It does not expand product scope, change the formal
Planner/Coder/Reviewer/Tester/Runner/Gateway workflow, or relax any gate.

## Why a fresh successor is required

Candidate `candidate.oivrdV6U`, run `20261014T191719Z-0802b465`, and Coder
session `01a13c35-37c9-7493-821a-6cefd8ed7513` are terminal consumed evidence.
The only official invocation exited `2` and retained `blocked` at plan/code
cycle `1/1`. Its exact evidence is:

- `state.json`: 12,021 bytes, mode `0644`, uid 501, SHA-256
  `78b8133ace2dbf2b9237465028245ab4e953fc4631c9c21f8f87f274af45d47d`;
- `events.jsonl`: 4,224 bytes, mode `0644`, uid 501, SHA-256
  `b9abfe8299d47328ca50638515f857115d6166a8b80ee8113a341007a0b12603`;
- Planner `READY`: 11,291 bytes, mode `0644`, uid 501, SHA-256
  `39133d5beb3b72e22f4d2e96e9f3100a2bcbf4a27eef83195b738f582549c8c2`;
- Coder `BLOCKED`: 2,691 bytes, mode `0644`, uid 501, SHA-256
  `53e325e8ef39291201051a03a8dedccea2b7b8c65165495ac287d9e4a421e945`;
- empty command results and no Reviewer, Tester, Runner, Gateway, publication,
  or product-file delta.

The exact stop is architectural, not a request to resume that Coder. The
completed-bundle validator must reject an unexpected tree with bounded work,
but `liveclip.media.secure_files._scan_regular_directory_tree` currently
materializes every entry in a directory and recursively scans unexpected
subtrees before the caller compares the observed tree with the expected one.
Implementing a second filesystem traversal in an application service would
duplicate adapter logic and violate the accepted dependency boundary.

The retained candidate, run, role session, artifacts, authentication handoff,
and every V39 root/result/receipt are immutable and never reusable. Never
resume the Coder session, retry the invocation, use `--last`, or use
`resume_liveclip.sh`.

## Architecture decision

The narrow repair belongs in `src/liveclip/media/secure_files.py`.
`liveclip.media` is the established local-filesystem infrastructure adapter;
it imports only Python standard-library modules and is already consumed by
application/services, delivery, renderer, database, pipeline, and provider
adapters. Allowing the formal Coder to modify this file preserves the strict
direction `entry points -> application/services -> domain/ports ->
infrastructure adapters`. It does not permit `liveclip.media` to import an
application service, framework, control-plane module, or product model.

Dedicated adapter regression coverage belongs in
`tests/unit/test_secure_files.py`. No other infrastructure, schema,
dependency, configuration, control-plane, Skill, Prompt, or workflow path is
added.

## Exact Coder allowlist

Only the fresh formal Coder may write product/test code, only in its isolated
fresh candidate, and only at these thirteen paths:

```text
src/liveclip/agent_runtime/__init__.py
src/liveclip/agent_runtime/checkpoints.py
src/liveclip/media/secure_files.py
src/liveclip/services/agent_clipping_validation.py
src/liveclip/services/agent_clipping_delivery.py
src/liveclip/cli/app.py
scripts/evaluate_agent_benchmark.py
tests/unit/test_agent_runtime.py
tests/unit/test_agent_clipping_validation.py
tests/unit/test_agent_clipping_delivery.py
tests/unit/test_agent_benchmark_evaluator.py
tests/unit/test_secure_files.py
tests/integration/test_agent_clipping_v2.py
```

The two-path expansion from the inherited eleven-path allowlist is exactly
`src/liveclip/media/secure_files.py` and `tests/unit/test_secure_files.py`.
Every other path remains forbidden. `qa/pipeline.jsonl` and
`qa/test-report.md` remain Runner-owned append-only evidence and are not Coder
paths. If implementation requires another path, stop `BLOCKED` for a new
Trusted-Main replan; never widen this list in-role.

## Bounded exact-tree acceptance

The future implementation must preserve the public no-follow publication and
validation APIs and their descriptor/inode/rehash/rollback guarantees. It may
refactor their private scanner only as needed to establish all of these facts:

1. Expected canonical regular-file and directory names are derived once from
   the already supplied pinned-file mapping. The maximum visit count is the
   exact number of expected files plus expected directories; maximum depth is
   derived from those canonical relative paths.
2. Directory entries are consumed incrementally. The implementation must not
   materialize `tuple(iterator)`, `list(iterator)`, or another unbounded copy
   of a directory before validation.
3. Each relative name is checked against the expected file/directory sets
   before metadata access, child open, or recursion. An unexpected directory
   is rejected without opening or enumerating that subtree.
4. Entry and depth counters fail closed before exceeding their exact limits.
   Seen-name collections cannot grow beyond the expected tree. Missing,
   duplicate, extra, symlinked, special, type-mismatched, or unstable members
   fail with `SecureFileError`.
5. Expected directories remain opened component-by-component with no-follow
   semantics, fd/path identity comparison, and post-child stability checks.
   Expected regular-file content is read or hashed only through its existing
   pinned evidence after the exact tree shape passes.
6. A validation failure performs no publication and leaves no success receipt.
   A post-rename validation failure retains the existing fail-closed rollback
   contract. No source media or completed evidence is used in formal tests.

The formal tests must use temporary synthetic trees and prove exact success;
missing and extra files/directories; an unexpected wide directory; an
unexpected deep subtree that is never opened or scanned; exact entry/depth
limit rejection; symlink/special/type substitution; endpoint mutation;
duplicate canonical names; bounded memory-shape behavior; no input mutation;
no success publication after failure; and compatibility of existing directory
publication/rollback behavior. Tests must avoid timing-only assertions and
must not read protected media, completed evidence, or credentials.

The remainder of the inherited outcome is unchanged: exact completed-bundle
correlation, truthful technical/human/non-applicable benchmark distinctions,
all-30 render/package binding, compatibility, immutable no-replace outputs,
and the original acceptance categories still apply.

## Fresh source, candidate, run, and trust contract

The successor is reconstructed from the immutable B2 seed, never from
`candidate.oivrdV6U` or another retained candidate:

- branch/HEAD `main` / `2f361fcddc0e63ae62ee62826e27b54bb8204c53`;
- seed repository
  `/Users/junhuaxu/Library/Application Support/LiveClip/engineering-candidates/agent-runtime-v2/a822890ace12/candidate.OlsWg1/repo`;
- B2 manifest 2,322 records / SHA-256
  `e6bc1213d482c38c78b97c3390ea35c05ca05efb2c1ff1d754e3894a04fd8044`;
- tracked patch SHA-256
  `472638a7f6c78634d3dbe5508716fc3a1328761dd4047eaf1b20c4d494a01254`;
- 71-path overlay-list SHA-256
  `1cbfb3a787026491c1c979ce3f263adece51af8cc1210c94094dd7bf2ee3cec7`.

Trusted Main must first freeze and externally accept one fresh no-replace
successor root. Candidate preparation is credential-free and may allocate at
most one unpredictable `candidate.XXXXXXXX`, create at most one result, and
run exactly one official initialization:

```json
["/usr/bin/make","loop-init","REQUIREMENT=docs/requirements/liveclip-agent-runtime-v2-acceptance-v3.md"]
```

The initial run must be a new ID, `received` at cycle/code-cycle `0/0`, with
null Coder session/error and empty artifacts/command results. It must differ
from every retained run and bind the exact candidate root, HEAD, requirement
bytes, final documents, source identities, policy, toolchain, and predecessor
set.

The candidate-local non-executable trusted record is versioned separately at:

`config/loop-engineering/trusted-context/liveclip-agent-runtime-v2-successor-v2.json`

It is absent through materialization, setup, readiness, doctor, and
`loop-init`; afterward Trusted Main may create it exactly once with
`O_CREAT|O_EXCL|O_NOFOLLOW`, mode `0600`, full-write verification, file and
parent `fsync`, and reopen identity/hash verification. It binds the fresh run,
this requirement, final ExecPlan/STATUS, exact thirteen-path allowlist,
immutable B2 source, accepted V39 terminal closure, candidate root/HEAD,
policy snapshot, and sealed toolchain. It contains no command and grants no
product authority. External controller acceptance of its final bytes and all
derived bindings is required before formal dispatch.

No V39 private HOME or authentication artifact may be copied, probed, reused,
or included in manifests. Any future authentication handoff is a distinct
one-use opaque boundary requiring new explicit operator authority for the
fresh accepted candidate. Authentication success is not formal authority.

## Formal workflow, budgets, and gates

The checked-in official workflow is unchanged. Planner, Reviewer, Tester, and
Gateway are fresh read-only roles. The Coder is one fresh isolated durable
writer, and only its exact newly recorded session may be resumed by the
checked-in state machine within the inherited two-plan/three-code-cycle
budget. The deterministic Runner retains the fixed checked-in commands and
timeouts: `lint` 900 seconds, `e2e` 900 seconds, `test` 2,400 seconds, and
non-final `doctor` 300 seconds. Role calls retain the 3,600-second bound.

Before any Coder write, Planner and Coder must independently report this
requirement hash, fresh run/root, B2 identities, the complete V39 terminal
state/Planner/Coder evidence, exact old and expanded allowlists, current
`secure_files.py` preimage, trusted-record identity, policy, and toolchain
fingerprints. Coder delta must remain a subset of the thirteen paths. Runner
tests execute only fixed IDs against the retained exact source snapshot.
Reviewer, Tester, deterministic correlation, and semantic Gateway must accept
the same evidence; Gateway cannot override failed or stale deterministic
evidence or unresolved P0/P1 findings.

Candidate/result/suffix/init, authentication, formal dispatch, and publication
are distinct single-use budgets. Each is consumed at its documented creation
or launch boundary. Any mismatch, timeout, truncation, role block, unexpected
path, need for another source path, exhausted budget, unsafe filesystem
behavior, or non-`DONE` terminal state is retained and stops without retry,
repair, replay, replacement, cleanup, or reuse. A stopped boundary requires a
new successor design and new controller authority.

Formal `DONE` means only correlated engineering acceptance. It does not imply
real-media rendering, benchmark execution, editorial/audio review, product
model inference, default promotion, v1 parity, publication to delivery, commit,
or push. Trusted CAS publication is a later distinct boundary after all gates
pass.

## Absolute prohibitions

This requirement itself authorizes no root creation, candidate allocation,
`loop-init`, authentication, formal/model role, Runner, test, lint, service,
render, evaluation, inference, publication, source-media access or mutation,
delivery-worktree publication, commit, push, cleanup, `--last`, or
`resume_liveclip.sh`. It never authorizes reuse or mutation of a retained
root, result, candidate, run, session, or evidence file.
