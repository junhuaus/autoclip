# ADR 049: Codex CLI 0.154 editorial security profile

Date: 2026-09-15. Status: accepted and published.

## Context

The LiveClip editorial adapter pins an exact Codex CLI version and hashes the
resolved executable identity plus a named security profile into every Pipeline
contract. The installed CLI advanced from the prior reviewed 0.147.0 to
0.154.0. The first bounded five-minute real-source probe correctly stopped at
readiness with `CODEX_CLI_NOT_READY`, zero Codex launches and no Delivery.
Version and saved-login diagnostics identified supported-version drift rather
than missing authentication.

Codex 0.154 uses the local `code_mode_host` transport for current models.
ADR031 reviewed that transport for the developer control plane: the host is
not itself permission to execute a command, and external authority remains a
function of enabled tools, sandbox and approval policy. The product adapter
therefore needed a new profile identity and an explicit 0.154 feature review.

## Decision

Accept exactly Codex CLI 0.154.0 under tool-free profile `tool-free-v3`.
Enable only `code_mode_host` as required local model transport. Explicitly
disable 88 known command, shell, unified execution/TTY, write-stdin, patch,
browser, computer, network/search, MCP/app/plugin, hook, goal/memory,
multi-agent, worktree, image and approval/request features. The complete and
disjoint classification covers all 140 features reported by the installed CLI.

Continue to ignore user configuration and rules, run ephemerally in a private
temporary directory with sandbox `read-only` and approval `never`, and pass
transcript data only through bounded stdin. Continue rejecting every JSONL
tool event even if the process also creates schema-valid output. Retain bounded
event parsing, strict local schema/EditPlan validation, one schema repair,
deterministic degradation, credential/proxy environment removal and per-call
executable-contract rechecks.

Capture `codex --version` as bytes. Accept only exact ASCII
`codex-cli 0.154.0` followed by no terminator, LF or CRLF; reject bare CR,
non-ASCII, additional whitespace/lines/bytes and every other version before
inference. This prevents universal-newline normalization from weakening the
exact-version boundary.

## Acceptance evidence

The first formal implementation `20260915T031428Z-183c2855` remains terminal
BLOCKED and unpublished. Its Reviewer found that text-mode subprocess capture
normalized a malformed bare-CR version response before validation. Tester
returned BLOCKED and no Runner or Gateway ran.

Fresh successor `20260915T033147Z-feb147f9` is formal DONE. Sole isolated Coder
`01a0a322-3b79-7b32-8cc4-f08c5361d246` changed exactly
`src/liveclip/providers/llm/codex.py` and `tests/unit/test_codex_llm.py`.
Reviewer returned PASS with no findings, Tester returned READY, fixed Runner
lint/e2e/full-test passed from source fingerprint
`a888cc7ba87435a6c9ade20a76374cf6704110b035c4d4738edc90b83c604b06`
and toolchain fingerprint
`539a2d0227084d6f129cdef225671a2540ae4944cf9e3575352031da90426449`,
and the fresh semantic Gateway returned PASS. The full test passed 2,467
Python and 80 Web tests plus all required browser/media/package checks.

Main independently audited DONE, the exact Coder session, feature partition,
byte capture, actual-child bare-CR regression and preserved failure lineage.
Trusted compare-and-swap publication changed only the two authorized paths.
Post-publication focused QA `20260915T041645Z-c154` passed 71 tests.

The subsequent real short-profile probe on the hash-pinned 2050--2350 second
excerpt passed local MLX transcription, four tool-free Codex semantic calls,
two MP4/SRT renders and immutable ZIP Delivery. Independent database, hash,
CRC, full-decode, subtitle-bound and contact-sheet checks passed. This proves
the bounded real excerpt path; it does not establish human audio/editorial
quality, full-input behavior, repeated stability or 2h/4h performance.

## Consequences

Persisted 0.147 contracts cannot silently resume under 0.154 because exact
version, executable identity and profile identity change the contract. Every
later CLI version fails closed until separately inventoried, classified,
implemented and accepted; version spoofing, broad ranges and automatic
fallback remain prohibited.

The bounded mini-lesson attempt exhausted its separately fixed eight-process
guard after two discovery units and the first five of 22 link reviews. It is
preserved as a deterministic FAIL with no render or Delivery. That result does
not invalidate the accepted 0.154 compatibility profile, but mini-lesson real
acceptance remains open and an unchanged retry is prohibited.

A second mini attempt with a newly derived finite budget stopped at 9/64
launches on a Link Review relationship/boolean contradiction that remained
invalid after repair. This further confirms that CLI capability and tool-free
execution work; ADR050 handles the separate Prompt clarity gap.

## Recovery

Restore the two accepted code/test files from the trusted publication receipt
if the adapter must be rolled back. Preserve all failed probe and blocked-run
evidence. Do not install another CLI, expose credentials, reset a consumed
guard or relax the tool-event/sandbox boundary to obtain a passing result.
