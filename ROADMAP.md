# Roadmap — current arc: trust + the issue flagship

**North star (v0.1, approved 2026-08-28):** AgentOps becomes a research control
plane that can *independently govern and evaluate* an agent experiment, preserve
reproducible evidence, and make trustworthy promotion decisions — while its first
flagship path stays concrete: **solve real GitHub issues on real open-source
repositories, governed end-to-end, with a patch and evidence bundle as the output.**

The full 14-day research design lives in
`archive/pre-dsh-checkpoint/agentops-codex-handover/docs/research/14-day-run/research-control-plane-design.md`
(archived pre-checkpoint, local-only) and the control-room copy in-repo at
`coordination/roadmap/14-day-plan.{yaml,md}`.
Dates are treated as **ordering, not deadlines** — the calendar expired; the phase
sequence is what matters.

## Status — Sep 2, 2026 (main, post DSH checkpoint)

**Phase 1 trust work (AO-D01/D02) — landed, test-first, red→green evidence in commits:**

| Task | Status | Evidence |
|---|---|---|
| AO-D01-01 ambient dotenv isolation | ✅ fixed | `1b0d1ac` — Settings no longer auto-loads CWD `.env`; litellm's import-time `load_dotenv()` neutralized in tests via `LITELLM_MODE`; hermeticity tripwire added to CI |
| AO-D01-02 truthful terminal statuses | ✅ fixed | `4112d42` — failed required validation ⇒ `status="failed"`, never `"completed"`; one suite test that silently relied on the bug repaired honestly |
| AO-D01-03 unknown kinds fail closed | ✅ fixed | `b8e65fc` — `--worker-type banana` blocks with `unknown_worker_type` instead of silently running no worker |
| LICENSE + CI hardening | ✅ done | `636de2c` — MIT + pyproject license field; uv v6 + cache, 30-min timeout, web suite in CI, no-`.env` guard |

**The flagship — governed GitHub-issue runs — first implementation landed:**

| Task | Status | Evidence |
|---|---|---|
| `agentops issue view/solve` + `app/core/issues.py` | ✅ built | `a0b823c` — fetch (gh) → isolated per-issue clone on `agentops/issue-N` branch → composed task with scope guidance → governed run → patch + evidence bundle; 10 tests incl. 2 end-to-end governed runs (one green, one fail-closed) |
| Live demo target | ✅ selected | `piskoviste/pisek#683` — real `good first issue` on a real Python OSS repo (GPL-3.0, unittest suite, active maintainer) |
| Live run #1 | ✅ failed *honestly* | Run `0debbbbf…` reported `status=failed` with an empty diff — evidence bundle pinpointed the deprecated `--full-auto` codex flag as root cause. **The trust fix caught a bug in the flagship's own first version.** |
| Worker command fix | ✅ landed | `6fc9c3c` — `codex exec -s workspace-write` |
| Live run #2 | 🔄 in progress | fresh workspace, fixed command — patch + evidence being generated |

## What remains for the v0.1 arc (phase-gated, in order)

1. **Finish the live issue demo** (this branch): patch lands on the issue branch,
   validation passes, evidence bundle captured; write the walkthrough as the
   portfolio artifact (`docs/dsh/` + README section).
2. **PR the flagship demo upstream** (optional but high-signal): open a PR to
   pisek from `agentops/issue-683` with the evidence bundle linked.
3. **Phase 2 — experiment kernel + DeepEval seam** (14-day Days 3–5):
   `ExperimentSpec` / `ExecutionProvider` / `EvaluationProvider` contracts so
   the issue-run becomes a *benchmark* — same task, multiple workers/packs,
   normalized metrics, split-aware comparison. The issue path built today is
   the coding-agent benchmark's execution provider.
4. **Control Room merge decision**: `codex/project-control-room` (93 commits)
   is now unblocked (`gh` re-authenticated). Re-run its suites, merge or
   tag-and-park. Keep it as a *tool* (validator, handoffs, board export),
   never a gate in front of product work.
5. **Old M4/M5 migration-pack finale**: now folds into the issue flagship —
   the "domain capability pack" proves itself by equipping a worker to solve
   an issue class, measured with-vs-without by the Phase 2 kernel.

## Standing discipline

- Process work never sits in front of unblocked product work.
- Every behavior change lands test-first with red→green evidence in the commit.
- No README/report claim exceeds demonstrated evidence.
- Missing evidence is `inconclusive`, never an inferred pass.

## Historical milestones (Jun 12–18 arc — all merged to main)

- ✅ M1 inner loop locked (9/9 worker-harness components, live-verified)
- ✅ M2 outer evidence fidelity (route-impact; verified e2e)
- ✅ M3 capability-pack loader (outer equips inner)
- ✅ Cockpit Phase 1 (Run Inspector) + 3D showcase (recorded governed migration)
- M4 migration domain pack → superseded by the issue flagship (see above)
- M5 final demo → the live pisek run is the new finale
