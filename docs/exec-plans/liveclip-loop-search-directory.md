# Search-only intermediate directory traversal

2026-09-12. User authorized continuous development while preserving Coder/Runner security. Main is
the sole supervised Coder in this isolated full clone; parent baseline manifest preserves source hashes.
The previous CLI and sealed-toolchain candidates and all failed receipts remain intact.

## Purpose and actual failure

`secure_files._open_directory` traverses each intermediate directory with O_RDONLY. Actual sandboxed
Runner test QA20260912T164243Z-d9bb fails during fixture collection because this requests read/list
authority on HOME merely to reach an authorized source file. Do not grant directory listing rights.
Fixed synthetic probe QA20260912164541Z-3be5 proves O_SEARCH plus O_DIRECTORY/O_NOFOLLOW/O_CLOEXEC
can traverse and read the authorized file under the same sandbox; all existing negative tests pass.

## Scope, design and ownership

Only `src/liveclip/media/secure_files.py` and `tests/unit/test_secure_files.py` may change, plus ADR033
and this plan. Do not change validators, prompts, schemas, dependencies, lock/Make, Runner, Coder,
allowlist, credentials, source media, databases or existing artifacts. SD-1A10 implementation hashes stay
unchanged. The main agent owns integration; no other writing agent is active.

Use O_SEARCH, when the OS exposes it, only for intermediate directory descriptors. Retain O_NOFOLLOW,
O_DIRECTORY and O_CLOEXEC. Keep the final directory descriptor O_RDONLY for existing listing/fsync/
publication semantics. Existing creation, errors, descriptor cleanup and race protection must remain.
On platforms without O_SEARCH retain existing behavior; do not add a weaker fallback.

- [x] 2026-09-12: actual read red QA8601 fails on chmod0111 ancestor; listing also denied. Publication assertion corrected to include required max_bytes before green.
- [x] Implement minimal intermediate-descriptor selection; preserve final descriptor capabilities.
- [x] QA20260912164808Z-a81e passes all29 secure-file regressions, including symlink races, publication, cleanup and fsync, in0.17s.
- [ ] Verify under actual existing sandbox with source and HOME protections unchanged; full lint/test.
- [ ] Fresh independent read-only review; combine reviewed prerequisites into a new SD-1A baseline.
- [ ] Complete formal five-role gates and trusted publication; no diagnostic can replace them.

## Recovery and acceptance

Register each command before execution in original root QA and append correlated reports. Preserve
failed d9bb evidence and probe receipts. No existing sealed cache/run state is rewritten. Withdraw only
this candidate if a regression appears; code/state identity changes require fresh evidence. The first
next task is the search-only ancestor counterexample. No cloud or real-video acceptance is claimed.

Current next task: actual combined-candidate lint and frozen Runner lint/test, plus independent
read-only review of this two-file delta against the previous entrypoint candidate. Its bounded
review 01a09683-c83a-7e62-9cbb-e3a7d8752da5 now PASSes with no findings and complete retained output.
The earlier semantic PASS with truncated output was rejected; all receipts remain retained.
