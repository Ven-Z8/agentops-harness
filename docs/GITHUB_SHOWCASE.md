# GitHub Showcase Strategy

AgentOps Harness should be the flagship repository in the portfolio. The message is:

> I build agent harnesses: orchestration, evaluation, safety, run history, and developer-productivity control planes for AI coding agents.

## How This Repo Should Present You

- **Role signal:** Agent Harness Specialist, AI Platform Engineer, Developer Productivity AI Engineer.
- **Main proof:** A local-first framework that turns coding-agent work into traceable plan → test → review → risk → report runs.
- **Differentiator:** This is not a chatbot. It is infrastructure around coding agents.
- **Hiring story:** Engineering teams need safe, measurable ways to use AI agents in real repositories. AgentOps Harness demonstrates that layer.

## Repository Pinning

Pin AgentOps Harness first. Then pin 4-5 projects that can become workloads evaluated by the harness:

| Repo | How AgentOps Harness Frames It |
|---|---|
| ContextForge | Context-engineering workload for planning, testing, and risk scoring. |
| AgentOrchestra | Multi-agent orchestration workload and comparison point. |
| EvalEngine | Evaluation metrics engine that can plug into harness reports. |
| MCPGuard | Safety/guardrail workload for security-focused agent runs. |
| Second Brain OS | Research and knowledge-ingestion workload for agentic workflows. |

## README Narrative

Lead with a concrete engineering problem:

> AI coding agents can generate code, but engineering teams still need orchestration, validation, risk controls, audit trails, and PR-ready reports. AgentOps Harness provides that control plane.

Then show:

- Architecture diagram.
- CLI demo.
- API demo.
- LangGraph workflow.
- SQLite run history.
- Risk scoring.
- OpenRouter/OpenAI-compatible provider boundary.
- Sample run report.

## Recruiter/Engineer Skim Path

1. Read the top hook.
2. See the architecture.
3. Run the demo command.
4. Open a generated report.
5. Inspect tests.
6. See roadmap toward dashboard, eval packs, and repository benchmark suite.

## Future Showcase Upgrade

Add `examples/workloads/` with small scenario manifests:

```yaml
name: request-logging-fastapi
repo: examples/sample_fastapi_app
task: Add request logging middleware with tests
expected:
  max_risk_score: 35
  required_commands:
    - python -m pytest -q
```

This turns the repo into both a harness and an evaluation suite for the rest of the portfolio.

## Cursor And Goose Angle

AgentOps Harness should integrate with Cursor and Goose as clients:

- Cursor commands/rules make Cursor a planning and review surface.
- Goose recipes make Goose a local orchestration surface.
- A future MCP extension should expose AgentOps Harness as a reusable validation tool.

The message: Harness does not compete with Cursor or Goose. It makes them safer and more measurable.
