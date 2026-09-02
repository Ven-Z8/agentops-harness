# AgentOps universal agent protocol

Start with [the Project Control Room](coordination/README.md). These instructions
apply to every coding harness unless the user's current request says otherwise.

## Precedence

1. The user's current request.
2. This repository-local `AGENTS.md`.
3. Approved product and architecture decisions.
4. Current repository code, tests, CI, packaging, and generated evidence.
5. Attached or historical handover material.

### Before work

1. Read `AGENTS.md` and [coordination/README.md](coordination/README.md).
2. Read `coordination/PROJECT.md`, `coordination/CURRENT.md`, and the task's GitHub issue or local roadmap record.
3. Run `uv run python scripts/project_control.py validate`.
4. Confirm the task identifier, dependencies, acceptance criteria, authority, and allowed scope.
5. Inspect relevant decisions and the latest handoff for the task.
6. Confirm the worktree and preserve unrelated changes.

### During work

1. Use the stable task ID in the branch, commits, evidence, and handoff.
2. Work test-first for behavior changes.
3. Record scope-changing decisions rather than hiding them in chat history.
4. Treat missing or invalid required evidence as inconclusive, never passed.
5. Do not update generated snapshots manually.

### At handoff

1. Run task-specific verification and record exact commands and results.
2. Write a structured handoff with completed, remaining, blocked, and risk information.
3. Link commits, changed files, decisions, and available evidence.
4. Refresh generated local state.
5. Update GitHub workflow state only when authorized and authenticated; otherwise request the update explicitly in the handoff.
