# AgentOps Harness Architecture

AgentOps Harness is a local-first coding-agent orchestration framework. The MVP is deterministic and mock-provider-first so the demo works without API keys.

```text
CLI/API
  |
  v
LangGraph Run Pipeline
  |
  +--> Repo Scanner  --> RepoProfile
  +--> Planner       --> ImplementationPlan
  +--> Edit Runner   --> ExternalEditResult (optional)
  +--> Git Utils     --> changed files + diff summary
  +--> Test Runner   --> command results
  +--> Reviewer      --> structured findings
  +--> Risk Guard    --> score + block decision
  +--> PR Writer     --> final Markdown report
  +--> Report Quality Guard --> malformed-output fallback
  +--> Evidence Guard --> unsupported-claim detection
  |
  v
SQLite or JSONL Run Storage
```

## Design Choices

- **Local-first:** All repo analysis and validation happen on local paths.
- **Typed state:** Every stage exchanges Pydantic models.
- **Safe by default:** Destructive commands and sensitive file edits are blocked or scored heavily.
- **No-key demo:** Mock/deterministic agents are the default.
- **Provider-ready:** `app/core/llm.py` supports mock, OpenRouter, and direct OpenAI behind one interface.

## LangGraph Workflow

The current `run_harness` pipeline is implemented as a LangGraph `StateGraph`:

```text
scan_repo -> create_plan -> run_external_worker -> collect_diff -> run_tests -> review_diff -> assess_risk -> write_report -> check_report_quality -> check_evidence
```

Each node returns a partial state update. `run_external_worker` is a no-op in observe mode and runs only when a caller provides an explicit worker command. The final state is converted into a `RunRecord` and persisted as a product artifact.

## Observe Mode And Edit Mode

- **Observe mode:** `agentops run` validates the current repository state without making edits.
- **Edit mode:** `agentops edit` runs a caller-provided external worker command, then validates the diff it leaves behind.

Edit mode keeps AgentOps Harness as the control plane. Cursor, Claude Code, Codex, Goose, or another local command can perform the edit, while AgentOps owns attribution, validation, risk, evidence, and reporting. The target repo must be clean by default so the post-worker diff is attributable to that worker.

## Worker handoff packets

`app/core/handoff.py` renders deterministic Markdown and JSON payloads from an existing `RunRecord`, or drafts a planner+scanner-only packet before any external worker runs. This keeps Cursor/Codex sessions focused on edits instead of repeating planning context.

CLI: `agentops handoff export`, `agentops handoff draft`; API: `GET /runs/{run_id}/handoff?format=markdown|json`.

## Workload manifests

YAML specs under `examples/workloads/` describe portfolio scenarios plus optional gates (`max_risk_score`, `required_commands`). `app/core/workload.py` parses manifests and evaluates them against completed runs (`agentops workload validate`, `agentops workload check`).

## Storage Boundary

Run records are stored separately from LangGraph checkpoints:

- `.db`, `.sqlite`, `.sqlite3` paths use SQLite.
- Other paths use JSONL for simple file-based demos.
- Future LangGraph checkpointing can be added without changing the run artifact schema.

## Evidence Guard

## Report Quality Guard

The Report Quality Guard checks provider-written reports before evidence checks run.

It rejects reports that:

- are too short to be useful
- contain placeholder/image artifacts
- omit required PR sections

When quality fails, Harness discards the provider report, regenerates a deterministic local report, and appends a `Report Quality Guard` section explaining the fallback. This protects the user from malformed provider output while preserving the run.

## Evidence Guard

The Evidence Guard cross-checks generated PR reports against the actual run record.

It flags unsupported claims such as:

- report says files were added but `changed_files=[]`
- report says tests were added but no test files changed
- report says tests passed when validation failed
- analysis-only runs that read like implementation PRs

When unsupported claims are found, the final report receives an `Evidence Guard` section so the user can see what the LLM invented.

## Provider Boundary

```text
Planner / Reviewer / PR Writer
  |
  v
LLMClient protocol
  |
  +--> MockLLMClient
  +--> OpenAICompatibleLLMClient
          +--> OpenAI API
          +--> OpenRouter API via https://openrouter.ai/api/v1
```

The provider is selected with `AGENTOPS_LLM_PROVIDER`. Real providers require explicit API keys and are never used by default.

When `AGENTOPS_LLM_PROVIDER=mock`, Planner, Reviewer, and PR Writer use deterministic local logic. When `openrouter` or `openai` is enabled, the graph injects the OpenAI-compatible client into those agents.

Provider failures are contained at graph-node boundaries. If structured planning, review, or report generation fails, the graph records a `provider_fallback:*` execution log entry and reruns that node with the deterministic local agent. The harness should keep producing usable evidence even when the model misbehaves.
