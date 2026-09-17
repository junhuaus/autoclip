# ADR 031: Local Codex tool-host compatibility

Date: 2026-09-12. Status: proposed, isolated prerequisite under review.

## Context

Formal SD-1A run `20260912T160102Z-12b7777d` failed before any Coder or Runner action.
Codex CLI 0.154.0 emitted a typed error because the checked-in feature policy disabled
`code_mode_host`. Its bundled models need that local tool transport even with the optional
`code_mode` feature disabled. The installed package already supplies `codex-code-mode-host`.
Enabling the local host must not grant additional file, process or external-tool authority.

A real exact-session canary also found that `exec resume` rejects the exec-only `--color`
argument. Both errors are control-plane compatibility issues, separate from SD-1A product changes.

## Decision

Explicitly enable only `code_mode_host` through shared checked-in argv construction for fresh
roles, exact Coder resumes and Doctor. Keep `code_mode` and all previously disabled external
surfaces disabled. Doctor verifies effective feature values, not only CLI parser success.
Remove the unsupported display flag only from the resume invocation. Preserve schema validation,
durable session identity, ignored mutable user configuration/rules, role sandbox and never approval.

Preserve bounded event output and fail closed on the actual typed CLI host-unavailable event
before accepting a role artifact. Model-authored prose is not a trusted event. This avoids spending
another planning cycle on an unchanged tool failure or mistaking a semantic verdict for usable tools.
The process capture reports whether raw output exceeded its bound; role results then fail closed,
even if a valid final JSON exists. Thus an early error cannot disappear from the retained tail and
be accepted. The bound and redaction remain unchanged, and Runner log truncation semantics are unchanged.

No global configuration, CLI installation, role profile, Runner sandbox, allowlist, frozen
toolchain, evidence correlation, retry budget or Gateway policy changes are included.

## Verification and limits

Focused tests cover new/resumed argv, all five role authorities, effective feature drift and
host errors accompanying both READY and NEEDS_INPUT model results. Real synthetic probes verify
actual file bytes and command denials for read-only, workspace-write and exact-session resume.
The final probes execute fixed harness-authored scripts whose bytes must remain unchanged. Their
command output contains actual caught PermissionError types and errno values; model summaries are
insufficient. An earlier probe lacked those tool records, and its negative authority claim was withdrawn.
Protected probes must be outside both the workspace and the CLI's existing writable temporary
roots: a sentinel in TMPDIR cannot prove an outside-workspace denial. Scratch temporary access
is existing CLI behavior; the trusted toolchain and evidence remain outside Coder's writable root.

These development probes are supplementary. The unchanged deterministic Runner and a fresh
independent review/Gateway must still accept the exact product candidate before publication.
Doctor readiness alone does not prove actual model tool usability or product acceptance.

## Recovery

Keep old blocked run, failed probes and previous source baselines immutable. Missing host,
unsupported CLI or changed policy fails closed. Correct a verified compatibility cause in its
own reviewed prerequisite before creating a new run; never edit state or reset its retry budget.

## Sources

Installed `codex features list`, `codex exec resume --help` and actual retained CLI events are
the version-specific evidence. Official documentation describes the default local host and
underlying permission boundaries:
[App Server](https://learn.chatgpt.com/docs/app-server),
[Permissions](https://learn.chatgpt.com/docs/permissions).
