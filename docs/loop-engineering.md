# LiveClip loop engineering

This control plane automates development work; it does not process livestream media. Run it only on a
dedicated, understood Git branch.

## One-time setup

```bash
make setup
make loop-profiles
make loop-doctor
```

`loop-profiles` copies the reviewed `config/loop-engineering/profiles/*.config.toml` files into
`~/.codex` and refuses to overwrite a different file. Profiles select model/reasoning defaults; the
orchestrator also pins each role's sandbox and `never` approval policy, ignores mutable base user
configuration/rules, and disables external apps, browsers, computer use, plugins, MCP-dependent Skills,
multi-agent work and other nonessential feature surfaces. Codex authentication remains in the user's
normal Codex home. Credential-bearing environment variables, SSH agents and authenticated proxy URLs
are removed from Agent and Runner children.

Codex CLI 0.154.0 requires its bundled local `code_mode_host` for role file/command tools.
The orchestrator explicitly enables that transport while keeping optional `code_mode` and external
surfaces disabled. Role sandbox and approval still govern underlying operations; this adds no remote
tool host or authority. Doctor checks the effective feature values, while a typed host-unavailable
event fails the role closed before artifact acceptance. Resume uses only supported arguments and
the exact recorded Coder session. See ADR 031 and its separate compatibility verification; readiness
does not replace actual tool probes or deterministic gates.

## Run a requirement

Write a self-contained Markdown requirement below `docs/requirements/`, including user outcome,
acceptance criteria, constraints and explicit non-goals. Then either initialize for inspection:

```bash
make loop-init REQUIREMENT=docs/requirements/my-change.md
make loop-run RUN_ID=YYYYMMDDTHHMMSSZ-xxxxxxxx
```

or create and run immediately:

```bash
make loop-run REQUIREMENT=docs/requirements/my-change.md
```

Inspect state with `make loop-status RUN_ID=...`. Durable files are under `.loop/runs/RUN_ID/`:

- `state.json`: current state, budgets, explicit Coder session and evidence references;
- `events.jsonl`: append-only transitions and decisions;
- `artifacts/ROLE/*.json`: strict role outputs;
- `agents/ROLE/*-events.jsonl`: bounded Codex event evidence;
- `runner/*.log`: bounded, redacted command output.

The `.loop` tree is intentionally ignored because prompts may contain private requirements and code
context. Test request/result evidence remains tracked and append-only under `qa/`.
Coder changes are made in an isolated candidate workspace. Reviewer, Tester, Runner and Gateway see a
separate assurance snapshot, so a surviving Coder descendant cannot race accepted evidence or the real
delivery worktree. After every gate accepts that exact snapshot, the trusted outer process publishes it
atomically file by file to the current branch. Before accepting a role result, the outer process
revalidates the local JSON Schema and proves that the
Agent did not change Git HEAD, prior `.loop` evidence or either QA append log. Non-Coder roles must also
leave the product worktree fingerprint unchanged. A missing initial Coder session ID fails closed rather
than starting a different repair conversation. Prompts, Schemas, profiles, `AGENTS.md`, the loop config
and the control-plane implementation are frozen before the writable role starts; a Coder cannot weaken
its own policy or the policy used by a later role.

## Routing and completion

- Planner output not ready or Gateway architecture failure: new Planner session.
- Reviewer P0/P1, Runner failure or implementation-quality Gateway failure: exact Coder session resume.
- Missing authority, Runner `ERROR`, environment impasse or exhausted budgets: `blocked`.
- `done`: latest review has no P0/P1, all required allowlisted commands pass against one HEAD/worktree
  fingerprint, and the fresh semantic Gateway returns PASS.

The default final commands are `make lint` and `make test`. Change `loop-engineering.yaml` through code
review; never accept an Agent-authored argv. `make doctor` is allowlisted but optional because local
Codex/media runtime compatibility can be an explicit environmental limit rather than a code failure.
Known browser-host permission failures are recorded as `ERROR`, never relabelled as product `FAIL` or
hidden `PASS`. Runner resolves the allowlisted executable before launch and adds an outer macOS
deny-default sandbox: external network is unavailable, only localhost browser testing is allowed, HOME
is a private temporary directory, and writes are limited to private temporary/browser-test directories.
Git, `.loop`, `qa/`, repository policy and product source remain unwritable. Before Coder starts, the
outer process verifies that Python and package dependencies are genuinely project-local, copies them to
a sealed cache outside the Coder workspace, and freezes Make/lock inputs. Each command then runs against
a private source snapshot colocated with a copy of those trusted dependencies. Its Git worktree
fingerprint must equal the exact pre-command fingerprint; Gateway recomputes that retained snapshot and
correlates the QA request, report, toolchain identity and immutable log before accepting PASS.

Trusted toolchains and retained execution snapshots live under
`~/Library/Caches/LiveClip/loop-toolchains/REPOSITORY_ID/`, whose parent is private to the current user.
They deliberately sit outside the Coder writable root. Remove an old cache only after its run evidence is
no longer needed; a later run rebuilds it from a verified local environment.

## Recovery

Never use `--last` to recover a role. Run `make loop-status`, inspect the latest event/artifact and
resume by `RUN_ID`; the stored Coder session ID is the only session eligible for a repair turn. If an
Agent process fails before a valid artifact, the run becomes `blocked` with its event log retained.
Correct the external cause, then create a new run in the MVP. Direct state-file editing is unsupported.
`loop-status` intentionally remains available even if the current checked-in loop configuration is
broken, so an operator can still inspect the durable failure record.

## Verified macOS prerequisites (September 12, 2026)

Use project-local `make setup` before `make loop-doctor`. Setup prepares pinned tokenizer
assets in `.cache/tiktoken` and the locked Playwright ffmpeg recording helper in
`.cache/playwright`. Runner uses verified copies inside the sealed toolchain and cannot
download missing assets. Missing, unsafe or corrupt assets fail readiness; do not repair
them by enabling external networking in Runner. Existing corrupt files are preserved by
the tokenizer preparer rather than silently overwritten.

Toolchain format2 relocates Python entrypoint headers to the sealed interpreter before
publication. Ruff/Mypy and the existing Vite/TypeScript build caches use private allowed
scratch directories. Root `/.venv` and `/.python` ignore entries cover trusted dependency
links in nested coding/assurance snapshots; nested same-named source files and links
remain fingerprinted. Do not waive a snapshot mismatch or copy a Coder-replaced dependency.

The macOS policy allows exact ancestor directory metadata/search needed to reach owned
roots while denying private HOME file contents and listing. Source traversal uses O_SEARCH
only on intermediate directories; final file descriptors retain nofollow/read semantics.
Browser startup uses a private MAC_CHROMIUM_TMPDIR and Unix sockets confined to the same
scratch tmp root. Loopback HTTP remains the only allowed IP networking.

Actual platform grants have limits: same-sandbox signals permit descendants to interfere
with one another; the RootDomainUserClient grant covers the interface, not only its power
notification methods; numeric Chrome Mach rendezvous names are namespace-scoped, not
caller-PID-equal. Synthetic probe21 confirms a non-existent PID-form name can be reserved,
then destroys it. This permits possible namespace squatting/startup interference. Foreign
signals/sockets, unrelated Mach names, private HOME/env, source/QA writes and external IP
network remain denied in the recorded actual probes. See ADR032–035 and associated receipts.

Both Agent and actual Runner reject truncated evidence, including an otherwise successful
exit0. Required tests still run only checked-in allowlist IDs. A semantic PASS never
rescues truncated, mutated, stale or uncorrelated deterministic evidence.

## Interrupted-run recovery clarification

`make loop-run RUN_ID=...` starts a previously initialized RECEIVED run. During that one
outer execution, repairs resume only the exact recorded Coder session. The MVP cannot
restart an interrupted in-progress state: it records BLOCKED. DONE and BLOCKED remain
terminal and are not reactivated by this command. Preserve state/artifacts/QA, diagnose the
specific cause, verify any required prerequisite fix independently, and create a new
bounded run with the previous reason recorded. Never edit budgets/state or use `--last`.

Use a complete dedicated clone containing the reviewed dirty baseline, not a HEAD-only
clone or an unsupported `.git` worktree pointer. Do not run broad publication against a
delivery tree containing excluded/untracked user data whose source fingerprint cannot
round-trip. Preserve data and use the recorded isolated baseline plus trusted exact-path
integration after full acceptance; do not hide the mismatch by excluding more evidence.

The original dedicated Coder profile was explicitly authorized and aligned once, with its
0600 backup retained. Subsequent runs do not overwrite global profiles/config or request
that authorization again. See the recorded host-alignment backup and hash in the SD-1A
verification report. Development gate success does not establish real ASR/LLM quality or
real-video acceptance; those have their own recorded input, budget and artifact evidence.


## Current-contract semantic failure evidence

For semantic-v4-quality-v2, each failed V4 subject has a committed immutable JSON asset in
runs/gNNN/semantic-audit. The failed TaskAttempt diagnostic pointer names the committed
manifest under .attempts/<task_id>/<lease_token>/diagnostics. The pointer is attempt-owned;
it must not be replaced with a generation-relative path or a path from another lease.
The manifest links each failed subject asset ID, relative path and SHA-256. Diagnostic-preserving
cleanup retains the manifest; generation-owned subject evidence remains separately retained.

Inspect the recorded run/generation, validation and prompt identity, request fingerprint,
call IDs, initial/repair phases and available errors. More than one failed concurrent subject
must be represented. Available OpenAI business text parts are individually indexed; a response
with ambiguous cardinality fails instead of silently selecting its first output. Transport
headers and reasoning are excluded. Credentials are redacted, including inside JSON text.
Do not paste raw environment, headers or credentials into a report when investigating a failure.

A complete repair that exceeds the configured token budget records a repair_budget event,
its estimate and budget, and repair_call_executed=false; this is not an extra Provider call.
Initial call evidence remains. Successful siblings can reuse validated caches on a compatible
explicit retry/new generation, while a changed config/prompt/contract has a distinct identity.
Network retries, the single semantic repair and stage recovery remain separate concepts;
SD-3's broader scheduling/retry work is not delivered by this audit correction.

Read the immutable evidence rather than editing it or clearing caches to change the outcome.
Repository failure recording must leave Task/Stage/Run and TaskAttempt in their actual outcome;
an artifact alone does not prove that stage failure persistence completed. Follow the currently
documented CLI retry workflow; a proposed future resume command is not yet implemented.
This local engineering evidence does not establish real-provider or real-video content quality.

ADR038: for new quality-contract Responses failures, non-completed status takes priority
over refusal, then unexpected/ambiguous output, then ordinary Schema/domain failures.
Available business output and Schema errors are still retained in the attempt diagnostic.
These response failures do not grant a semantic repair; production Stage transient retry
policy is unchanged and remains separately addressed by SD-3. Use project-local Python
for SQLite inspection; the macOS system SQLite failed to read the actual fixture database.

ADR039: each business_output_parts record also carries its complete validation_errors.
Aggregate validation_errors includes output/content index prefixes. This diagnostics-only
validation does not choose an authoritative multipart result or grant another semantic repair.
Retain both per-part errors and raw redacted text when investigating a response-state failure.


## Accepted SD-1A artifact inspection

Formal195929 is DONE; see docs/verification/stable-delivery-sd1a-accepted-2026-09-12.md.
The test execution retains seven synthetic mini artifacts and a last-published immutable
manifest under apps/web/playwright-report/mini-lesson/<run UUID>. Correlate exact execution/
QA/source/toolchain,not a report copied from another run. Visual inspection is a separate
record; do not rewrite the product quality report. Setup's default sync omits optional
local-asr dependencies; preserve that installed extra when restoring a configured ASR host.
