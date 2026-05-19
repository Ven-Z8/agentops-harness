# AgentOps Harness Demo Script

## Setup

```bash
cd projects/agentops-harness
uv sync --extra dev
```

## 1. Scan A Repository

```bash
uv run --extra dev agentops scan --repo examples/sample_fastapi_app
```

Show that the harness detects Python, FastAPI, pytest, entrypoints, folders, and config files.

## 2. Generate A Plan

```bash
uv run --extra dev agentops plan --repo examples/sample_fastapi_app --task "Add request logging middleware"
```

Point out the structured plan, acceptance criteria, tests to run, and risk notes.

## 3. Run The Harness

```bash
uv run --extra dev agentops run --repo examples/sample_fastapi_app --task "Add request logging middleware"
```

Highlight the PR-style report:

- Files changed
- Tests run
- Risk score
- Review findings
- Follow-up tasks

## 4. Validate The Project

```bash
uv run --extra dev pytest -q
uv run --extra dev ruff check .
```

## 5. Try The API

```bash
uv run --extra dev uvicorn app.api:api --reload
```

In another terminal:

```bash
curl -X POST http://127.0.0.1:8000/runs \
  -H "Content-Type: application/json" \
  -d '{"repo_path":"examples/sample_fastapi_app","task":"Add request logging middleware"}'
```

Then fetch:

```bash
curl http://127.0.0.1:8000/runs/<run_id>/report
curl http://127.0.0.1:8000/runs/<run_id>/logs
```

## Talk Track

AgentOps Harness demonstrates the engineering layer around coding agents: typed workflow state, local repo analysis, test execution, review, risk scoring, and traceable reporting. It is not another chatbot; it is infrastructure for making AI-assisted software engineering measurable and safer.
