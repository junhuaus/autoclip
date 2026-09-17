# ADR-026: Bounded loop-engineering control plane

Status: accepted for the `liveclip-v2/loop-engineering` development branch

Date: 2026-08-23

## Context

An autonomous developer must turn a requirement into a plan, code, independent review, tests, real
command evidence and a final quality decision. Codex conversations alone are not durable project
state: a new CLI invocation starts a new session unless an exact session is resumed, and blindly
resuming the most recent session can attach the wrong context. Agent prose also cannot be trusted as
execution authority or proof that a program works.

The LiveClip product runtime already has a fixed six-stage media Pipeline. A general development
orchestrator must not enter that dependency graph or weaken its command, path, credential and media
trust boundaries.

## Decision

Add a separate control plane under `tools/loop_engineering` with these rules:

1. Durable JSON state and append-only events below ignored `.loop/runs` are canonical. Chat memory is
   only a role-local optimization.
2. Planner, Reviewer, Tester and Gateway use new read-only Codex sessions. Coder alone uses
   `workspace-write` in an isolated candidate workspace; repair turns resume only the exact stored
   Coder session ID. `--last` is forbidden. Assurance runs against a separate snapshot, and the trusted
   outer process publishes it to the delivery worktree only after every gate passes.
3. Named Codex profile layers choose model/reasoning defaults. The orchestrator still supplies explicit
   sandbox, approval, repository root, stdin prompt and JSON Schema arguments. Mutable base user
   configuration and rules are ignored; external app/browser/computer/plugin/MCP-dependent Skill and
   multi-agent surfaces are explicitly disabled and compatibility-checked by Doctor.
4. Every role returns a strict structured artifact. The outer process independently validates the JSON
   against the checked-in Schema, requires the initial Coder session ID and rejects mutation of Git HEAD,
   prior run evidence or QA logs. Prompt/Schema/profile/config/Agent/control-plane bytes are frozen before
   the writable role starts. Transcripts, requirements and role output remain untrusted data.
5. The Runner accepts a checked-in command ID, resolves it to a fixed argv array and invokes it with
   `shell=False` inside a deny-default macOS sandbox. The child gets a private HOME, no external network,
   localhost-only browser connectivity and only fixed temporary/browser-output write roots. Git, source,
   policy, `.loop` and QA evidence are unwritable. A model cannot add a path, shell fragment, environment
   secret or command. Before Coder, Python/Web dependencies and Make/lock inputs are copied into a sealed
   user-private cache outside the writable workspace. Runner executes a retained source snapshot with a
   copied trusted Web tree and trusted Python environment, never ignored dependencies from Coder space.
6. Agent and Runner subprocesses are process-group bounded; output is streamed into a fixed-size
   redacted tail rather than captured without limit. Credential-bearing environment variables and
   credential agents are removed. Runner evidence records exit status, Git HEAD and a worktree
   fingerprint before and after execution. The execution snapshot independently recomputes to that same
   fingerprint. Requests and results append to `qa/pipeline.jsonl` and `qa/test-report.md`; Gateway
   correlates their exact ID/command/run, retained execution tree, toolchain and immutable Runner log.
   After a deterministic precheck of those canonical records, the trusted outer process gives the
   read-only Gateway an ignored assurance-local inspection bundle with only this run's bounded logs,
   QA request/reports and command results. It hashes the bundle and rejects any role mutation; the
   final deterministic Gateway still verifies the original records. This makes current test components
   inspectable without granting the role write access or changing the sealed source fingerprint.
7. The final deterministic Gateway requires all configured gates, one fresh evidence fingerprint, no
   P0/P1 review finding, and semantic Gateway PASS. Semantic PASS cannot waive facts.
8. Review/test failures route to Coder; requirement or architecture defects route to Planner. Explicit
   Coder/Tester `BLOCKED`, external errors or browser-host execution errors route directly to `blocked`.
   Plan and code repair budgets are finite.

```text
requirement → planner → coder → reviewer → tester → runner → gateway → done
                 ^        ^         │          │        │
                 │        └─────────┴──────────┘        │
                 └──────────── architecture rework ─────┘
```

## Consequences

Runs are reproducible and inspectable without relying on chat history. Review independence and Runner
authority are explicit. The loop can continue without a human for ordinary failures but stops honestly
when retries are exhausted or authority/external state is missing.

The MVP runs in one dedicated branch rather than creating one Git worktree per task. Therefore one loop
run at a time is allowed and the operator must start from an understood branch. Worktree isolation,
lease-based concurrent scheduling and automatic checkpoint commits are later milestones.

## Rejected alternatives

- One long Codex conversation for every role: hides independence and makes stale context authoritative.
- A stateless CLI call with the complete repository context copied on every turn: wasteful and still
  lacks durable workflow state.
- `codex resume --last`: races unrelated sessions and is not a stable task identity.
- Letting Tester or Gateway execute suggested shell: turns untrusted model output into code execution.
- Letting an LLM alone decide success: cannot prove exit codes, artifact freshness or test coverage.
- Adding the loop to `src/liveclip`: would confuse product Pipeline and developer orchestration.
