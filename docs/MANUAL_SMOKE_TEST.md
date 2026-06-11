# Manual Smoke Test — AgentOps Harness

A short by-hand checklist to validate the whole harness end-to-end (e.g. before a demo).
Each step has a command and a **pass criterion**. ~15 minutes.

## Before you start (gotchas that bite)

- **Keep `--storage` OUTSIDE the target repo.** Writing run history into the target dirties
  it and edit mode will refuse to run. Use `--storage /tmp/smoke/runs.db`.
- **Edit mode needs a clean target** — `git status` in the target must be empty (or pass `--allow-dirty`).
- **claude worker needs a key:** `source ~/.zprofile` first (sets `ANTHROPIC_API_KEY`). codex/opencode use their own auth.
- **`--workspace docker`** needs Docker running and the target's deps installable (`uv sync` must succeed).
- Run everything from the project root with `uv run --extra dev` (or `--extra openhands` for the OpenHands worker).

```bash
# one-time setup for the run
uv sync --extra dev
rm -rf /tmp/smoke && mkdir -p /tmp/smoke
cp -r examples/sample_fastapi_app /tmp/smoke/app && cd /tmp/smoke/app
cat > agentops.goals.yaml <<'YAML'
north_star: A small FastAPI service with health endpoints.
goals:
  - id: G1
    statement: Expose operational readiness.
    priority: now
    success_when: ["A /healthz endpoint is added.", "A test covers /healthz."]
    scope_out: ["Authentication or billing."]
YAML
git init -q && git add -A && git commit -qm init
cd -   # back to the harness project root
```

## 1. Unit suite is green
```bash
uv run --extra dev python -m pytest -q -m "not docker"
```
☐ **Pass:** `213 passed` (± a few), 0 failed. `ruff check .` → all checks passed.

## 2. Observe run + CEO product review (free, no edits)
```bash
uv run --extra dev agentops run --repo /tmp/smoke/app --goal G1 \
  --task "Add a /healthz endpoint with a test" --storage /tmp/smoke/runs.db
```
☐ **Pass:** report prints a `## Product Review` section with a verdict + cited findings;
`changed_files` empty; target repo still clean (`git -C /tmp/smoke/app status` → clean).

## 3. Evidence bundle exists
```bash
RID=$(ls /tmp/smoke/runs/); ls /tmp/smoke/runs/$RID
```
☐ **Pass:** ~16 files incl. `repo_graph.json`, `task_plan.yaml`, `product_review.json`,
`workspace_report.json`, `final_report.md`, `trace.jsonl`, `run_record.json`.

## 4. Real worker edit (governance + attribution)
```bash
source ~/.zprofile   # for the claude worker; codex/opencode skip this
uv run --extra dev agentops edit --repo /tmp/smoke/app --worker-type codex --goal G1 \
  --task "Add a GET /healthz endpoint returning {\"status\":\"ok\"} and a test" \
  --worker-timeout-seconds 180 --storage /tmp/smoke/runs.db
```
☐ **Pass:** worker edits land (`git -C /tmp/smoke/app diff` shows `/healthz` + a test);
`changed_files` lists only real files (no `__pycache__`). Try `--worker-type claude` and
`--worker-type opencode` too — each should make a real edit (claude needs the key).
*(reset the target between worker runs: `cd /tmp/smoke/app && git checkout . && git clean -fd && cd -`)*

## 5. Pre-dispatch enforcement (block before the worker runs)
```bash
cd /tmp/smoke/app && git checkout . && git clean -fd && cd -
uv run --extra dev agentops edit --repo /tmp/smoke/app \
  --worker-command "agentops-scripted-edit secrets.py 'leak'" \
  --task "touch a secret" --storage /tmp/smoke/runs.db
```
☐ **Pass:** run status **blocked**, the worker never ran, `secrets.py` does NOT exist in the target.

## 6. Revert-on-deny (undo a denied change the worker made)
```bash
uv run --extra dev agentops edit --repo /tmp/smoke/app \
  --worker-command "sh -c 'echo a > NOTES.md; echo leak > secrets.py'" \
  --task "write notes" --storage /tmp/smoke/runs.db
```
☐ **Pass:** `NOTES.md` exists (permitted), `secrets.py` does NOT (reverted); the report's
permission section lists `secrets.py` under enforced reverts.

## 7. Bounded retry loop
```bash
# (retry fires on a genuine test failure; an env failure must NOT retry)
# Observe the run log / final report: "attempts" should be 1 when validation can't run
# (missing deps), and >1 only when a test actually ran and failed.
```
☐ **Pass:** a missing-deps target shows `attempts: 1` (no pointless retry); `--max-attempts 2`
with a genuinely failing test shows `attempts: 2`.

## 8. Isolated Docker workspace — validation in a container (needs Docker)
```bash
# Docker validation is exposed on `run` (observe). It builds a container, uv-syncs
# the target, runs validation inside it, and fails fast on a broken env.
uv run --extra dev agentops run --repo /tmp/smoke/app --goal G1 \
  --workspace docker --task "Add /healthz" --storage /tmp/smoke/runs.db
```
☐ **Pass:** `workspace_report.ok` is true and validation ran in the container; a broken-deps
target instead fails fast with a clear `workspace_report` diagnostic (seconds, not a hang).
`docker ps -a` shows no leaked `agentops-ws-*` containers afterward.
*(Known gap: `agentops edit` has no `--workspace` flag — Docker-validation with a host worker
isn't reachable via the CLI yet; `edit --sandbox` jumps straight to full isolation. Follow-up.)*

## 9. Sandbox — worker runs in a throwaway container (needs Docker)
```bash
uv run --extra dev agentops edit --repo /tmp/smoke/app \
  --worker-command "sh -c 'echo a > NOTES.md; echo leak > secrets.py'" \
  --sandbox --task "write notes" --storage /tmp/smoke/runs.db
```
☐ **Pass:** `NOTES.md` reaches the host, `secrets.py` does NOT (physically prevented — it
existed only in the container). `--sandbox` implies Docker full-isolation; no `--workspace` needed.
*(Note: `--sandbox` with a built-in `--worker-type` is intentionally blocked — only
`--worker-command` is sandboxed today.)*

## 10. OpenHands worker (real SDK agent loop)
```bash
source ~/.zprofile
uv run --extra openhands agentops edit --repo /tmp/smoke/app --worker-type openhands \
  --task "Add a /healthz endpoint" --worker-timeout-seconds 200 --storage /tmp/smoke/runs.db
```
☐ **Pass:** a real OpenHands agent edits the repo; `edit_result` completed; changes attributed.

## 11. Surfaces (API + MCP)
```bash
uv run --extra dev uvicorn app.api:api --port 8099 &   # then:
curl -s -XPOST localhost:8099/runs -H 'Content-Type: application/json' \
  -d '{"repo_path":"/tmp/smoke/app","task":"Add /healthz"}' | head -c 200
uv run --extra dev agentops-mcp <<< ''   # starts the MCP stdio server (Ctrl-C to stop)
```
☐ **Pass:** `POST /runs` returns a run record JSON; `agentops-mcp` starts without error.

## Cleanup
```bash
rm -rf /tmp/smoke; docker rm -f $(docker ps -aq --filter "name=agentops-ws-") 2>/dev/null
```

---
**If any step fails, capture:** the command, the run id (`ls /tmp/smoke/runs`), and the
relevant artifact (`/tmp/smoke/runs/<id>/run_record.json`) — that's enough to diagnose.
