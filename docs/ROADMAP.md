# AgentOps Harness Roadmap

## Phase 1: CLI/Core Vertical Slice

- [x] Project skeleton with uv, pytest, ruff, Docker, CI.
- [x] Repo scanner for Python/FastAPI repositories.
- [x] Deterministic planner for demo mode.
- [x] Git diff collector and changed-file tracking.
- [x] Test runner for pytest and ruff.
- [x] Reviewer and risk guard.
- [x] PR-style final report generator.
- [x] Local run history.
- [x] Sample FastAPI app and harness tests.
- [x] OpenAI-compatible provider abstraction for OpenRouter/OpenAI.
- [x] External-worker edit mode with post-edit validation.

## Phase 2: LangGraph Orchestration

- [x] Replace linear pipeline internals with LangGraph `StateGraph`.
- [x] Add typed graph state and execution trace events.
- [x] Route planner/reviewer/PR writer through `app/core/llm.py` when real providers are enabled.
- [x] Add optional external-worker node before diff collection.

## Phase 3: API And Dashboard

- [x] FastAPI endpoints for run creation, logs, report, and run retrieval.
- [x] SQLite run history.
- [ ] Streamlit dashboard for trace inspection.

## Phase 3.5: Portfolio Harness Positioning

- [x] Position AgentOps Harness as the flagship repo for agent harness engineering.
- [x] Add Cursor command/rule integration generator.
- [x] Add Goose recipe generator.
- [x] Add Evidence Guard for unsupported LLM report claims.
- [x] Add Report Quality Guard with deterministic fallback for malformed provider output.
- [x] Add provider fallback for malformed structured planning/review output.
- [ ] Add workload manifests for other portfolio repositories.
- [x] Add AgentOps MCP extension for Goose and MCP-compatible clients.
- [ ] Add benchmark comparison reports across multiple sample projects.
- [ ] Generate saved example reports committed under `docs/examples/`.

## Phase 4: Local Mac App

- [ ] Add `agentops serve` local API command.
- [ ] Build SwiftUI macOS shell for local-only runs.
- [ ] Visualize run timeline, risk, tests, diff, and evidence findings.
- [ ] Add 3D run graph once engine data is rich and stable.

## Phase 5: Packaging And Portfolio Polish

- [ ] Docker and docker-compose.
- [ ] GitHub Actions CI.
- [ ] Architecture docs, demo script, benchmark script, and resume bullets.
- [ ] Add Bandit security scan once dependency footprint settles.
