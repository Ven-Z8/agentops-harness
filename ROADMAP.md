# Roadmap — Jun 12 → 18, 2026

**North star:** the outer loop (AgentOps) *equips* the inner loop (OpenHands worker) with **domain capability packs** — `{ manifest, skills/*.md, tools, hooks }` loaded per repo/task — and the headline demo is a **real codebase migration** on a good repo, governed end-to-end and rendered transparently from the run artifacts.

The inner loop is **locked** (all 9 worker-harness components wired + verified live on `nl2sql-viz`; PRs #12/#14/#15 merged). These milestones carry that foundation into the outer loop and the migration finale.

**Status — Jun 15:** M1–M3 are **done** and the observability **Cockpit shipped** (#16 docs, #19 M2+M3, #18 Cockpit all merged to `main`). The outer→inner pack mechanism (M3) and the transparency surface (Cockpit) are both in place; the M2 fix was verified **end-to-end** (complex OpenHands run → outer Verification Stack `Accepted: True`, Evidence Guard clean). What remains is the payoff — author the migration pack (M4) and run the governed migration demo (M5) — **gated on the migration repo + domain resources coming from the owner's side.**

| # | Milestone | Due | Status |
|---|---|---|---|
| M1 | Inner loop locked + README + north-star | Jun 13 | ✅ done |
| M2 | Outer evidence fidelity: route-impact | Jun 14 | ✅ done (#19, verified e2e) |
| M3 | Capability-pack loader (outer → inner) | Jun 16 | ✅ done (#19) |
| — | Observability Cockpit (Phase 1 Run Inspector) | Jun 14 | ✅ shipped (#18) |
| M4 | Migration domain pack | Jun 17 | open — awaiting repo + resources |
| M5 | Final migration demo on a good repo | Jun 18 | open |

---

## M1 — Inner loop locked + README + north-star · due Jun 13

Declare the inner loop locked and make the repo communicate it.

- [x] Audit the harness architecture + 9 components against merged code (this session)
- [x] README: agent-loop + nine-components slides visible, **inner loop** section, 9-component coverage table, inner/outer boundary
- [x] README: *Where this is going* — domain capability packs + migration finale
- [x] ROADMAP.md (this file)
- [x] Lock-in artifact: architecture → code matrix — the README's 9-component coverage table *is* the slide→code matrix (slides `agent-loop.png` / `nine-components.png` → wired-via column)

## M2 — Outer evidence fidelity: route-impact · due Jun 14

So migration diffs get graded correctly. `changed_subgraph.impacted_routes` is built from the **pre-edit** graph, so worker-added routes are flagged as ungrounded by the Evidence Guard (reproduced 2/2 on `nl2sql-viz`).

- [x] Detect routes **added by the diff**, include them as impacted nodes (`ChangedSubgraphBuilder` re-parses post-edit changed files; `route_added_by_diff`)
- [x] Scope impacted_routes to diff-touched routes (stop over-including untouched ones) — scoped by `git diff -U0` line ranges
- [x] Re-run: Evidence Guard no longer false-flags a new route (covered by `tests/test_route_impact.py` + updated `test_graph_smoke`)
- Tracked: background task `task_f774a6fc`

## M3 — Capability-pack loader (outer → inner) · due Jun 16

The key new architectural piece. The outer loop assembles a pack and injects it into the inner OpenHands loop through existing seams.

- [x] Define the pack format: `manifest.yaml` (name, domain, version, skills/tools/hooks) + `skills/*.md` + `hooks.py` (`app/schemas/pack.py`; shipped `packs/example/`)
- [x] Outer-loop selector: `--pack` flag → `select_pack` (path or built-in name); auto-by-profile is a stubbed future hook (lands with M4)
- [x] Loader: skills → `AgentContext` system suffix, tools → `Tool` name list, hooks → `callbacks` (`app/core/packs/loader.py`; injected in `openhands_runner`)
- [x] Guardrail: pack tools must be in the terminal/file-only allowlist — `PackError` otherwise
- [x] Tests: `tests/test_capability_pack.py` — trivial pack loads end-to-end; `assemble_agent_inputs` proves skill/tools/hooks reach the agent

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

- **Observability Cockpit** — ✅ **Phase 1 (Run Inspector) shipped** (#18): in-repo vanilla-JS + SSE UI at `/cockpit` — run list, 5-phase governance ribbon, guard cards, raw-artifact browser, bundle download, and a **Worker loop** tab streaming the OpenHands `prompt→tool→observation` trajectory. **Still open:** dispatch console (POST a run + watch live), run history/trends, goals/intent-graph view. Folds into M5. (`agentops-observability-viewer-goal` memory.)
- **Product-Reviewer success-signal fidelity** — surfaced during M2 e2e: the Product Reviewer returned "0 of 2 signals met" even though the endpoint **and** its test were added — it doesn't yet credit M2-recognized routes (`impacted_routes`) or untracked new test files. Same *class* of gap as M2, but for the CEO/intent layer. Teach it to read `impacted_routes` + the on-disk test files.
- **Run-artifact retention / GC** — `task_9767cbb9` — keep-last-N / max-age + `agentops prune`; do before the Cockpit reads many run folders.
