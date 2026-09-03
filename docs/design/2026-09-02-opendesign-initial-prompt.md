# OpenDesign initial prompt — AgentOps Operator Console

> Paste the block below into OpenDesign (it drives this DSH harness through the
> open-design profile). It follows the design-brief skill's I-Lang protocol so
> the agent parses every dimension explicitly; the body adds the real domain
> surfaces so the generated screens carry actual content, not placeholders.

---

[PLAN:@DESIGN|type=operator_console]
  |palette=monochrome_dark
  |accent=signal_green
  |typography=inter
  |display=space_grotesk
  |layout=app_shell_sidebar
  |mood=mission_control_honest_engineering
  |density=compact_data_dense
  |exclude=gradients,parallax,stock_illustrations,gamification
  |responsive=desktop_first_min_1280

Product: **AgentOps Operator Console** — the working UI for a local-first agent
governance harness. This is a REAL product with a real backend already running;
you are designing the screen set the operator (a solo engineer, Venkat) uses
daily to launch, watch, and judge governed AI coding runs.

## What the product actually does (use this as the content, no placeholders)

A *run* is a governed attempt to resolve a real GitHub issue on a real
open-source repo. Each run produces a patch + an evidence bundle. A run has:
status (completed / failed / blocked — never faked), attempts, risk score
(0–100), changed files, test results (commands + exit codes), an evidence
report (grounded / ungrounded claims), a verification bundle, permission
enforcements, and a full event log. The core brand promise is **honest
evidence**: the UI must make truth legible — a failed run is displayed as a
first-class outcome, never hidden or spun.

Key flows to design:

1. **Runs list (home)** — live+stored runs; KPIs (runs, pass, risk); a "live"
   indicator; risk badge per run; honest status chips (completed=green,
   failed=red, blocked=amber).
2. **Run detail (the heart)** — pipeline stage timeline (plan → dispatch →
   enforce → validate → retry → report) with the current stage lit; test
   results table with exit codes; evidence findings with citations; the
   produced patch (diff view); token usage.
3. **New governed run** — pick a real GitHub issue (owner/repo/number), choose
   worker (OpenHands / codex / claude), optionally attach a **task spec**
   (SWE-bench-style contract: pinned commit, FAIL_TO_PASS / PASS_TO_PASS
   tests); a "negative-contract gate" pre-check panel shows the bug being
   proven reproducible before dispatch.
4. **Task-spec library** — saved task-spec cards (repo, pinned commit, test
   lists, environment identity) ready to fire.
5. **Showcase mode toggle** — the same data, presentation grade: big type,
   one hero run, replay scrubber, for demos/portfolio. A view mode, not a
   separate app.

## Hard requirements

- Status colors are semantic and never decorative: green=completed,
  red=failed, amber=blocked/inconclusive. An "inconclusive" state exists and
  is visually distinct from failure (evidence missing ≠ evidence failed).
- Every claim on screen traces to evidence: test rows link to logs, findings
  link to citations, risk badge links to its factor list.
- Monospace for all code, test ids, commit hashes, commands.
- The operator trusts this UI to judge a run in under 10 seconds.
- Accessibility: contrast AA minimum; the console may be read for long
  stretches.

## Deliverables requested

1. `DESIGN.md` (design-brief skill output) for this console.
2. Screen set: runs list, run detail, new-run composer, task-spec library
   (4 screens minimum) — single-file HTML prototypes each, desktop ≥1280px.
3. A critique pass against your `craft/` rulebooks (state-coverage: empty /
   loading / error states for every region; anti-AI-slop; laws-of-ux).

After the first pass I will iterate in conversation with real run data from
the repo (`.agentops/runs/`) as the content source.
