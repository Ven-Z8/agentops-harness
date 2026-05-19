# Local Mac App Plan

AgentOps Harness can become a local-only macOS app, but the app should sit on top of the harness engine rather than replace it.

## Recommended Shape

```text
SwiftUI macOS App
  |
  +--> Local FastAPI server or direct CLI process calls
  |
  v
AgentOps Harness Engine
  scan -> plan -> diff -> tests -> review -> risk -> report -> evidence guard
  |
  v
SQLite run history
```

## Why Not Build The Mac App First?

The star value is the harness engine: evidence grounding, real test output, risk scoring, run history, and model/provider routing. A beautiful 3D UI becomes impressive only when it is visualizing trustworthy data.

## MVP Mac App Features

- Select local repo folder.
- Enter engineering task.
- Start run.
- Watch timeline: scan, plan, diff, tests, review, risk, report, evidence guard.
- View actual evidence:
  - changed files
  - git diff summary
  - test output
  - risk score
  - unsupported LLM claims
- Export PR report markdown.
- Re-run previous task.

## Later 3D UI Ideas

- 3D workflow graph where nodes light up during execution.
- Risk heatmap as a spatial surface over changed files.
- Evidence claim cards floating beside the generated report.
- Timeline replay of an agent run.

## Implementation Options

### Option A: SwiftUI Shell + Local API

Run FastAPI locally and have the SwiftUI app call `http://127.0.0.1:<port>`.

Best for:

- Fast iteration
- Keeping Python harness untouched
- Future web/dashboard reuse

### Option B: SwiftUI Shell + CLI Process

The app launches `agentops` commands and reads SQLite results.

Best for:

- Fully local no-server feel
- Simple packaging

### Option C: Native Rewrite

Rewrite harness logic in Swift.

Not recommended. It would weaken the Python/LangGraph/agent-platform story and slow down portfolio progress.

## Recommendation

Build Option A when the engine stabilizes:

1. Keep AgentOps Harness as Python CLI/API/MCP.
2. Add a local daemon command: `agentops serve`.
3. Build a SwiftUI macOS client that talks to the local API.
4. Add the 3D visualization once run data is rich enough.
