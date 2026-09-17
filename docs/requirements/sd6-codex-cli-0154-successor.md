# SD-6A Codex CLI 0.154 successor: byte-exact version probe

## Preserved predecessor and exact remaining gap

Formal run `20260915T031428Z-183c2855` is terminal BLOCKED and unpublished.
Its sole isolated Coder `01a0a314-42be-7451-975b-01f83496ba84` changed exactly
`src/liveclip/providers/llm/codex.py` and `tests/unit/test_codex_llm.py` in the
sealed assurance source at fingerprint
`2f8ed6150ad58ca671819bc4599917ea435ed9bc253e7841eac8a868b6411806`.
Reviewer found one P2 and returned FAIL; Tester correctly returned BLOCKED;
no Runner or Gateway ran. The full bounded record, artifact hashes, trusted
starting snapshot and exact two-file delta are in
`docs/verification/sd6a-first-blocked-lineage.json`.

The remaining product gap is precise. `codex_cli_contract_version` invokes
`subprocess.run(..., text=True)`, so Python universal-newline decoding changes
a child response ending only in bare carriage return into line feed before the
strict regex sees it. A mock `CompletedProcess` string test does not exercise
this transformation. LiveClip must validate the actual captured bytes.

## Scope and ownership

The new sole isolated successor Coder may edit only:

- `src/liveclip/providers/llm/codex.py`
- `tests/unit/test_codex_llm.py`

It inherits and must preserve the predecessor's exact 0.154.0, tool-free-v3,
single `code_mode_host` enable, 88 explicit authority-feature disables,
contract drift rechecks and hard tool-item rejection. Main owns requirements,
ADR/plan/STATUS, lineage/classification evidence, QA, audit, real probe and
publication. All other paths are read-only. Fresh assurance roles are
read-only. Never use `--last`; only the new recorded successor Coder writes.

## Required implementation and tests

1. Capture `codex --version` stdout as bytes without universal-newline
   normalization. Accept only the exact ASCII bytes `codex-cli 0.154.0`, with
   either no terminator, LF, or CRLF. Reject bare CR, other whitespace, extra
   lines/bytes, non-ASCII, NUL, malformed versions, all other versions and
   nonzero exit before any inference process can start.
2. Add a regression using an actual executable child process whose stdout
   bytes end in bare CR. It must call the real version-contract function and
   prove rejection. Keep direct cases for the three accepted byte forms and
   all predecessor malformed/version cases.
3. Preserve executable path/regular bytes/size, version and profile binding;
   per-call identity recheck; saved-login probe; ignored config/rules;
   ephemeral/read-only/no-approval execution; private cwd; bounded stdin,
   schema and output; credential/proxy removal; and tool-event rejection.
4. Use the complete disjoint 140-feature review in
   `docs/verification/sd6-codex-cli-0154-feature-classification.json`. The
   receipt binds the installed executable/inventory and predecessor assurance
   code hashes. Do not derive the test expectation from the production tuple
   or add a new enabled feature.
5. Fixed Runner `make lint`, `make e2e` and full `make test` must PASS from one
   sealed source/toolchain identity. Fresh Reviewer must return PASS with no
   unresolved P0/P1, Tester READY and Gateway PASS. Missing, stale, failed,
   mutated or uncorrelated evidence prevents DONE.
6. Main publishes only after formal DONE and independent audit of the trusted
   starting snapshot, successor Coder session, exact authorized paths,
   version/feature invariants and QA history. Post-publication focused tests
   and the separately guarded real probe remain required before any actual
   inference/content/package claim.

## Bounded inspection guidance and recovery

Use bounded reads and hashes for long STATUS, QA and inventory files; never
print a full worktree status or 140-feature JSON when hashes/counts/selected
keys suffice. QA `20260915T030822Z-f274` and predecessor formal BLOCKED remain
unchanged. If this successor fails, retain its exact session and evidence,
publish nothing, and derive any later successor from the last justified sealed
source. Do not spoof CLI versions, widen the probe limits, install a different
CLI or use the exposed OpenRouter key.
