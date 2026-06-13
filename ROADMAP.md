# Roadmap — Jun 12 → 18, 2026

**North star:** the outer loop (AgentOps) *equips* the inner loop (OpenHands worker) with **domain capability packs** — `{ manifest, skills/*.md, tools, hooks }` loaded per repo/task — and the headline demo is a **real codebase migration** on a good repo, governed end-to-end and rendered transparently from the run artifacts.

The inner loop is **locked** (all 9 worker-harness components wired + verified live on `nl2sql-viz`; PRs #12/#14/#15 merged). These milestones carry that foundation into the outer loop and the migration finale.

| # | Milestone | Due | Status |
|---|---|---|---|
| M1 | Inner loop locked + README + north-star | Jun 13 | active |
| M2 | Outer evidence fidelity: route-impact | Jun 14 | open |
| M3 | Capability-pack loader (outer → inner) | Jun 16 | open |
| M4 | Migration domain pack | Jun 17 | open |
| M5 | Final migration demo on a good repo | Jun 18 | open |

---

## M1 — Inner loop locked + README + north-star · due Jun 13

Declare the inner loop locked and make the repo communicate it.

- [x] Audit slide-04 architecture + 9 components against merged code (this session)
- [ ] README: slide-04 visible, **inner loop** section, 9-component coverage table, inner/outer boundary
- [ ] README: *Where this is going* — domain capability packs + migration finale
- [ ] ROADMAP.md (this file)
- [ ] Lock-in artifact: slide-04 → code matrix (workspace-artifacts)

## M2 — Outer evidence fidelity: route-impact · due Jun 14

So migration diffs get graded correctly. `changed_subgraph.impacted_routes` is built from the **pre-edit** graph, so worker-added routes are flagged as ungrounded by the Evidence Guard (reproduced 2/2 on `nl2sql-viz`).

- [ ] Detect routes **added by the diff**, include them as impacted nodes
- [ ] Scope impacted_routes to diff-touched routes (stop over-including untouched ones)
- [ ] Re-run: Evidence Guard no longer false-flags a new route; Verification Stack `Accepted` flips
- Tracked: background task `task_f774a6fc`

## M3 — Capability-pack loader (outer → inner) · due Jun 16

The key new architectural piece. The outer loop assembles a pack and injects it into the inner OpenHands loop through existing seams.

- [ ] Define the pack format: `manifest` (domain, version, tool/skill/hook list) + `skills/*.md` + `tools` + `hooks`
- [ ] Outer-loop selector: choose a pack by repo profile / task / `--pack` flag
- [ ] Loader: skills → `AgentContext`, tools → `Tool` registry, hooks → `callbacks` / pre-tool gate
- [ ] Guardrail: pack tools stay terminal/file-only (no browser/network)
- [ ] Tests: a trivial pack loads end-to-end and its tool/skill appears in the agent

## M4 — Migration domain pack · due Jun 17

Author the first real pack.

- [ ] Pick the migration (e.g. a framework/API/version migration on a chosen "good repo")
- [ ] Skills: the migration playbook (step-by-step, what to change, how to verify)
- [ ] Tools: any migration-specific helpers (codemod-style, still terminal/file-only)
- [ ] Hooks: guardrails specific to the migration (e.g. block edits outside target paths)
- [ ] Eval harness: run **with vs without** the pack to show the pack earns its keep

## M5 — Final migration demo on a good repo · due Jun 18

The payoff.

- [ ] Run the governed migration end-to-end: outer loads the pack → inner executes → outer validates
- [ ] Transparency: render the loop trajectory + guard verdicts from run artifacts (folds in the viewer goal)
- [ ] Capture evidence bundle + a written walkthrough as the portfolio artifact

---

## Supporting tasks (slot in as time allows, not standalone milestones)

- **Run-artifact retention / GC** — `task_9767cbb9` — keep-last-N / max-age + `agentops prune`; do before the viewer reads many run folders.
- **Observability viewer** — `agentops-observability-viewer-goal` memory — folds into M5 (the demo needs it to *show* the loop behaving).
