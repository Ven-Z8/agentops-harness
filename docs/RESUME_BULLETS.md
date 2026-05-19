# Resume Bullets

- Built AgentOps Harness, a local-first AI coding-agent orchestration framework that converts engineering tasks into structured plan → implement → test → review → risk assessment workflows.
- Designed LangGraph-based multi-agent architecture with Repo Scanner, Planner, Test Runner, Reviewer, Risk Guard, and PR Writer agents using typed state management.
- Implemented repository analysis, git diff tracking, pytest/ruff execution, security guardrails, SQLite run history, FastAPI run APIs, and structured PR-style reporting.
- Added evaluation metrics for test pass rate, risk score, changed-file impact, execution latency, and review findings to measure coding-agent reliability.
- Built Evidence Guard to detect unsupported LLM claims by grounding generated PR reports against git diffs, changed files, test results, and execution traces.
- Added Report Quality Guard to reject malformed provider output and fall back to deterministic PR reporting.
- Added OpenRouter/OpenAI-compatible provider abstraction while preserving deterministic mock mode for reproducible demos and tests.
- Built CLI/API interfaces to demonstrate traceable AI-assisted software engineering workflows.
