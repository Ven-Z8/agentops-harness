---
schema_version: 1
decision_id: AO-DEC-UI-1
status: accepted
date: 2026-09-02T22:00:00Z
owners: [venkat]
task_ids: [AO-P6]
---

## Context

The harness needs an operator-facing UI to be a real, testable product. Two
surfaces exist today: (1) the web Cockpit (`web/`, 74 tests) — a run inspector
with replay, KPIs, mission rail, mounted by FastAPI at `/`; (2) the CLI + API.
Phase-2 work (task-spec kernel, positive contract, benchmark fan-out) has no
visual surface yet. The owner installed OpenDesign (design-agent platform
driving DSH over stdio) to design the UI, and the DSH task-board plugin
(`@linxin666/dsh-client-ui-task-board`) for cross-session execution tracking.

## Decision

1. **One UI, two modes** (owner-selected): evolve the existing Cockpit into the
   operator console (live runs, approvals, evidence inspection) and add a
   polished showcase mode (portfolio/demo), sharing one design system — rather
   than a fresh app or two separate apps.
2. **Operator first** (owner-selected): the first designed surfaces serve the
   owner driving real governed runs; external engineers and recruiters come
   after the daily-driver path works.
3. **Next-phase execution tracking lives on the DSH task board** (the
   `~/.dsh/task-board` ledger), backed by the repo's control-room roadmap as the
   authoritative scope source. Board cards reference roadmap IDs
   (AO-DEC-UI-1, AO-D03-01, …) and repo handoffs; the board never replaces the
   roadmap as scope authority.
4. **UI design proceeds through OpenDesign**: the design brief below is the
   initial prompt; the resulting DESIGN.md/screens get reviewed against the
   repo's honest-evidence policy before any implementation claim.

## Alternatives considered

- Fresh console app, Cockpit kept as showcase: rejected — splits the data
  client, duplicates run-model logic, abandons 74 passing tests.
- Cockpit stays read-only showcase, new operator app: rejected for the same
  reason; one codebase must carry both modes.
- Simple TASKS.md board: rejected — no execution binding; the DSH board runs
  tasks (pinned workspace/permission, cron), which is the point.
- GitHub Issues/Projects as board: deferred — external dependency; the
  control-room board-export already covers mirroring when wanted.

## Consequences

- The Cockpit gains operator capabilities (launch run, watch live, approve
  asks, task-spec submission) rather than being rewritten.
- Showcase mode is a view-layer concern over the same run data — no forked
  data paths.
- Board cards pin workspace + permission explicitly (never above
  `sessionDefaultPermission` without human confirmation, per the plugin's
  confirmation gate).
- Design work happens outside the repo (OpenDesign); only accepted artifacts
  (DESIGN.md, approved screens) get committed under `docs/design/`.

## Evidence

- Existing Cockpit: `web/` (74 tests passing), mounted via `app/api.py`
  (`mount_cockpit`), verified on the checkpoint commit `5230ed1`.
- Task-board plugin installed: `@linxin666/dsh-client-ui-task-board@0.3.12`
  ledger at `~/.dsh/task-board/ledger-v2.json` (schemaVersion 3, empty tasks).
- OpenDesign DSH runtime installed: `~/.dsh/profiles/open-design/` with
  `@open-design/dsh-runtime@0.1.0` (README: one short-lived
  `dsh --profile open-design --stdio` process per run).
- Full-suite checkpoint verification: 745 pytest passed / ruff clean / web 74.

## Revisit criteria

- If the Cockpit's vendor-free constraint (no framework) blocks live-updating
  operator views (SSE/websockets), revisit the stack decision with a decision
  record before introducing dependencies.
- If board execution proves flaky across sessions, fall back to control-room
  handoffs as the only tracker and record that here.
