# Loop CLI tool compatibility prerequisite

2026-09-12. User authorized continuous development to completion; this bounded control-plane prerequisite is separate from SD-1A. Main agent is the sole supervised Coder in this isolated candidate. Original product tree, SD-1A candidate and blocked Loop receipts are preserved.

## Purpose

Codex CLI 0.154.0 must support actual role-local file tools while all existing Coder, assurance and Runner authority boundaries remain enforced. Prior run 20260912T160102Z-12b7777d stopped because code_mode_host was disabled; the current CLI bundles a local helper and models require that tool transport.

## Scope and ownership

Only tools/loop_engineering/config.py, codex.py, cli.py, process.py and tests/unit/test_loop_engineering.py may change, plus this ExecPlan, ADR 031 and docs/loop-engineering.md. Main owns integration and all shared docs. Do not change role model/profile bytes, role sandbox or never approval, Runner/allowlist/gateway policy, product source, dependencies, historical runs or delivery.

## Plan and evidence

- [x] 2026-09-12 16:10 UTC: reproduce absent host in six clean failing cases; two initially invalid fixtures corrected and excluded from red evidence.
- [x] Explicitly require only the local tool-host feature; keep other external features disabled. Share feature argv between new/resumed roles and Doctor.
- [x] Treat actual tool-host-unavailable events as an environment AgentError after preserving output, instead of burning another planner cycle or accepting semantic success.
- [ ] Verify existing isolation, immutable evidence, exact session and gateway regressions, lint/types.
- [x] 2026-09-12 16:18 UTC: QA 20260912161647Z-6546 passes real Planner/Coder/exact-resume probes with command denials and unchanged outside bytes; retained tool-probe-20260912T161647Z.
- [ ] Independent fresh read-only security review of this compatibility delta and actual canaries; address concrete findings.
- [ ] Integrate the reviewed prerequisite into a new SD-1A baseline, preserving old baseline/receipts; rerun bounded formal workflow against changed verified conditions.

## Safety and recovery

The local Code Mode host is tool transport, not a permission grant. Underlying file/command tools must still enforce role sandbox and never approval; no remote host/network listener is introduced. No global CLI/config changes. Coder remains the only writing role and only within its isolated candidate; Runner remains deny-default, fixed argv, external network denied and evidence-bound. A missing host must fail closed. Do not manually edit blocked state or reuse a previous final PASS after any source/policy change. Old snapshots stay immutable; rollback withdraws only this new candidate.

## Surprises, decisions and current evidence

46 focused tests passed (QA 20260912161053Z-18df); full lint passed including 319 Ruff and
177 Mypy files plus Web TypeScript (20260912161540Z-d0f2). Real probes under the ignored
parent preserve failures. The initial unregistered probe is excluded; a later probe used a
sentinel in TMPDIR and therefore made an invalid denial assumption. A non-temporary sibling
fixture proved fresh Planner writes denied and Coder inside writes allowed/outside writes denied.
Its exact resume then exposed unsupported `--color` (20260912161532Z-63c0). A clean regression
failed on that argument (20260912161630Z-e6f1), and only the display flag was removed.
Reverification is in progress; no formal product acceptance or publication is claimed.

Decision: retain existing CLI scratch-root behavior and test protected non-temporary files that
represent actual toolchain/evidence placement. Do not widen any sandbox to make a probe pass.
The sole Coder still owns only these four source/test files. No product code or locks changed.

Concrete diagnostics from this candidate: `.venv/bin/python -m pytest -q -p no:cacheprovider
tests/unit/test_loop_engineering.py`, `make lint`, and `make loop-doctor`. Register commands in
the root append-only QA pipeline before execution. Real probes and independent review artifacts
live in the ignored parent directory, not product fixtures. A denied write is a successful
negative observation only when the external harness confirms unchanged bytes and real tool logs.

Next: complete corrected exact-resume probe and focused regressions, obtain fresh read-only review
of the four-file delta and ADR 031, then record the accepted prerequisite baseline before formal SD-1A.

## References

Official App Server docs describe the default local Code Mode host: https://learn.chatgpt.com/docs/app-server . Official permission docs separate tool surfaces and local command sandbox enforcement: https://learn.chatgpt.com/docs/permissions . Installed 0.154.0 package includes codex-code-mode-host; no download is required.

2026-09-12 16:21 UTC independent review FAIL with two P2 findings: tail truncation can hide an early host error, and negative write probes lack tool-level denial records. Prior byte-only negative acceptance is withdrawn. Scope now includes process.py solely to report truncation; agents reject truncated evidence without changing Runner command/log policy. Fixed trusted scripts must capture actual PermissionError output and remain byte-identical. Review artifacts: parent/review-20260912T161802Z.

2026-09-12 16:22 UTC: review fixes implemented. QA 20260912162030Z-283d clean red reproduced early-error loss (3 failures); 20260912162131Z-690e now passes 48 tests. Fixed-script canaries 20260912162110Z-a500 retain actual command output containing PermissionError errno 1, verified immutable scripts and exact Coder resume. This supersedes the earlier withdrawn negative claim. Fresh re-review pending.
