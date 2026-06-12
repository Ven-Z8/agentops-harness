# Architecture North Star — Two Decks, Two Layers, Two Semantics

> The organizing principle for AgentOps Harness. Refines
> [THREE_LAYER_FOUNDATION.md](THREE_LAYER_FOUNDATION.md) and
> [reference/code-as-agent-harness/what-is-a-harness.md](reference/code-as-agent-harness/what-is-a-harness.md)
> by mapping our two reference decks onto the two layers we actually build, and
> separating the work accordingly.

## 1. The core mapping

Our two explainer decks are not two views of one thing — they describe two
different layers, and we work them **separately**.

| Deck | Describes | Our layer | We… |
|---|---|---|---|
| **harness-project** | the **inner loop** — what a capable coding agent *is* and how it performs | **Worker** | **adopt** (don't rebuild) |
| **code-as-harness** (the paper) | how to **govern, verify, evolve** the closed loop | **AgentOps** (control plane) | **build** |

**harness-project slides 6–17 are entirely worker anatomy:** the architecture around
the loop (6), Claude Code's five layers (7), the **nine components** (8), each
component — while-loop, context, tools, sub-agents, persistence, hooks, permissions
(9–13), memory + skills (14–15), the **OpenHands SDK** (16), and the five performance
levers (17). None of these are AgentOps. They are the worker.

**code-as-harness is the control-plane thesis:** executable · inspectable · stateful ·
governed; plan-execute-verify; semantic verification (§5.2.2); self-evolution (§3.5);
convergence and the open problems (§5.2). That is what AgentOps adds *around* a worker.

## 2. The boundary rule (the 10% nuance that matters)

**The nine components are the *worker's*.** AgentOps implements none of them — no agent
loop, no context compaction, no sub-agents. **OpenHands (or codex/claude) provides the
nine components.** Therefore:

> We do **not build** the inner loop. We **adopt** it. We build the control plane.

This makes the two layers different *kinds* of work:
- **Worker layer = an integration problem** — run a real, capable agent loop in isolation.
- **AgentOps layer = a construction problem** — governance, verification, evidence, evolution.

## 3. Two semantics (the deep split)

"Semantic" matters in both decks — but means a different thing in each layer. Keeping
them straight is what stops us from building the wrong thing.

| | Inner loop (worker) | Outer loop (AgentOps) |
|---|---|---|
| **Kind** | semantic **retrieval** | semantic **verification** |
| **Question** | "find the right code" | "did the change *mean* what was intended?" |
| **Source** | slide-17 lever #1; Cursor semantic search (+12.5% accuracy, trained on agent traces) | code-as-harness slide 20 / §5.2.2 — "a green test is not the full specification" |
| **Owner** | the worker (OpenHands/Cursor provide it) — **not our job** | **AgentOps — our frontier** |

The Product Reviewer is our first reach at semantic verification; its deterministic
heuristics are brittle (on nl2sql-viz it flagged correct work as `incomplete`). The
**LLM-judged product-reviewer path *is* semantic verification** — that is where AgentOps
earns its keep, not in retrieval.

References: Cursor [semantic search](https://cursor.com/blog/semsearch) ·
[continually improving the agent harness](https://cursor.com/blog/continually-improving-agent-harness).

## 4. The inner/outer loop dynamic

The decks describe two loops (transcript: *"an inner loop that works on the task and an
outer loop that looks how can we continue"*):

- **Inner loop** = the worker's `prompt → model → action → feedback`, 50–200×. Slide 5.
- **Outer loop** = AgentOps's `plan → worker → enforce → validate → retry`, plus the
  evolution loop (§3.5). Cursor's "improve the harness from agent traces" is this outer
  loop improving the inner loop's retrieval — a concrete example of the two interacting.

## 5. Where we stand vs. the frontier (honest)

**Worker layer:** four workers run (codex/opencode/claude verified; OpenHands integrated)
— **but only on the host.** No real agent loop runs *inside the isolated Docker
workspace* yet; the sandbox is proven only with non-looping shell commands. Slide 16's
"agent loop in a DockerWorkspace" is **not yet realized.**

**AgentOps layer:** governance is real and enforced (pre-dispatch block · revert-on-deny ·
sandbox · bounded retry); evidence trail, convergence benchmark, conflict auditor, and a
*deterministic* product reviewer exist. **Semantic verification (§5.2.2) is the gap** —
the LLM reviewer path and an evidence bundle that declares scope/confidence per check.

## 6. Why real tasks force both layers up

A small task (`add /healthz`) exercises a trivial inner loop and a shallow check. A real
task (a feature, a migration) needs:
- **Worker:** a genuine long-horizon loop, **in isolation** (OpenHands in a DockerWorkspace).
- **AgentOps:** **semantic** verification over the whole trajectory — "does it serve the
  goal, with what's unverified made explicit," not "tests pass."

Small tasks never stress either. The roadmap must.

## 7. The work model

Advance the two layers **separately**, each against its own deck:

- **Worker track (harness-project deck):** adopt + isolate. Next: OpenHands on a
  DockerWorkspace so a real agent loop runs **and is tested** inside the sandbox.
- **AgentOps track (code-as-harness deck):** build governance + **semantic verification**.
  Next: the LLM product-reviewer path + scoped/confident evidence (§5.2.2).

Same nesting as before (CEO → AgentOps → Worker); this doc just fixes *which deck owns
which layer* and *what kind of work each demands*, so we stop conflating "make the agent
better" (worker, adopted) with "govern and verify the loop" (AgentOps, built).
