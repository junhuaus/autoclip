# Claude Code repository entry point

Follow `AGENTS.md`; it is the repository-wide operating contract. This handoff
branch starts from clean `main` checkpoint
`ee20d7544574ddad22b7c019ce1ed26485612a63`.

## Required reading

Read in this order before complex work:

1. `AGENTS.md`
2. `docs/PRODUCT_SPEC.md`
3. `docs/SOLUTION.md`
4. `.agent/PLANS.md`
5. `docs/exec-plans/liveclip-v1.md`
6. `STATUS.md`

For v0.2 work, also read `docs/PRODUCT_SPEC_V0.2.md` and
`docs/exec-plans/liveclip-v0.2.md`; v0.1 remains the compatibility baseline.
Before Agent-v2 or developer-control-plane work, read
`docs/exec-plans/liveclip-v2-loop-engineering.md`,
`loop-engineering.yaml`, and
`docs/exec-plans/liveclip-agent-runtime-v2.md`.

`STATUS.md` is the concise current snapshot.
`docs/exec-plans/liveclip-agent-runtime-v2.md` is the sole authoritative,
comprehensive Living ExecPlan for Agent v2. Preserve the accepted v1
compatibility path and dual-profile path; do not replace or weaken either
without explicit authority.

## Operating boundaries

- Maintain one writer in the delivery worktree. The main agent owns shared
  schemas, migrations, dependency locks, Solution/ADR, ExecPlan, STATUS, and
  integration.
- Under `tools/loop_engineering`, Planner, Reviewer, Tester, and Gateway are
  fresh read-only roles. Only the isolated Coder writes, and only its recorded
  session may be resumed. The deterministic Runner executes checked-in
  allowlisted argv; the trusted outer process alone publishes accepted work.
- Never use `--last` and never run `resume_liveclip.sh`.
- Keep evidence categories distinct: deterministic validation proves only its
  checked gates; rendering plus human editorial/audio review is a separate
  acceptance activity; real model inference requires explicit authority and
  must not be inferred from either category.
- `input/`, `data/models/`, `data/evaluations/`, and `data/deliveries/` are
  ignored local-only assets. Never force-add, commit, log, or delete them.
- Never place credentials or authentication bytes/metadata in files, logs,
  prompts, receipts, or commits.
- For multi-step work, keep `STATUS.md` and the authoritative Living ExecPlan
  current, preserving historical evidence and explicit recovery boundaries.

Start by verifying the branch, HEAD, upstream, worktree, applicable contracts,
and authorization boundary before making changes.
