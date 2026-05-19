# AgentOps Harness Portfolio Factory

AgentOps Harness is the command center for building the portfolio. The point is not
to clone every new agent framework. The point is to absorb the durable patterns and
turn them into a local harness that makes each portfolio project measurable.

## Decision

Use AgentOps Harness as the portfolio factory:

```text
portfolio goal
  -> workload manifest
  -> repo scan
  -> plan / worker handoff
  -> validation commands
  -> risk and evidence guards
  -> portfolio episode package
```

The output is a viewer-facing episode: what was attempted, which repo was touched,
which checks ran, what changed, what the risk score was, and which guardrails fired.

## Source Signals

| Source | What to learn | What not to do tonight |
|---|---|---|
| Cursor agent harness | Dynamic context, keep rate, per-model tool formats, error taxonomy, harness A/B testing | Do not build a Cursor clone |
| Anthropic long-running app harness | Planner -> generator -> evaluator, real browser/test verification, sprinted generation | Do not start a heavyweight multi-agent lab |
| HKUDS/OpenHarness | Tools, skills, permissions, hooks, memory, subagents, dry-run discipline | Do not replace our local harness runtime |
| HKUDS/OpenSpace | Skill evolution, task pattern reuse, token savings, quality monitoring | Do not add cloud/community skill sync yet |
| tinyhumansai/openhuman | Local memory tree, Obsidian wiki, compression before LLM calls | Keep this in Second Brain OS, not AgentOps core |
| gsd-build/get-shit-done | Spec-driven milestones, file-based planning, context reset through focused tasks | Do not install another workflow layer over the repo |
| LangChain Deep Agents | Planning, filesystem state, subagents, human approval, sandboxed long-running tasks | Use as implementation inspiration only |

## Tonight Slice

Build the smallest credible proof that the harness can package portfolio work:

1. Define a real workload manifest for a portfolio repo.
2. Run or reuse a harness run for that workload.
3. Emit a portfolio episode package from the persisted run.
4. Keep tests and lint passing.

## Episode Package

An episode must answer:

- What portfolio project did this support?
- What task was attempted?
- Which worker mode ran: observe-only or external worker?
- What validation commands ran?
- What files changed?
- What was the risk score?
- Did workload gates pass?
- Did evidence/report guards flag anything?
- What final report did the harness produce?

This is the bridge between engineering work and public showcase proof.

## Next Layers

- Add error taxonomy counters for tool failures: `InvalidArguments`,
  `UnexpectedEnvironment`, `ProviderError`, `Timeout`, `UserAborted`, `Unknown`.
- Add keep-rate tracking after accepted edits survive later runs.
- Add model/tool profile metadata so patch-based and string-replace workers can be compared.
- Let Second Brain OS feed dynamic context into the plan/handoff stage.
- Add a weekly harness retrospective that scans run logs and opens backlog items for regressions.
