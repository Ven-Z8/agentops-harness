# AgentOps Harness MCP Server

AgentOps Harness exposes a local MCP server so Goose and MCP-compatible clients can use the harness as a tool.

## Start The Server

```bash
uv run --extra dev agentops-mcp
```

The server uses stdio transport by default through the MCP Python SDK.

## Tools

### `agentops_scan`

Profiles a local repository.

Arguments:

- `repo_path`: repository path

### `agentops_run`

Runs the full LangGraph harness pipeline and persists a run record.

Arguments:

- `repo_path`: repository path
- `task`: engineering task
- `storage_path`: optional SQLite/JSONL run storage path

### `agentops_get_report`

Fetches a saved PR-style report.

Arguments:

- `run_id`: saved run id
- `storage_path`: optional SQLite/JSONL run storage path

### `agentops_list_runs`

Lists recent run records.

Arguments:

- `storage_path`: optional SQLite/JSONL run storage path
- `limit`: max number of runs

## Goose

Generate a Goose recipe that includes the MCP extension:

```bash
uv run --extra dev agentops integrations goose --repo .
```

This writes `.goose/recipes/agentops-harness.yaml`.

## OpenRouter

The MCP server uses the same provider config as the CLI. Mock mode is default. To enable real OpenRouter calls:

```bash
export AGENTOPS_LLM_PROVIDER=openrouter
export AGENTOPS_OPENROUTER_API_KEY=...
export AGENTOPS_OPENROUTER_MODEL=deepseek/deepseek-v4-flash
uv run --extra dev agentops providers status
uv run --extra dev agentops providers ping
```

Do not commit real `.env` files or API keys.
