from __future__ import annotations

CURSOR_FILES: dict[str, str] = {
    ".cursor/commands/agentops-scan.md": """# AgentOps Scan

Profile the current repository with AgentOps Harness.

Run:

```bash
uv run --extra dev agentops scan --repo .
```

Use the scan output to understand language, framework, test commands, entrypoints,
and risk-sensitive areas before planning work.
""",
    ".cursor/commands/agentops-run.md": """# AgentOps Run

Run AgentOps Harness against the current repository and task.

Ask the user for the task if it is not explicit, then run:

```bash
uv run --extra dev agentops run --repo . --task "<engineering task>"
```

Treat the final report as the source of truth for validation, risk, reviewer
notes, and follow-up work.
""",
    ".cursor/commands/agentops-report.md": """# AgentOps Report

Fetch a saved AgentOps Harness report.

Ask for the run id if it is not provided, then run:

```bash
uv run --extra dev agentops report --run-id "<run id>"
```

Summarize only the report's findings. Do not invent test results or risk assessments.
""",
    ".cursor/commands/agentops-handoff.md": """# AgentOps Handoff

Prepare a handoff from Cursor to a coding agent plus AgentOps Harness validation.

Write a concise handoff with:

- Task
- Relevant files
- Constraints
- Acceptance criteria
- Tests to run
- Risk concerns

End with this validation command:

```bash
uv run --extra dev agentops run --repo . --task "<engineering task>"
```
""",
    ".cursor/rules/agentops-harness.mdc": """---
description: AgentOps Harness operating rules for Cursor
globs:
  - "**/*"
alwaysApply: true
---

# AgentOps Harness Cursor Rules

Cursor owns planning and review. AgentOps Harness owns independent repo
scanning, validation, risk scoring, run history, and PR-style reporting.

Use this role split:

- Cursor: clarify task, inspect code, draft plan, review AgentOps reports.
- Coding agent: implement changes and tests.
- AgentOps Harness: run `agentops scan`, `agentops run`, and `agentops report`.

Do not treat a chat answer as proof. Prefer a saved AgentOps run report with
test output, risk score, and reviewer findings.

Never ask Cursor to edit secrets, `.env` files, credentials, private keys,
auth/payment/security folders, or dependency files without explicitly calling
out the risk.
""",
}


GOOSE_RECIPE = """version: "1.0.0"
title: "AgentOps Harness Evaluator"
description: "Evaluate repository tasks with scan, test, review, risk, and PR-style reporting."

parameters:
  - key: task
    input_type: string
    requirement: required
    description: "Engineering task to evaluate"
  - key: repo_path
    input_type: string
    requirement: optional
    default: "."
    description: "Repository path to evaluate"

instructions: |
  You are using AgentOps Harness as the independent evaluator for a coding-agent workflow.

  Operating model:
  - Goose can inspect, plan, and coordinate.
  - AgentOps Harness is the validation and reporting layer.
  - Do not claim work is complete until AgentOps Harness has produced a report.

  First scan the repository:

  ```bash
  uv run --extra dev agentops scan --repo {{ repo_path }}
  ```

  Then run the harness:

  ```bash
  uv run --extra dev agentops run --repo {{ repo_path }} --task "{{ task }}"
  ```

  Use the final report's Tests run, Risk assessment, Reviewer notes, and
  Follow-up tasks as the source of truth.

prompt: |
  Evaluate this engineering task with AgentOps Harness:

  {{ task }}

  Repository: {{ repo_path }}

  Return a concise summary of the AgentOps Harness report. Include Risk
  assessment, tests run, and follow-up tasks.

activities:
  - "Run AgentOps Harness for {{ task }}"
  - "Scan repository with AgentOps Harness"
  - "Summarize latest AgentOps report"

settings:
  goose_provider: "openai"
  goose_model: "gpt-4o"
  temperature: 0.2
  max_turns: 50

extensions:
  - name: "agentops-harness"
    type: "stdio"
    command: "uv"
    args:
      - "run"
      - "--extra"
      - "dev"
      - "agentops-mcp"

retry:
  max_retries: 1
  timeout_seconds: 300
  checks:
    - type: shell
      command: "uv run --extra dev agentops scan --repo {{ repo_path }}"
"""
