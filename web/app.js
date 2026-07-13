"use strict";

import { CockpitDataClient } from "./data-client.js";
import { missionFromLocation } from "./mission-config.js";
import {
  createLatestRequestGate,
  mergeEvidenceEvents,
  streamShouldClose,
  updateChannelErrors,
} from "./app-state.js";
import { createReplayController, createReplayState } from "./replay-controller.js";
import { buildCockpitViewModel, STAGE_IDS } from "./run-model.js";
import { createThreeStage } from "./scene/three-stage.js";
import { stageVisual } from "./scene/transitions.js";
import * as panels from "./ui/panels.js";

// AgentOps Cockpit — vanilla ES-module lifecycle coordinator. The data client
// owns API/SSE access, while ui/panels.js projects backend-authored run data.
const client = new CockpitDataClient();
const state = {
  runs: [], selected: null, detail: null, viewModel: null, tab: "plan", wfilter: "all",
  mission: missionFromLocation(), mode: "replay", errors: {}, selectedEvent: null,
  replay: createReplayState({ length: 0 }),
  trajectoryEvents: [], workerEvents: [],
};
let replayController = null;
let cockpitStage = null;
let stageContextLostHandler = null;
const runDetailRequests = createLatestRequestGate();

if (state.mission?.initialStage) {
  state.tab = state.mission.initialStage;
  state.replay = { ...state.replay, selectedStage: state.mission.initialStage };
}

const TABS = [
  { key: "plan", label: "Plan", count: d => d.record.plan?.steps?.length, render: panels.tabPlan },
  { key: "diff", label: "Diff", count: d => d.record.changed_files?.length, render: panels.tabDiff },
  { key: "tests", label: "Tests", count: d => d.record.test_results?.commands?.length, render: panels.tabTests },
  { key: "worker", label: "Worker loop", count: d => d.worker?.count || undefined, render: panels.tabWorker },
  { key: "governance", label: "Governance", render: panels.tabGovernance },
  { key: "product", label: "Product", count: d => d.record.product_review?.findings?.length, render: panels.tabProduct },
  { key: "graph", label: "Graph", render: panels.tabGraph },
  { key: "report", label: "Report", render: panels.tabReport },
  { key: "files", label: "Files", count: d => d.artifacts?.length, render: panels.tabFiles },
];
const TAB_STAGES = Object.freeze({
  plan: "plan",
  diff: "work",
  tests: "guard",
  worker: "work",
  governance: "guard",
  product: "prove",
  graph: "plan",
  report: "prove",
  files: "prove",
});
const TERMINAL_STATUSES = new Set(["completed", "blocked", "failed"]);

window.addEventListener("beforeunload", () => {
  stopReplayTimer();
  client.closeStreams();
  disposeTacticalStage();
}, { once: true });
document.addEventListener("visibilitychange", () => {
  if (document.hidden && state.replay.playing) pauseReplay();
});
initializeTacticalStage();
init();

function initializeTacticalStage() {
  const canvas = document.getElementById("cockpit3d");
  const fallback = document.getElementById("stageFallback");
  const visualMode = document.getElementById("visualMode");
  try {
    cockpitStage = createThreeStage({
      canvas,
      onStageSelected: stageId => {
        if (state.viewModel) selectStage(stageId);
      },
      reducedMotion: window.matchMedia?.("(prefers-reduced-motion: reduce)").matches || false,
    });
    canvas.hidden = false;
    fallback.hidden = true;
    visualMode.textContent = "3D stage";
    stageContextLostHandler = event => {
      event.preventDefault();
      activateStageFallback("WebGL context lost");
      if (state.detail) {
        const viewModel = rebuildViewModel();
        panels.renderModelState(viewModel);
      }
    };
    canvas.addEventListener("webglcontextlost", stageContextLostHandler);
  } catch (error) {
    activateStageFallback(error?.message || "WebGL is unavailable");
  }
}

function disposeTacticalStage() {
  const canvas = document.getElementById("cockpit3d");
  if (stageContextLostHandler) {
    canvas?.removeEventListener("webglcontextlost", stageContextLostHandler);
    stageContextLostHandler = null;
  }
  const stage = cockpitStage;
  cockpitStage = null;
  stage?.dispose();
}

function activateStageFallback(message) {
  disposeTacticalStage();
  state.errors = {
    ...state.errors,
    webgl: { type: "webgl", message: String(message) },
  };
  const canvas = document.getElementById("cockpit3d");
  const fallback = document.getElementById("stageFallback");
  const visualMode = document.getElementById("visualMode");
  canvas.hidden = true;
  fallback.hidden = false;
  fallback.setAttribute("aria-label", "2D fallback stage");
  visualMode.textContent = "2D fallback";
  renderStageFallback(state.viewModel);
}

function renderStageFallback(viewModel) {
  const fallback = document.getElementById("stageFallback");
  if (fallback.hidden) return;
  if (!viewModel) {
    fallback.innerHTML = '<div class="empty">Select a run to inspect the stage.</div>';
    return;
  }
  fallback.innerHTML = `<div class="stage-fallback-ribbon" role="group" aria-label="Run stages">
    ${viewModel.stages.map(stage => {
    const visual = stageVisual(stage.status);
    const selected = stage.id === viewModel.selection.stage;
    return `<button class="stage-fallback-node" data-stage="${panels.esc(stage.id)}" data-status="${panels.esc(stage.status)}" aria-pressed="${selected}">
      <span class="fallback-glyph" aria-hidden="true">${panels.esc(visual.glyph)}</span>
      <span>${panels.esc(stage.label)}</span>
      <span class="fallback-status">${panels.esc(visual.label)}</span>
    </button>`;
  }).join("")}
  </div>`;
  fallback.querySelectorAll("[data-stage]").forEach(button => {
    button.addEventListener("click", () => selectStage(button.dataset.stage));
  });
}

function renderTacticalStage(viewModel) {
  if (!cockpitStage) {
    renderStageFallback(viewModel);
    return;
  }
  try {
    cockpitStage.setPlaybackActive(state.replay.playing);
    cockpitStage.render(viewModel);
  } catch (error) {
    activateStageFallback(error?.message || "WebGL rendering failed");
  }
}

async function init() {
  await loadRuns();
  const preferred = state.mission
    ? state.runs.find(run => run.run_id === state.mission.recordedRunId)
    : null;
  const initialRun = preferred || state.runs[0];
  if (initialRun) selectRun(initialRun.run_id);
}

async function loadRuns() {
  const data = await client.listRuns();
  state.runs = data.runs;
  panels.renderStats(data.stats);
  panels.renderRunList(state.runs, {
    selected: state.selected,
    onSelectRun: selectRun,
  });
}

async function selectRun(runId) {
  const request = runDetailRequests.begin();
  stopReplayTimer();
  state.selected = runId;
  panels.markSelected(state.selected);
  client.closeStreams();
  const inspector = document.getElementById("inspector");
  inspector.innerHTML = '<div class="empty">Loading run…</div>';
  try {
    const detail = await client.runDetail(runId);
    if (!runDetailRequests.isCurrent(request)) return;
    setDetail(detail);
  } catch (error) {
    if (!runDetailRequests.isCurrent(request)) return;
    inspector.innerHTML = `<div class="empty">Failed to load: ${panels.esc(error.message)}</div>`;
    return;
  }
  panels.renderInspector(state.viewModel, {
    detail: state.detail,
    tabs: TABS,
    selectedTab: state.tab,
    onSelectTab: selectTab,
    onTogglePause: togglePause,
  });
  streamTrajectory(runId);
}

function selectTab(key) {
  state.tab = key;
  stopWorkerStream();
  const stage = TAB_STAGES[key] || "plan";
  if (stage !== state.replay.selectedStage) selectStage(stage);
  const tab = panels.renderTab(TABS, key, state.viewModel, state.detail);
  if (tab.key === "diff") loadDiffArtifact();
  if (tab.key === "worker") activateWorkerPanel();
  if (tab.key === "files") panels.bindArtifactRows(onSelectArtifact);
}

async function loadDiffArtifact() {
  const pane = document.getElementById("diffPane");
  if (!pane) return;
  try {
    const text = await client.text(
      `/cockpit/api/runs/${encodeURIComponent(state.viewModel.run.id)}/artifacts/diff.patch`,
    );
    pane.innerHTML = panels.colorizeDiff(text);
  } catch {
    pane.textContent = "Could not load diff.patch";
  }
}

function streamTrajectory(runId) {
  const host = document.getElementById("traj");
  if (!host) return;
  host.innerHTML = "";
  state.viewModel.telemetry.governance.forEach(event => panels.appendEvent(host, event));
  if (isReplayMode()) playReplay({ restart: true });
  host.streamSource = client.openStream(
    `/cockpit/api/runs/${encodeURIComponent(runId)}/stream`,
    {
      open: () => updateConnection("trajectory", "open"),
      event: event => {
        const streamedEvent = JSON.parse(event.data);
        const evidenceCount = state.viewModel.telemetry.governance.length;
        state.trajectoryEvents.push(streamedEvent);
        const viewModel = rebuildViewModel();
        viewModel.telemetry.governance.slice(evidenceCount).forEach(
          evidence => panels.appendEvent(host, evidence),
        );
      },
      done: () => {
        updateConnection("trajectory", "done");
        if (streamShouldClose("done")) {
          finishTrajectory(host, { keepReplayControls: isReplayMode() });
        }
      },
      error: () => {
        updateConnection("trajectory", "error");
        if (streamShouldClose("error")) {
          finishTrajectory(host, { keepReplayControls: isReplayMode() });
        }
      },
    },
  );
}

function finishTrajectory(
  host = document.getElementById("traj"),
  { keepReplayControls = false } = {},
) {
  closeHostStream(host);
  document.getElementById("trajDot")?.classList.remove("pulse");
  const button = document.getElementById("pauseBtn");
  if (button) button.style.display = keepReplayControls ? "" : "none";
  if (keepReplayControls) renderReplayControls();
}

function togglePause() {
  if (isReplayMode()) {
    if (state.replay.playing) pauseReplay();
    else playReplay({ restart: state.replay.cursor >= state.replay.length - 1 });
    return;
  }
  const host = document.getElementById("traj");
  const button = document.getElementById("pauseBtn");
  if (host?.streamSource) {
    closeHostStream(host);
    document.getElementById("trajDot")?.classList.remove("pulse");
    if (button) button.innerHTML = `${panels.ICON.play}<span>resume</span>`;
  } else if (state.selected) {
    streamTrajectory(state.selected);
    if (button) {
      button.style.display = "";
      button.innerHTML = `${panels.ICON.pause}<span>pause</span>`;
    }
  }
}

function activateWorkerPanel() {
  if (!state.detail.worker?.present) return;
  panels.bindWorkerPanel({
    filter: state.wfilter,
    onFilterChange: filter => { state.wfilter = filter; },
  });
  streamWorker(state.viewModel.run.id);
}

function streamWorker(runId) {
  const host = document.getElementById("wtraj");
  if (!host) return;
  host.innerHTML = "";
  state.viewModel.telemetry.worker.forEach(event => {
    host.insertAdjacentHTML("beforeend", panels.ievRow(event));
    panels.applyFilterToRow(host.lastElementChild, state.wfilter);
  });
  const stop = () => {
    closeHostStream(host);
    document.getElementById("wDot")?.classList.remove("pulse");
  };
  host.streamSource = client.openStream(
    `/cockpit/api/runs/${encodeURIComponent(runId)}/worker/stream`,
    {
      open: () => {
        updateConnection("worker", "open");
        document.getElementById("wDot")?.classList.add("pulse");
      },
      event: event => {
        const evidenceCount = state.viewModel.telemetry.worker.length;
        state.workerEvents.push(JSON.parse(event.data));
        const viewModel = rebuildViewModel();
        viewModel.telemetry.worker.slice(evidenceCount).forEach(evidence => {
          host.insertAdjacentHTML("beforeend", panels.ievRow(evidence));
          panels.applyFilterToRow(host.lastElementChild, state.wfilter);
        });
        host.scrollTop = host.scrollHeight;
      },
      done: () => {
        updateConnection("worker", "done");
        if (streamShouldClose("done")) stop();
      },
      error: () => {
        updateConnection("worker", "error");
        document.getElementById("wDot")?.classList.remove("pulse");
        if (streamShouldClose("error")) stop();
      },
    },
  );
}

function stopWorkerStream() {
  closeHostStream(document.getElementById("wtraj"));
}

function closeHostStream(host) {
  if (!host?.streamSource) return;
  client.closeStream(host.streamSource);
  host.streamSource = null;
}

async function onSelectArtifact({ name, pane }) {
  try {
    const text = await client.text(
      `/cockpit/api/runs/${encodeURIComponent(state.viewModel.run.id)}/artifacts/${encodeURIComponent(name)}`,
    );
    pane.innerHTML = name.endsWith(".patch")
      ? panels.colorizeDiff(text)
      : panels.esc(text);
  } catch {
    pane.textContent = "Could not load file.";
  }
}

function modeForDetail(detail) {
  if (state.mission?.recordedRunId === detail.summary.run_id) return "recorded";
  return TERMINAL_STATUSES.has(detail.summary.status) ? "replay" : "live";
}

function projectedDetail() {
  const governance = mergeEvidenceEvents(
    state.detail.trajectory || [],
    state.trajectoryEvents,
  );
  const workerEvents = mergeEvidenceEvents(
    state.detail.worker?.events || [],
    state.workerEvents,
  );
  const worker = {
    ...state.detail.worker,
    events: workerEvents,
    count: workerEvents.length,
  };
  return {
    ...state.detail,
    trajectory: governance,
    worker,
  };
}

function setDetail(detail) {
  stopReplayTimer();
  state.detail = detail;
  state.mode = modeForDetail(detail);
  state.errors = state.errors.webgl ? { webgl: state.errors.webgl } : {};
  state.selectedEvent = null;
  state.trajectoryEvents = [];
  state.workerEvents = [];
  const length = (detail.trajectory?.length || 0) + (detail.worker?.events?.length || 0);
  const initialReplay = {
    ...createReplayState({
      length,
      reducedMotion: window.matchMedia?.("(prefers-reduced-motion: reduce)").matches || false,
    }),
    selectedStage: state.mission?.initialStage || "plan",
  };
  state.replay = initialReplay;
  replayController = createReplayController({
    initialState: initialReplay,
    onChange: applyReplayState,
  });
  rebuildViewModel();
}

function rebuildViewModel() {
  state.viewModel = buildCockpitViewModel({
    detail: projectedDetail(),
    mission: state.mission,
    mode: state.mode,
    selection: {
      stage: state.replay.selectedStage,
      event: state.selectedEvent,
    },
    errors: state.errors,
  });
  renderTacticalStage(state.viewModel);
  return state.viewModel;
}

function applyReplayState(replayState) {
  state.replay = replayState;
  state.selectedEvent = state.replay.cursor >= 0
    ? state.viewModel.telemetry.timeline[state.replay.cursor] ?? null
    : null;
  const viewModel = rebuildViewModel();
  panels.renderModelState(viewModel);
  renderReplayControls();
}

function transitionReplay(action) {
  replayController?.dispatch(action);
  return state.viewModel;
}

function selectStage(stage) {
  if (!STAGE_IDS.includes(stage)) return state.viewModel;
  const cursor = state.viewModel.telemetry.timeline.findIndex(event => event.stage === stage);
  return transitionReplay({ type: "select-stage", stage, cursor });
}

function playReplay({ restart = false } = {}) {
  if (restart) transitionReplay({ type: "restart" });
  return transitionReplay({ type: "play" });
}

function pauseReplay() {
  return transitionReplay({ type: "pause" });
}

function stopReplayTimer() {
  replayController?.stop();
}

function renderReplayControls() {
  if (!isReplayMode()) return;
  const button = document.getElementById("pauseBtn");
  if (!button) return;
  button.style.display = "";
  const atEnd = state.replay.cursor >= state.replay.length - 1;
  button.innerHTML = state.replay.playing
    ? `${panels.ICON.pause}<span>pause</span>`
    : `${panels.ICON.play}<span>${atEnd ? "restart" : "resume"}</span>`;
}

function isReplayMode() {
  return state.mode === "recorded" || state.mode === "replay";
}

function updateConnection(channel, status) {
  const errors = updateChannelErrors(state.errors, channel, status);
  state.errors = errors;
  const detailMode = modeForDetail(state.detail);
  const hasStreamError = Boolean(errors.trajectory || errors.worker);
  state.mode = detailMode === "live" && hasStreamError ? "disconnected" : detailMode;
  const viewModel = rebuildViewModel();
  panels.renderModelState(viewModel);
  return viewModel;
}
