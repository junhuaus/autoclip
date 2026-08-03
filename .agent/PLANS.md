# LiveClip ExecPlan rules

An ExecPlan is the durable execution contract for any complex LiveClip change. It is not a static task list. It must remain understandable to a new agent with only the repository and local toolchain available.

Every ExecPlan must be fully self-contained and continuously updated. It must describe the user-observable result, the relevant architecture and vocabulary, the exact code and document locations involved, and the constraints that must remain true. Do not rely on chat history.

Each plan contains:

- Purpose / Big Picture: what a user can do when the work is complete.
- Context and Orientation: current repository state, important modules, data paths, and dependencies.
- Scope and explicit non-goals for the current milestone; non-goals may defer but never silently delete Product Spec scope.
- Milestones and a checkbox progress list with timestamps for completed work.
- Work breakdown with file ownership and task dependencies.
- Concrete commands from the repository root, including expected observations and failure interpretation.
- Validation and acceptance criteria based on externally observable behavior and real artifacts.
- Idempotency, retry, crash recovery, cancellation, and rollback/re-run guidance.
- Surprises and Discoveries with short evidence.
- Decision Log with date, decision, alternatives, rationale, and consequences.
- Risks and Mitigations.
- Recovery Notes containing the first unambiguous next task.
- Outcomes and Retrospective after a milestone closes.

Progress is factual. Mark an item complete only after its acceptance evidence exists. Record partially completed work explicitly. When a command fails, retain the exact command, relevant error, and whether the failure is deterministic, environmental, or transient.

Plans use repository-relative paths and name the symbols or sections to change. They explain test fixtures and expected artifacts sufficiently that another agent can reproduce them. Avoid vague instructions such as “finish the backend” or “test everything.”

Before stopping a session:

1. Leave the worktree understandable and preserve user changes.
2. Run the strongest validation that currently applies.
3. Record successful and failed commands truthfully.
4. Update the Living ExecPlan and `STATUS.md` so they agree.
5. Record branch, last relevant commit, and worktree status.
6. State unverified work and the single next concrete task.
7. Include a copyable resume prompt in `STATUS.md`.

Milestone work is recoverable when rerunning a completed step is safe or its recovery behavior is documented. File existence alone never proves a cached stage succeeded; use state, fingerprints, hashes, and validation manifests.
