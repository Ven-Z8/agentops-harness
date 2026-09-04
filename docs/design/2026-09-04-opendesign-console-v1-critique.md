# OpenDesign Console v1 — Critique (AO-DEC-UI-1 review)

Review of `docs/design/opendesign-console-v1/` against the repo's
honest-evidence policy and decision AO-DEC-UI-1 ("screens get reviewed
against the honest-evidence policy before any implementation claim").
Date: 2026-09-04. Reviewer: agentops session (post-wiring, live server).

## Verdict

**Accept with follow-ups.** The design system is genuinely good for this
product: fixed semantic color mapping, mono for every id/command/hash,
state colors that are never decorative. The screens were improved during
wiring (hardcoded gate evidence replaced by live states). The remaining
risk is not the design — it is the **curated/live boundary**: every surface
must say which it is, and two screens still blur it.

## What works (with evidence)

1. **Fixed semantic tokens enforce honesty.** `--ok/--fail/--warn/--info`
   are mapped to outcomes (completed/failed/blocked-inconclusive/info), not
   vibes. Blocked and interrupted share amber `--warn` — the UI cannot paint
   an interrupted run green, which is exactly AO-D01-02 made visual.
2. **runs-list is fully live.** KPI strip + table render from `/runs` +
   `/runs/kpis`; loading → data | empty | error are all real states; the
   error state names the missing server instead of faking content.
3. **run-detail hydration is evidence-driven.** With `?id=`, every panel
   (status chip, KPI cells, stage rail, tests, risk, replay) renders from
   `/runs/{id}` + `/runs/{id}/events`; the stage rail lights only where
   execution_logs evidence exists. The replay scrubber scrubs real worker
   events (150 on the dmr flagship).
4. **new-run composer now proves the contract for real** (this session):
   the negative-contract gate calls `/runs/spec/pre-dispatch`, renders real
   probe exit codes, and fail-closes visibly (blocked/inconclusive/error
   states). The dispatch CTA stays disabled until the gate opens.
5. **Demo honesty on run-detail without `?id=`**: it keeps the curated dmr
   case study — which IS that run's real worker evidence — and the live
   path supersedes it whenever an id is present.

## What does not work yet (concrete, prioritized)

1. **task-specs.html is 100% curated.** It presents the pisek/dmr specs as
   a library with no data source. Fix: a `/specs` endpoint (or reading the
   task-spec files the CLI already consumes) and the same loading/empty/error
   treatment as runs-list. Until then the screen should carry a visible
   "design case study" marker.
2. **index.html launch cards overstate the live surface.** The hero reads
   as if every screen is a working console. runs-list/run-detail/new-run now
   are; task-specs is not. One line per card saying live vs case study would
   keep the promise honest.
3. **Dispatch is a handoff, not an action.** The composer proves the
   contract and then hands the operator a CLI command. That is the honest
   v1 (worker credentials stay out of the console), but "launch" on the
   board card means the follow-up slice: `POST /runs/spec/dispatch` with a
   background governed run + live SSE progress (the cockpit SSE patterns
   exist to reuse). Until then the button copy should remain
   dispatch-via-CLI, which it does.
4. **No live-update on runs-list** (fetch-on-load; refresh to see new runs).
   Acceptable for solo-operator use; SSE or poll is the follow-up.
5. **KPI floats.** `/runs/kpis` returns `7.0` for counts. Cosmetic; the
   console renders them fine, but integer counts are cleaner contract-wise.
6. **Replay kind map is lossy by design** (T/O/F/K/S/M/C/E). Fine for
   scrubbing; the run-detail "Evidence" tab (not built) is where full
   output_tails belong.

## Design-system notes for v2

- The 12px floor and tabular-nums discipline hold across screens — keep it;
  it is what makes dense evidence legible.
- `chip` variants: runs-list defines chip-ok/chip-fail/chip-warn; new-run
  only has ok/warn/muted (no fail). Unify the chip set in a shared
  `console.css` when the screens graduate into `web/` (per AO-DEC-UI-1
  graduation plan).
- Sidebar worker-status rows (openhands sdk version, codex/claude opt-in)
  are static on every screen. They should read provider status from the API
  (`/providers`-style endpoint exists in the CLI) or be marked as identity,
  not status.

## Scope decision recorded

Console v1 does not hold worker credentials and does not start long-running
dispatches; the governed CLI remains the dispatch authority. Live in-console
dispatch + approve/confirm (board card AO-UI-01 remainder) is a distinct
follow-up slice, not a v1 gap.
