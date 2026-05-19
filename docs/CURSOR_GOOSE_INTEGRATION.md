# Cursor And Goose Integration

AgentOps Harness should not try to become Cursor or Goose. The stronger portfolio story is:

> Cursor and Goose are agent surfaces. AgentOps Harness is the independent control plane that evaluates, scores, and reports what those agents do.

## Research Takeaways

### Claude Code Harness

Claude Code Harness uses a disciplined role split:

- Cursor can plan, review, manage tasks, and create handoffs.
- Claude Code owns implementation, tests, and debugging.
- Shared files such as `Plans.md` keep both tools aligned.
- Runtime guardrails, review commands, and rerunnable validation make the workflow trustworthy.

The useful pattern for AgentOps Harness is not copying its commands. The useful pattern is a **multi-agent operating contract** where one tool plans, another implements, and a harness validates.

### Goose

Goose is useful because it is local-first, MCP-native, recipe-driven, and multi-provider. Recipes can package instructions, prompts, parameters, retry checks, and tool expectations. That makes Goose a good workflow surface for AgentOps Harness.

## Recommended Architecture

```text
Cursor / Goose / Claude Code / Codex
        |
        v
Engineering task + repo path
        |
        v
AgentOps Harness
  scan -> plan -> diff -> tests -> review -> risk -> report
        |
        v
SQLite run history + PR-style report
```

## Cursor Integration

Install into a repo:

```bash
uv run --extra dev agentops integrations cursor --repo .
```

This writes:

- `.cursor/commands/agentops-scan.md`
- `.cursor/commands/agentops-run.md`
- `.cursor/commands/agentops-report.md`
- `.cursor/commands/agentops-handoff.md`
- `.cursor/rules/agentops-harness.mdc`

Suggested Cursor role:

- Clarify requirements.
- Draft implementation plans.
- Generate handoffs.
- Review AgentOps reports.
- Avoid claiming completion without a saved AgentOps run.

## Goose Integration

Generate a Goose recipe:

```bash
uv run --extra dev agentops integrations goose --repo .
```

This writes:

- `.goose/recipes/agentops-harness.yaml`

Suggested Goose role:

- Coordinate local workflows.
- Use recipes to run repeatable evaluation.
- Summarize AgentOps Harness reports.
- Later, call AgentOps Harness through an MCP extension.

## Next Step: MCP Extension

AgentOps Harness now includes an MCP server exposing:

- `agentops_scan(repo_path)`
- `agentops_run(repo_path, task)`
- `agentops_get_report(run_id)`
- `agentops_list_runs(limit)`

That lets Goose, Claude Desktop, Cursor-compatible MCP clients, and future agent runtimes use AgentOps Harness directly as a tool.

Run it with:

```bash
uv run --extra dev agentops-mcp
```

## Why This Matters

This makes AgentOps Harness the portfolio umbrella:

- Cursor can be the planning UI.
- Goose can be the open-source local agent runtime.
- Claude Code/Codex can be implementers.
- AgentOps Harness becomes the evaluator, safety layer, and evidence generator.
