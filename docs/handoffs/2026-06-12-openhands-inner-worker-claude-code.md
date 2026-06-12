# Claude Code Handoff: OpenHands Inner Worker Follow-Up

Date: 2026-06-12
Branch target: `codex/openhands-inner-worker`
Repo: `Ven-Z8/agentops-harness`

## Current State

AgentOps now has a production-shaped OpenHands inner worker integration. The
implementation keeps AgentOps as the outer governance harness and OpenHands as
the governed inner implementation loop.

Implemented surfaces:

- `app/schemas/worker_loop.py`
- `app/core/workers/openhands_config.py`
- `app/core/workers/openhands_artifacts.py`
- `app/core/workers/openhands_runner.py`
- `app/core/workers/openhands_worker.py`
- `app/prompts/workers.py`
- `app/core/graph.py`
- `docs/OPENHANDS_INNER_WORKER.md`
- `examples/workloads/openhands_request_logging.yaml`
- OpenHands worker/config/artifact/runner/prompt tests

The worker remains optional. Default dev tests do not require the OpenHands SDK
or provider API keys.

## SDK Documentation Findings

Official docs and source were mirrored locally during the implementation pass:

- Docs index: `https://docs.openhands.dev/llms.txt`
- Downloaded docs: 194 Markdown pages, 45,586 lines
- `OpenHands/OpenHands` commit inspected:
  `b240031d27a3dbb0f005c13b05171b1ca7b363c9`
- `OpenHands/software-agent-sdk` commit inspected:
  `e3a2a4a2b1b85cd544ec9bc9b7a1d1e5e587a3c8`

Important SDK-specific correction already applied:

- `Conversation.run()` takes no max-iteration keyword in SDK v1.28.x.
- Max iterations belong on `Conversation(..., max_iteration_per_run=...)`.
- SDK-visible events are available through `Conversation(..., callbacks=[...])`.
- SDK persistence is configured through `Conversation(..., persistence_dir=...)`.

## Verification Already Run

These passed before this handoff file was added:

```bash
uv run --extra dev ruff check .
uv run --extra dev python -m pytest -q
env -u LLM_API_KEY -u ANTHROPIC_API_KEY -u OPENAI_API_KEY \
  UV_PROJECT_ENVIRONMENT=/tmp/agentops-harness-dev-no-openhands \
  uv run --extra dev python -m pytest \
  tests/test_openhands_runner_contract.py tests/test_openhands_worker.py -q
```

Observed results:

- `ruff`: all checks passed
- full pytest: `228 passed`
- clean dev-only OpenHands slice: `15 passed`

## What Claude Code Should Do Next

1. Review the OpenHands worker diff as a strict implementation reviewer.
   Focus on optional dependency boundaries, subprocess behavior, artifact
   persistence, status mapping, and prompt contract clarity.

2. Run a permanent real-worker smoke, not a temporary-directory smoke:

   ```bash
   tmp_repo="$(mktemp -d)/sample_fastapi_app"
   cp -R examples/sample_fastapi_app "$tmp_repo"
   git -C "$tmp_repo" init -q
   git -C "$tmp_repo" add .
   git -C "$tmp_repo" commit -qm "initial sample app"

   OPENHANDS_MODEL=anthropic/claude-sonnet-4-5-20250929 \
   ANTHROPIC_API_KEY=... \
   uv run --extra dev --extra openhands agentops edit \
     --repo "$tmp_repo" \
     --task "Add request logging middleware" \
     --worker-type openhands \
     --worker-timeout-seconds 600 \
     --max-attempts 1
   ```

3. Inspect the generated run directory and confirm these OpenHands artifacts are
   present:

   - `worker_prompt.md`
   - `worker_stdout.log`
   - `worker_stderr.log`
   - `worker_loop_summary.json`
   - `worker_result.json`
   - `worker_scorecard.json`
   - `openhands_events.jsonl`
   - `openhands_state/`

4. Verify AgentOps still owns final truth after the worker returns:

   - final `diff.patch` collected by AgentOps
   - permission report generated
   - tests rerun by AgentOps
   - risk report generated
   - evidence report generated
   - verification bundle generated

5. If the real run exposes SDK event payload issues, improve only the event
   serializer and tests. Do not make OpenHands a required dependency.

## Non-Negotiables

- Do not import OpenHands in the parent worker.
- Do not require provider keys in normal CI tests.
- Do not add browser/network tools to the OpenHands worker.
- Do not trust the worker self-report as final validation.
- Preserve AgentOps as the outer harness and OpenHands as the inner worker.
