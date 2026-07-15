# 3D Cockpit Portfolio Showcase Design

**Status:** Approved for implementation

**Date:** July 13, 2026

**Primary use case:** Governed Migration

**Secondary use case:** Guardrail Intercept

## 1. Objective

Turn the existing read-only AgentOps Cockpit into a portfolio-grade explanation of
the harness architecture and a real governed run.

The Cockpit will use a purposeful Three.js stage to explain two relationships:

1. The nested harness architecture: intent, AgentOps control, worker loop, and repo.
2. The run lifecycle: Plan, Equip, Work, Guard, and Prove.

The 3D stage is a projection of persisted run state. It does not calculate verdicts,
interpret evidence, or invent demo progress. Normal HTML remains the authoritative
surface for evidence, controls, text, and accessibility.

## 2. Success Criteria

The first portfolio milestone is complete when:

- `make showcase` imports a committed golden run into normal AgentOps storage,
  starts the FastAPI application, and opens the Governed Migration mission.
- The showcase runs without an API key or external network access.
- The run is visibly and persistently labeled `Recorded`.
- The 3D stage shows the four harness layers and five run stages using data from the
  selected run.
- Selecting a stage focuses the corresponding layer and opens supporting evidence.
- The proof rail exposes tests, plan scope, risk, evidence grounding, and final
  verification without relying on worker self-report.
- Capability-pack name, version, skills, resolved tools, hooks, and manifest digest
  are present in the run provenance and visible in the Cockpit.
- Every displayed claim can be traced to the run record or a bundled artifact.
- The same run remains fully inspectable when WebGL or animation is unavailable.
- Existing Cockpit routes and non-showcase runs continue to work.

## 3. Scope

### Phase 1: Governed Migration

The first connected mission is a real, recorded OpenHands run against a bundled,
multi-file Python migration fixture. The target migration is Pydantic v1 to v2 so
the demo has precise success criteria, meaningful tests, and enough blast radius to
exercise planning, capability injection, worker activity, validation, and evidence.

The mission tells one five-stage story:

| Stage | Question answered | Primary evidence |
|---|---|---|
| Plan | What was understood before the model acted? | repo graph, intent goal, plan contract |
| Equip | What capability was injected into the worker? | pack provenance, skills, resolved tools |
| Work | What did the worker actually do? | OpenHands event log, diff, changed files |
| Guard | What did AgentOps enforce and verify? | tests, attempts, risk, permissions, reverts |
| Prove | Why should the result be trusted? | evidence guard, product review, verification bundle |

### Phase 2: Guardrail Intercept

The second mission reuses the same scene, state model, proof rail, and error
contract. It focuses the Guard stage and demonstrates a denied or reverted
out-of-scope edit with a complete evidence trail.

Phase 2 does not introduce a second UI architecture.

### Explicit Non-Goals

- Browser-launched agent execution or a dispatch console.
- React, React Three Fiber, or a frontend build pipeline.
- A cloud-hosted or multi-user Cockpit.
- Java or Spring migration support for the first showcase.
- Additional LLM providers or coding-worker adapters.
- Free-form scene editing, unrestricted orbit controls, or decorative 3D objects
  that do not encode harness state.

## 4. Visual Direction

The approved direction is the **Layered Tactical Cockpit**.

### 4.1 Spatial architecture

Four translucent depth planes communicate responsibility:

1. Intent Graph
2. AgentOps Control
3. Worker Loop
4. Repo Graph

The planes are not separate pages. They stay visible as architectural context while
the selected run stage changes focus.

### 4.2 Tactical runway

A five-node perspective runway crosses the planes:

`Plan -> Equip -> Work -> Guard -> Prove`

Nodes use the normalized states `pending`, `active`, `pass`, `warn`, `blocked`, and
`unavailable`. Color, glow, and motion have the same semantic meaning throughout
the Cockpit.

### 4.3 Readable evidence surfaces

The following remain normal DOM elements:

- Mission and run navigation.
- Recorded/live/reconnecting mode badge.
- Proof rail and final verdict.
- Worker telemetry and selected-stage detail.
- Plan, diff, tests, worker, governance, product, graph, report, and artifact views.
- Replay controls and bundle download.

The canvas is `aria-hidden`; equivalent stage state and controls are exposed in the
DOM.

## 5. Runtime Architecture

The backend remains the source of truth. The frontend normalizes each run once and
feeds two renderers.

```text
FastAPI + CockpitReader
  |-- GET /cockpit/api/runs
  |-- GET /cockpit/api/runs/{id}
  |-- GET /cockpit/api/runs/{id}/stream
  |-- GET /cockpit/api/runs/{id}/worker/stream
  |-- GET /cockpit/api/runs/{id}/artifacts/{name}
  `-- GET /cockpit/api/runs/{id}/bundle.zip
             |
             v
data-client.js -> run-model.js -> CockpitViewModel
                                      |          |
                                      v          v
                              Three.js stage   DOM panels
```

Three.js never fetches data directly. It receives a `CockpitViewModel` and emits
only selection events such as `stageSelected("guard")`.

### 5.1 Frontend modules

The current single-file frontend will be divided along stable responsibilities:

- `web/app.js`: boot, selection state, lifecycle coordination, and render scheduling.
- `web/data-client.js`: fetch helpers, EventSource ownership, reconnect policy, and
  stream cleanup.
- `web/run-model.js`: pure conversion from run detail and event state to
  `CockpitViewModel`.
- `web/mission-config.js`: curated mission metadata and run selection rules. Mission
  metadata changes labels and initial focus; it cannot override run verdicts.
- `web/scene/three-stage.js`: scene, camera, geometry, lighting, picking, resizing,
  disposal, and view-model rendering.
- `web/scene/transitions.js`: state colors, camera presets, interpolation, and
  reduced-motion behavior.
- `web/ui/panels.js`: run/mission rail, proof cards, telemetry, deep-dive tabs, and
  fallback stage ribbon.
- `web/styles.css`: design tokens, layout, responsive states, and DOM fallback.
- `web/vendor/three.module.min.js`: a pinned local Three.js module with its license.

### 5.2 View model

`run-model.js` produces a stable object with these top-level fields:

```text
mode             recorded | live | replay | disconnected
mission          id, title, summary
run              id, task, repository, status, duration, attempt count
layers           intent, control, worker, repo
stages           plan, equip, work, guard, prove
proof            tests, scope, risk, permissions, evidence, verification
pack             provenance or unavailable
telemetry        normalized governance and worker events
artifacts        available files and bundle URL
selection        selected stage and selected event
errors           scoped fetch, stream, artifact, and rendering errors
```

Verdict calculation stays in Python. The view model only maps persisted values to
presentation states.

The mode values are distinct: `recorded` is a committed golden run, `replay` is an
ordinary completed run being replayed from local storage, `live` is a run with an
actively growing worker event stream, and `disconnected` preserves the last known
state after a stream failure.

## 6. Capability-Pack Provenance

The Equip stage must prove which capability pack reached the worker.

A backwards-compatible `CapabilityPackProvenance` model will contain:

- `name`
- `domain`
- `version`
- `description`
- `skills`
- `resolved_tools`
- `hooks`
- `manifest_sha256`

The provenance is added to the canonical `RunRecord`, the worker-loop summary, and
a `capability_pack.json` artifact. Older records default to `None` and render the
Equip stage as `unavailable`, not failed.

`WorkerLoopSummary.tools_requested` must record the resolved tool set used to build
the agent, not the global default tool list.

The artifact bundle already exports the run directory, so writing
`capability_pack.json` into that directory makes provenance part of the downloaded
bundle without a separate export path.

## 7. Golden Run and Showcase Startup

### 7.1 Committed structure

The approved run is stored under:

```text
examples/showcase/governed-migration/
  manifest.yaml
  run_record.json
  artifacts/
```

`manifest.yaml` records the mission ID, run ID, target fixture, source commit,
capture date, pack identity, expected artifact list, and sanitation notes.

The golden run is captured only after a real OpenHands run completes successfully.
The capture process removes credentials, environment values, user home paths, and
machine-specific temporary paths without changing semantic results. The committed
fixture retains the original task, diff, tests, verdicts, event ordering, and source
commit.

### 7.2 Import path

`scripts/showcase.py` performs an idempotent import:

1. Validate the showcase manifest and required artifacts.
2. Parse the committed record through the current `RunRecord` schema.
3. Save it through `RunStorage` to `.agentops/showcase.db`.
4. Copy artifacts to `.agentops/runs/<run_id>/`.
5. Start `create_api(storage_path=showcase.db)` with Uvicorn.
6. Open `/cockpit?mission=governed-migration` unless `--no-open` is supplied.

`make showcase` invokes this script. Re-running it replaces the known showcase
record and its exact artifact directory, but does not delete unrelated run history.

There is no showcase-only frontend data source. After import, the run travels through
the standard storage, CockpitReader, API, SSE, artifact, and bundle paths.

## 8. Replay and Interaction

Golden playback is labeled `Recorded` at all times. It never uses the existing
pulsing live indicator.

The replay controller supports play, pause, restart, and stage selection. It merges
outer governance events and worker events into a deterministic ordered timeline.
If source timestamps are absent, stable recorded order is used with a documented
presentation interval; no synthetic timestamps are added to artifacts.

Stage selection has three coordinated effects:

1. Move the camera to a fixed, bounded preset.
2. Highlight the relevant runway node and harness layer.
3. Update the DOM detail panel with supporting artifacts and claims.

Camera movement is bounded. Phase 1 does not include free orbit controls because
they weaken the explanatory composition and keyboard experience.

## 9. Failure Contract

### Recorded mode

- Show a persistent `Recorded` badge and replay controls.
- Do not display a live pulse.
- Retain source-commit and capture metadata.

### Stream interruption

- Freeze at the last verified event.
- Preserve already-loaded evidence and current selection.
- Reconnect after 1, 2, and 4 seconds.
- After three failed reconnects, show a manual retry action.
- Never advance stage state optimistically.

### Missing or invalid artifacts

- Render all evidence that remains available.
- Mark only the affected proof card and stage as `unavailable`.
- Suppress `Accepted` when the verification bundle required to support it is missing.
- Name the missing artifact and offer the relevant retry or bundle action.

### WebGL unavailable

- Replace the canvas with the five-stage DOM ribbon.
- Preserve all selection, proof, telemetry, and artifact interactions.
- Report `2D fallback` as a visual mode, not a run failure.

### Reduced motion

- Keep the Three.js scene.
- Disable camera interpolation, pulsing, and ambient movement.
- Apply state changes immediately.

### Empty storage or invalid golden run

- Show the exact `make showcase` or run-generation command.
- Do not render empty proof cards as zero-value success.
- Exit `scripts/showcase.py` with a non-zero status if the committed fixture cannot
  be validated or imported.

## 10. Accessibility and Performance

- All stage controls are keyboard reachable and expose selected/current state.
- Canvas information is duplicated in semantic DOM text.
- Status is communicated by label and icon as well as color.
- Color contrast targets WCAG AA for DOM content.
- The layout supports desktop, tablet, and narrow mobile widths; mobile defaults to
  the DOM stage ribbon and makes the 3D stage optional.
- Device pixel ratio is capped at 1.5.
- Animation runs only during playback or a transition and pauses when the tab is
  hidden.
- Run switching closes previous EventSource objects and disposes scene-specific
  geometries, materials, textures, and listeners.
- Resize work is throttled to animation frames.

## 11. Testing and Verification

### Python tests

- Showcase manifest and required-artifact validation.
- Idempotent golden-run import through `RunStorage`.
- Cockpit list, detail, stream, artifact, and bundle endpoints for the imported run.
- Capability-pack provenance serialization and backwards compatibility.
- Actual resolved tools in `WorkerLoopSummary`.
- Missing-artifact and invalid-showcase failure paths.

### Frontend unit tests

Use the Node built-in test runner with no npm dependency for pure ESM modules:

- Raw run detail to five-stage view-model mapping.
- Recorded/live/disconnected mode mapping.
- Proof and final-verdict suppression when evidence is unavailable.
- Pack-provenance and backwards-compatible unavailable states.
- Event ordering and stage-selection reducers.
- Reconnect state transitions.

Three.js geometry construction is not coupled to these tests; scene inputs are the
tested view model.

### Browser verification

Run the seeded showcase in a real browser and verify:

- Canvas initializes with no console errors.
- All five stages are selectable by pointer and keyboard.
- Replay controls drive the runway and telemetry together.
- Proof cards link to the expected artifacts.
- Run switching closes prior streams and resets selection correctly.
- Recorded, reconnecting, partial-evidence, reduced-motion, and 2D fallback states.
- Desktop, tablet, and mobile layouts.
- No continuous animation after replay is paused or the tab is hidden.

The approved desktop view is captured as a README hero image or short GIF after the
real golden run is available.

### Repository verification

- `uv run --extra dev python -m pytest -q -m "not docker"`
- `uv run --extra dev ruff check .`
- Node built-in frontend test command.
- `make showcase` smoke test from a clean local environment.

## 12. Delivery Sequence

1. Add pack provenance and tests.
2. Add golden-run manifest/import infrastructure using a temporary test fixture.
3. Split the existing frontend without changing behavior.
4. Introduce `CockpitViewModel` and prove it against existing runs.
5. Add the locally vendored Three.js stage and 2D fallback.
6. Connect Governed Migration replay and evidence selection.
7. Capture and sanitize the real Pydantic migration run.
8. Add `make showcase`, README hero media, and the concise walkthrough.
9. Add Guardrail Intercept on the same data and scene contracts.

The first implementation checkpoint is reached after step 4: existing Cockpit data
must render through the new state boundary before any 3D polish is considered
complete.

The implementation plan produced from this design covers steps 1 through 8 and
therefore Phase 1 only. Guardrail Intercept receives a separate plan after the
Governed Migration showcase passes its acceptance criteria.

## 13. Portfolio Narrative

The final three-minute walkthrough is:

1. Show the four nested harness layers.
2. Start the recorded Governed Migration.
3. Inspect the injected pack at Equip.
4. Watch real worker actions at Work.
5. Show tests, retry, risk, and permission decisions at Guard.
6. Open the evidence-backed verdict and bundle at Prove.
7. Switch to Guardrail Intercept to demonstrate enforcement using the same system.

The story is not that AgentOps made a dashboard. The story is that AgentOps makes an
agent run executable, inspectable, stateful, governed, and provable—and the Cockpit
makes those properties visible.
