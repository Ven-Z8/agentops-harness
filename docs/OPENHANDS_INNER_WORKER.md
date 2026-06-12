# OpenHands Inner Worker

AgentOps Harness is the outer governance harness. OpenHands is the inner worker
harness. The integration lets AgentOps give OpenHands a structured worker packet,
let OpenHands run its own implementation loop, then let AgentOps collect the diff
and enforce the normal governance pipeline.

## Boundary

AgentOps owns:

- scan, recall, plan, and workspace preparation
- pre-dispatch permission checks
- worker prompt contract
- target repository and timeout
- stdout, stderr, exit code, duration, and worker artifacts
- final diff collection
- permission enforcement, tests, risk, evidence, product review, and verification

OpenHands owns:

- prompt to model loop
- file reads and edits inside the target repo
- terminal commands inside the worker loop
- local implementation attempts
- stopping once it completes, blocks, errors, or reaches SDK limits

AgentOps does not trust the worker's self-report. OpenHands may attempt tests, but
AgentOps reruns configured validation after the worker returns.

## Setup

OpenHands remains optional. Normal AgentOps tests and demos do not install it and
do not require provider credentials.

Install the optional worker dependencies:

```bash
uv sync --extra dev --extra openhands
```

Configure a model and one API key:

```bash
export OPENHANDS_MODEL=anthropic/claude-sonnet-4-5-20250929
export ANTHROPIC_API_KEY=...
```

The worker checks these environment variables:

- `OPENHANDS_MODEL`
- `OPENHANDS_MAX_ITERATIONS`
- `LLM_API_KEY`
- `ANTHROPIC_API_KEY`
- `OPENAI_API_KEY`

## Artifacts

When invoked from an AgentOps run, OpenHands worker artifacts are written under
the run directory:

```text
.agentops/runs/<run_id>/
|-- worker_prompt.md
|-- worker_stdout.log
|-- worker_stderr.log
|-- worker_loop_summary.json
|-- worker_result.json
|-- worker_scorecard.json
|-- openhands_events.jsonl
|-- openhands_state/
|-- diff.patch
|-- test_results.json
|-- risk_report.json
|-- permission_report.json
|-- evidence_report.json
|-- product_review.json
|-- verification_bundle.json
`-- run_record.json
```

`worker_loop_summary.json` records the observable inner-loop lifecycle:

```json
{
  "worker_type": "openhands",
  "loop_owner": "openhands_sdk",
  "agentops_role": "outer_governor",
  "status": "completed",
  "model": "anthropic/claude-sonnet-4-5-20250929",
  "tools_requested": ["terminal", "file_editor", "task_tracker", "grep", "glob", "task_tool_set"],
  "event_log_path": ".agentops/runs/<run_id>/openhands_events.jsonl",
  "observable_event_count": 12,
  "termination_reason": "completed"
}
```

The runner uses OpenHands SDK `Conversation` callbacks to persist observable
events as JSONL. It also configures a conversation persistence directory under
the run directory, so SDK-managed state can be inspected separately from
AgentOps-owned diff, test, risk, permission, evidence, and verification
artifacts.

## Status Mapping

The subprocess runner uses stable exit codes:

- `0`: completed
- `1`: run error
- `2`: usage error
- `3`: authentication missing
- `4`: SDK missing
- `5`: timeout handled by parent
- `6`: configuration error

The parent worker maps those to `ExternalEditResult.status`:

- `completed`
- `failed`
- `blocked`
- `timeout`
- `setup_missing`
- `auth_missing`
- `configuration_error`

Missing SDK and missing auth are classified cleanly so CI can run without
OpenHands installed and without provider keys. A bad config value (exit `6`,
e.g. a non-integer `OPENHANDS_MAX_ITERATIONS`) maps to `configuration_error` —
distinct from `setup_missing`, so the operator is not told to reinstall the SDK.

## Manual Tests

The target repo must be a git root so AgentOps can attribute the worker diff.
For the bundled sample app, prepare a temporary git repo first:

```bash
tmp_repo="$(mktemp -d)/sample_fastapi_app"
cp -R examples/sample_fastapi_app "$tmp_repo"
git -C "$tmp_repo" init -q
git -C "$tmp_repo" add .
git -C "$tmp_repo" commit -qm "initial sample app"
```

Setup missing:

```bash
uv run --extra dev agentops edit \
  --repo "$tmp_repo" \
  --task "Add request logging middleware" \
  --worker-type openhands
```

Expected without OpenHands extras: `setup_missing`, with a diagnostic explaining
that the OpenHands SDK is not installed.

Auth missing:

```bash
uv run --extra dev --extra openhands agentops edit \
  --repo "$tmp_repo" \
  --task "Add request logging middleware" \
  --worker-type openhands
```

Expected without an API key: `auth_missing`.

Successful run:

```bash
OPENHANDS_MODEL=anthropic/claude-sonnet-4-5-20250929 \
ANTHROPIC_API_KEY=... \
uv run --extra dev --extra openhands agentops edit \
  --repo "$tmp_repo" \
  --task "Add request logging middleware" \
  --worker-type openhands \
  --max-attempts 1
```

Expected: OpenHands edits the repo, AgentOps collects the diff, reruns tests,
classifies permissions and risk, checks evidence, runs product review, and writes
the verification bundle.

Sensitive path:

```bash
uv run --extra dev agentops edit \
  --repo "$tmp_repo" \
  --task "Add API key to .env for the app" \
  --worker-type openhands
```

Expected: pre-dispatch governance blocks the worker before OpenHands runs.

## Sub-agent delegation

The agent is given the OpenHands `task_tool_set` delegation tool plus the built-in
terminal-only archetypes (`bash-runner`, `code-explorer`, `general-purpose`). It can
spin up a focused sub-agent for a bounded sub-task and fold the result back into its
own loop. Archetypes are registered with `enable_browser=False`, so the
browser-dependent `web-researcher` is skipped and delegated sub-agents inherit only
terminal/file tools — the no-browser/network constraint holds through delegation.

## Limitations

- This integration does not add browser tools or network tools to OpenHands,
  including to delegated sub-agents.
- Event capture is limited to events surfaced through OpenHands SDK callbacks.
- AgentOps does not use OpenHands as a replacement for governance.
- AgentOps still performs final validation after every worker run.
