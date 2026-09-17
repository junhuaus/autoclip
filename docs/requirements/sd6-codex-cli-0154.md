# SD-6A Codex CLI 0.154 editorial compatibility

## Problem and user-visible outcome

The bounded real-source short-highlight probe QA `20260915T030822Z-f274`
failed closed before inference. The installed and authenticated Codex CLI now
reports `codex-cli 0.154.0`, while the product editorial adapter accepts only
the previously reviewed `0.147.0`. The probe used local MLX ASR, injected no
cloud ASR or LLM key, spent zero Codex `exec` launches and produced no
Delivery. Preserve that failure.

After this slice, LiveClip may use exactly Codex CLI 0.154.0 through a newly
identified, reviewed tool-free editorial profile. It must still reject every
other CLI version, mutable user configuration, executable-identity drift,
model tool activity and any attempt to obtain file, process, network, browser,
MCP, plugin or multi-agent authority. A version/login check remains readiness
evidence only; the real five-minute product probe after publication supplies
actual inference evidence.

## Exact scope and ownership

The sole isolated Coder may edit only:

- `src/liveclip/providers/llm/codex.py`
- `tests/unit/test_codex_llm.py`

Main owns ADR049, this requirement, the Living ExecPlan, STATUS, QA
integration, feature-inventory receipts, the post-publication real probe and
trusted publication. Do not change dependencies, prompts, schemas, provider
fallbacks, model defaults, retry budgets, the control plane, Runner policy,
credentials or source media. Planner, Reviewer, Tester and Gateway are fresh
read-only sessions. Only the one recorded Coder session may write in the
isolated candidate; never use `--last`.

## Required behavior and evidence

1. Accept the exact version line `codex-cli 0.154.0`; reject 0.147.0, newer,
   older and malformed responses. Bump the security-profile identity so the
   immutable provider contract cannot collide with the prior reviewed profile.
   Continue binding resolved executable path, regular-file bytes and size,
   exact version and profile identity, and recheck before every call.
2. Review the installed 0.154.0 feature inventory. The model-required local
   `code_mode_host` transport may be explicitly enabled only if `code_mode`,
   shell, unified execution, apply/patch, browser/computer, network/search,
   MCP/apps/plugins, hooks, goals/memory, multi-agent, worktree, image and
   request/approval tool surfaces remain explicitly disabled. New 0.154 tool
   surfaces such as sleep, TTY/write-stdin, code-mode prewarm/interrupt and
   in-app local automation must not be inherited.
3. Retain ephemeral execution, ignored user config/rules, approval `never`,
   read-only sandbox, private temporary cwd, bounded stdin/schema/output,
   credential/proxy environment removal and strict JSONL handling. Any actual
   tool item remains a hard failure even when a valid output file exists.
4. Tests must assert the exact new version/profile contract, old-version
   rejection, required local-host flag, complete mutually exclusive
   enable/disable handling for that host, disabled tool surfaces and existing
   tool-event rejection. No test may fake a real inference success claim.
5. Fixed deny-default Runner `make lint`, `make e2e` and full `make test` must
   pass from one sealed source/toolchain identity. Fresh Reviewer has no
   unresolved P0/P1; semantic Gateway PASS plus complete, correlated,
   unmutated deterministic evidence is required.
6. Trusted Main may publish only after formal `DONE` and independent exact-path
   audit. It must then run an ordinary focused regression and repeat the same
   bounded five-minute short-highlight probe with the pre-recorded six-launch
   and 25-minute caps. A failure remains failure and is not retried by widening
   a limit.

## Recovery

Keep QA `20260915T030822Z-f274` and its zero-launch receipt immutable. If the
formal run blocks or any deterministic gate fails, retain its exact run,
session and QA evidence and publish nothing. Do not disguise 0.154.0 as an old
version, install an unreviewed CLI, bypass readiness or restore the previously
exposed OpenRouter key.
