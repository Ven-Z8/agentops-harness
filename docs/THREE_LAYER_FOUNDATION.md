# Flagship Foundation — The Three-Layer Harness

> Architecture decision, 2026-06-10. The foundation of the AgentOps Harness flagship.
> Reconciles the harness-deep-dive transcript, both explainer decks, and the
> "Code as the Agent Harness" paper. See [reference/code-as-agent-harness/what-is-a-harness.md](reference/code-as-agent-harness/what-is-a-harness.md).

## The decision

A harness is everything *outside* a loop that makes it finish a task — and the
pattern **nests**. The flagship is three nested layers the CEO/CTO owns, with the
model rented in exactly one box:

```
┌─ CEO LAYER ───────────────────────────────────────────────┐
│  holds GOALS + PRODUCT. starts the loop, closes it.        │  ← the gap; build this
│  governs WHAT is done and WHETHER it served the goal       │
├─ AGENTOPS LAYER (control harness) ─────────────────────────┤
│  governs HOW: plan → assign → validate → guard → evidence  │  ← largely built
├─ WORKER LAYER ─────────────────────────────────────────────┤
│  does the editing: swappable inner-loop workers            │  ← built (codex/claude/opencode)
│       └─ MODEL (rented, swappable) ─ answers once          │
└────────────────────────────────────────────────────────────┘
```

- **AgentOps governs *how* work is done** — correctly, safely, with evidence. Built.
- **The CEO layer governs *what* is done and *whether it served the goal*** — product
  alignment, prioritization, ship-or-reassign. This is the missing half. The human
  CEO/CTO lives here; the Product Reviewer and "suggested next work" are CEO-layer
  components (not AgentOps guards).

## Two owned deterministic graphs — the moat

Each layer starts *grounded* because of a deterministic, inspectable, locally-owned
primitive. The model is rented; the graphs are yours.

```
Worker layer  ← grounded by →  repo graph    (structure of the CODE)
CEO layer     ← grounded by →  intent graph  (structure of the PURPOSE)
AgentOps      = the translator: intent → governed run → evidence → back to the CEO
```

The repo graph (already built — 1,714 nodes on contextiq, 0 LLM tokens) keeps the
worker from blindly exploring code. The **intent graph** is its symmetric twin for the
CEO layer: it keeps the loop grounded in *what you're trying to build*, and gives the
Product Reviewer ground truth to judge alignment against.

## The intent graph — CEO-authored, v1 scope

The CEO authors a structured goal model. Principle: **goals are durable; features are
emergent.** The graph holds durable goals; the per-loop assignment supplies the
emergent feature (mirrors repo-graph-durable vs plan-transient).

**v1 schema (locked):**

```
NORTH STAR   — one sentence: what this product is, for whom
NOT_THIS     — what this product is explicitly NOT (catches fundamental scope violations)
CONSTRAINTS  — non-negotiables (stack, principles, what we never do)

GOAL  G1  "<the why>"
  rationale     — why this matters
  priority      — now | next | later
  success_when  — [ discrete, individually-checkable signals ]   ← each citable met/unmet
  scope_out     — [ what this goal explicitly excludes ]
```

`success_when` is a list of **discrete checkable signals** (not a paragraph) so the
Product Reviewer can report "criterion 2 of 3 met" with a citation even without a
feature layer.

## How v1 grounds the loop

- **Initiate** — CEO picks a goal; AgentOps gets a task pre-grounded with `rationale`
  (why), `success_when` (target), `scope_out` (constraints). The worker packet inherits
  product intent, not just code structure.
- **Review** (Product Reviewer) — judges the diff against `success_when` (completeness),
  `scope_out` / `NOT_THIS` (drift, value/overbuilt), `priority` (right-thing-now).
- **Assign next** — unmet `success_when` + `next`-priority goals are the suggestions.
- A run's `plan.acceptance_criteria` is the **child** of a goal's `success_when`:
  intent flows down to a run; evidence flows back up to the CEO.

**Four Product Reviewer lenses grounded by v1:** goal-alignment ✅, prioritization ✅,
value/overbuilt ✅, completeness ⚠️ (judged at goal level + per-loop criteria; sharper
once features exist).

## Explicitly deferred / out of scope

- **Feature layer** (goals → features → done_when) and **cross-loop feature tracking**
  ("F1 is 2 of 3 runs done") — clean post-event v2.
- **Token economics** — out of scope entirely (dropped, not deferred).
- **Safe self-mutation** of the harness (paper §5.2.3) — evolution.py only *proposes*;
  applying changes with regression-guards is the moonshot frontier.

## Why this is the code-as-harness line

Two owned deterministic graphs (code + intent) with a governed loop between them is the
paper's serious-harness rubric drawn at three layers: **Executable** (real diffs/tests),
**Inspectable** (both graphs + evidence trail), **Stateful** (intent graph + run history
+ memory), **Governed** (CEO intent + AgentOps guards). The moat is not one model — it
is the two graphs and the governed loop, local and owned.
