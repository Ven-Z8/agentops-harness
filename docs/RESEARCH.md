# AgentOps Harness Research Notes

## Local Brain Findings

- The workspace Brain frames agentic engineering as a control plane above coding agents: plan, execute, validate, remember, and audit. This supports positioning AgentOps Harness as infrastructure for traceable software delivery rather than a chatbot or codegen wrapper.
- Existing Brain notes emphasize LangGraph checkpointing, audit trails, and deterministic validation as production requirements for agent workflows.
- Second Brain OS notes already establish a useful local pattern: OpenRouter as an opt-in provider behind a single LLM abstraction, with mock/default behavior for no-key demos.

## External Sources

- [Claude Code Harness](https://github.com/Chachamaru127/claude-code-harness) validates the workflow shape: plan, work, review, release, runtime guardrails, rerunnable validation, and evidence packs.
- [LangGraph Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api) supports explicit stateful node workflows. Nodes accept graph state and return updates; `START` and `END` define controlled execution boundaries.
- [LangGraph Persistence](https://docs.langchain.com/oss/python/langgraph/persistence) supports checkpointed threads and SQLite checkpointing for local workflows. For AgentOps Harness, run history and graph checkpointing should be separate: SQLite run records are product artifacts, while checkpointers are execution-state mechanics.
- [Goose](https://goose-docs.ai/) validates the local-first agent product surface: desktop/CLI/API, MCP extensions, multi-provider LLMs, subagents, and security controls.
- [OpenRouter Quickstart](https://openrouter.ai/docs/quickstart) confirms OpenRouter can be used through OpenAI-compatible chat completions and the OpenAI SDK with `base_url=https://openrouter.ai/api/v1`.

## Design Decisions

1. Keep the CLI and public run behavior stable while replacing the internal linear workflow with LangGraph.
2. Store run artifacts in SQLite for queryable history; keep LangGraph checkpointers as a later execution-resume enhancement.
3. Add API endpoints after the graph is stable: create run, fetch run, fetch report, fetch logs.
4. Keep mock mode as default. OpenRouter/OpenAI provider support is opt-in and should not be invoked by tests or demos unless env vars explicitly select it.
5. Do not build Streamlit yet. The API and persisted run artifacts are the foundation the dashboard should read from.

## Next Implementation Slice

```text
scan_repo -> create_plan -> collect_diff -> run_tests -> review_diff -> assess_risk -> write_report -> persist_run
```

This maps directly to LangGraph nodes and preserves the existing final report contract.
