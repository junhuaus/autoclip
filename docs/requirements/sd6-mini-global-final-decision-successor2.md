# SD-6 mini Global final-decision successor 2

## Starting evidence

Parent formal runs `20260915T215821Z-d1ef69c8` and
`20260915T231518Z-3cc4a9a1` are terminal BLOCKED and unpublished. The first
preserves the original Prompt change plus a host-load full-test timeout. The
second Coder made the direct regression lint-safe while preserving full AST and
Prompt SHA-256 `fef9173cbeb2175ddb1aff30f9c4c6efdaf22718e5fce01af3fbbfe99a686073`;
fresh Reviewer found zero findings. Its fixed Runner could not execute the
project toolchain because the trusted successor cloner rewrote Main-owned
`.venv` shebangs against the assurance path instead of the Main path. This was
a clone/toolchain defect, not a product or test assertion failure. All three
results remain immutable FAIL.

Successor 2 starts from the second run's sealed assurance product source
fingerprint `bdc9b93fb55db73c336e7c78e8d7d5fdefeef89453f53bbd02679004344a9569`.
It receives a fresh Main-owned local toolchain whose embedded paths are
rewritten from the actual Main source root into this candidate. Role-visible
handoff text files and a hash index preserve both terminal parents and Runner
diagnostics without relying on ignored `.log` paths.

## Authorized scope

The fresh sole isolated Coder may change exactly:

- `src/liveclip/clipping_skills/semantic_topic_chain_v1/stages/global_review.md`
- `tests/unit/test_semantic_lineage_prompts.py`

No product change is expected. Independently verify that the Prompt and
evaluated four-clause regression already satisfy the original contract and
that the test is lint-safe. If and only if a defect remains, repair it within
those two paths. Do not change any toolchain, Runner, timeout, allowlist,
sandbox, dependency, validator, schema, runtime, selection, score, risk,
quality, retry or budget setting.

## Required behavior

Both composed mini Global Review Prompts must state that the supplied
`boundary_reviews` interval is final for this stage; judge it independently;
return `keep` when acceptable and `drop` otherwise; never copy or return the
upstream `repair_boundary`; and never request a second boundary repair. Keep
all existing editorial gates and both profile cases exact.

## Acceptance

Fresh Planner, one new Coder, fresh read-only Reviewer and Tester, fixed Runner
`lint`, `e2e`, `test`, and fresh Gateway must all agree on one sealed source and
toolchain. All commands must PASS. A slow or inaccessible environment remains
a blocker; never extend the timeout or reduce coverage. Main independently
audits both parent failures, exact Coder/session/path scope, baseline-negative
behavior, source/toolchain fingerprints, QA correlation and Gateway PASS
before atomic compare-and-swap publication. No real mini Delivery success is
implied.
