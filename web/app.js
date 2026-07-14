"use strict";

import { CockpitDataClient } from "./data-client.js";
import { missionFromLocation } from "./mission-config.js";
import {
  createLatestRequestGate,
  mergeEvidenceEvents,
  streamShouldClose,
  updateChannelErrors,
} from "./app-state.js";
import {
  createReplayController,
  createReplayState,
  resolveReplayEvent,
} from "./replay-controller.js";
import { buildCockpitViewModel, STAGE_IDS } from "./run-model.js";
import { createThreeStage } from "./scene/three-stage.js";
import * as panels from "./ui/panels.js";

// AgentOps Cockpit — vanilla ES-module lifecycle coordinator. The data client
// owns API/SSE access, while ui/panels.js projects backend-authored run data.
const client = new CockpitDataClient();
const reducedMotionQuery = window.matchMedia?.("(prefers-reduced-motion: reduce)");
const mobileStageQuery = window.matchMedia?.("(max-width: 820px)");
const state = {
  runs: [], selected: null, detail: null, viewModel: null, tab: "plan", wfilter: "all",
  mission: missionFromLocation(), mode: "replay", errors: {}, selectedEvent: null,
  replay: createReplayState({ length: 0 }),
  trajectoryEvents: [], workerEvents: [],
};
let replayController = null;
let cockpitStage = null;
let stageContextLostHandler = null;
let webglAvailable = false;
let mobile3dVisible = false;
const runDetailRequests = createLatestRequestGate();
const artifactRequests = createLatestRequestGate();

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
const panelCallbacks = Object.freeze({
  onSelectStage: selectStage,
  onSelectArtifact,
  onRetryStream: retryStream,
});

window.addEventListener("beforeunload", () => {
  stopReplayTimer();
  client.closeStreams();
  disposeTacticalStage();
}, { once: true });
document.addEventListener("visibilitychange", () => {
  if (document.hidden && state.replay.playing) pauseReplay();
});
document.getElementById("replayBtn")?.addEventListener("click", togglePause);
document.getElementById("show3dBtn")?.addEventListener("click", () => {
  mobile3dVisible = !mobile3dVisible;
  syncMobileStageMode();
});
mobileStageQuery?.addEventListener?.("change", () => {
  mobile3dVisible = false;
  syncMobileStageMode();
});
renderMissionSummary();
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
      reducedMotion: reducedMotionQuery?.matches || false,
    });
    webglAvailable = true;
    canvas.hidden = false;
    fallback.hidden = true;
    visualMode.textContent = "3D stage";
    syncMobileStageMode();
    stageContextLostHandler = event => {
      event.preventDefault();
      activateStageFallback("WebGL context lost");
      if (state.detail) {
        const viewModel = rebuildViewModel();
        panels.renderModelState(viewModel, panelCallbacks);
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
  webglAvailable = false;
  mobile3dVisible = false;
  state.errors = {
    ...state.errors,
    webgl: { type: "webgl", message: String(message) },
  };
  const canvas = document.getElementById("cockpit3d");
  const fallback = document.getElementById("stageFallback");
  const visualMode = document.getElementById("visualMode");
  canvas.hidden = true;
  fallback.hidden = false;
  fallback.textContent = `3D architecture unavailable: ${String(message)}. Semantic stage controls remain available.`;
  visualMode.textContent = "2D fallback";
  syncMobileStageMode();
  renderSemanticStage(state.viewModel);
}

function renderSemanticStage(viewModel) {
  const ribbon = document.getElementById("stageRibbon");
  if (!viewModel) {
    ribbon.innerHTML = '<span class="empty">Select a run to inspect its stages.</span>';
    return;
  }
  ribbon.innerHTML = panels.stageRibbon(viewModel);
  panels.bindStageButtons(selectStage);
}

function renderTacticalStage(viewModel) {
  renderSemanticStage(viewModel);
  if (!cockpitStage) {
    return;
  }
  try {
    cockpitStage.setPlaybackActive(state.replay.playing);
    cockpitStage.render(viewModel);
  } catch (error) {
    activateStageFallback(error?.message || "WebGL rendering failed");
  }
}

function syncMobileStageMode() {
  const narrow = mobileStageQuery?.matches || false;
  const canvas = document.getElementById("cockpit3d");
  const shell = document.querySelector(".stage-shell");
  const button = document.getElementById("show3dBtn");
  const show3d = webglAvailable && (!narrow || mobile3dVisible);
  shell?.classList.toggle("mobile-3d", narrow && mobile3dVisible);
  if (canvas) canvas.hidden = !show3d;
  if (button) {
    button.hidden = !webglAvailable || !narrow;
    button.setAttribute("aria-pressed", String(mobile3dVisible));
    button.textContent = mobile3dVisible ? "Hide 3D architecture" : "Show 3D architecture";
  }
  if (show3d) cockpitStage?.resize();
}

function renderMissionSummary() {
  const host = document.getElementById("missionSummary");
  if (!host || !state.mission) return;
  host.innerHTML = `<p class="eyebrow">Mission</p><h1>${panels.esc(state.mission.title)}</h1><p>${panels.esc(state.mission.summary)}</p>`;
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
  artifactRequests.begin();
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
    ...panelCallbacks,
  });
  renderReplayControls();
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
  await onSelectArtifact({ name: "diff.patch", pane });
}

function streamTrajectory(runId) {
  const host = document.getElementById("traj");
  if (!host) return;
  host.innerHTML = "";
  state.viewModel.telemetry.governance.forEach(event => panels.appendEvent(host, event));
  if (isReplayMode()) playReplay({ restart: true });
  host.streamSource = client.openResilientStream(
    `/cockpit/api/runs/${encodeURIComponent(runId)}/stream`,
    {
      open: () => updateConnection("trajectory", "open"),
      event: event => {
        const streamedEvent = JSON.parse(event.data);
        const evidenceCount = state.viewModel.telemetry.governance.length;
        state.trajectoryEvents.push(streamedEvent);
        const viewModel = rebuildViewModel();
        syncReplayLength(viewModel.telemetry.timeline.length);
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
      error: (_event, connection) => {
        transitionReplay({ type: "disconnect" });
        updateConnection("trajectory", "error", connection);
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
  host.streamSource = client.openResilientStream(
    `/cockpit/api/runs/${encodeURIComponent(runId)}/worker/stream`,
    {
      open: () => {
        const viewModel = updateConnection("worker", "open");
        document.getElementById("wDot")?.classList.toggle("pulse", viewModel.pulse);
      },
      event: event => {
        const evidenceCount = state.viewModel.telemetry.worker.length;
        state.workerEvents.push(JSON.parse(event.data));
        const viewModel = rebuildViewModel();
        syncReplayLength(viewModel.telemetry.timeline.length);
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
      error: (_event, connection) => {
        transitionReplay({ type: "disconnect" });
        updateConnection("worker", "error", connection);
        document.getElementById("wDot")?.classList.remove("pulse");
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

function retryStream(channel) {
  const host = channel === "worker"
    ? document.getElementById("wtraj")
    : document.getElementById("traj");
  host?.streamSource?.retry?.();
}

function syncReplayLength(length) {
  if (!replayController || state.replay.length === length) return state.viewModel;
  return transitionReplay({ type: "set-length", length });
}

async function onSelectArtifact({ name, pane }) {
  const runId = state.selected;
  const selectedStage = state.replay.selectedStage;
  const isScopeCurrent = () => (
    state.selected === runId &&
    pane.isConnected !== false &&
    (pane.id !== "evidencePane" || state.replay.selectedStage === selectedStage)
  );
  return artifactRequests.run({
    request: () => client.text(
      `/cockpit/api/runs/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(name)}`,
    ),
    isScopeCurrent,
    onSuccess: text => {
      pane.innerHTML = name.endsWith(".patch")
        ? panels.colorizeDiff(text)
        : panels.esc(text);
      pane.hidden = false;
      if (state.errors.artifact?.name === name) {
        const { artifact: _artifact, ...remainingErrors } = state.errors;
        state.errors = remainingErrors;
        const viewModel = rebuildViewModel();
        panels.preserveRecoveredArtifactEvidence(viewModel);
      }
    },
    onError: error => {
      state.errors = {
        ...state.errors,
        artifact: { name, message: String(error?.message || error) },
      };
      const viewModel = rebuildViewModel();
      panels.renderModelState(viewModel, panelCallbacks);
      const target = pane.id ? document.getElementById(pane.id) : pane;
      if (target) {
        target.hidden = false;
        target.textContent = panels.artifactFailureMessage(name);
      }
    },
  });
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
      reducedMotion: reducedMotionQuery?.matches || false,
    }),
    selectedStage: state.mission?.initialStage || "plan",
  };
  state.replay = initialReplay;
  replayController = createReplayController({
    initialState: initialReplay,
    onChange: applyReplayState,
    eventAtCursor: cursor => state.viewModel?.telemetry.timeline[cursor] ?? null,
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
    reducedMotion: state.replay.reducedMotion,
  });
  renderTacticalStage(state.viewModel);
  return state.viewModel;
}

function applyReplayState(replayState) {
  state.replay = replayState;
  state.selectedEvent = resolveReplayEvent(
    state.replay,
    state.viewModel.telemetry.timeline,
  );
  const viewModel = rebuildViewModel();
  panels.renderModelState(viewModel, panelCallbacks);
  renderReplayControls();
}

function transitionReplay(action) {
  replayController?.dispatch(action);
  return state.viewModel;
}

function selectStage(stage) {
  if (!STAGE_IDS.includes(stage)) return state.viewModel;
  const cursor = state.viewModel.telemetry.timeline.findIndex(event => event.stage === stage);
  const eventId = state.viewModel.telemetry.timeline[cursor]?.id ?? null;
  return transitionReplay({ type: "select-stage", stage, cursor, eventId });
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
  const buttons = [
    document.getElementById("replayBtn"),
    document.getElementById("pauseBtn"),
  ].filter(Boolean);
  if (!buttons.length) return;
  const replay = isReplayMode();
  const atEnd = state.replay.cursor >= state.replay.length - 1;
  const action = state.replay.playing ? "pause" : atEnd ? "restart" : "resume";
  for (const button of buttons) {
    button.disabled = !state.detail || !replay;
    button.style.display = replay ? "" : "none";
    button.setAttribute("aria-pressed", String(state.replay.playing));
    button.setAttribute("aria-label", `${action[0].toUpperCase()}${action.slice(1)} recorded replay`);
    button.innerHTML = state.replay.playing
      ? `${panels.ICON.pause}<span>pause</span>`
      : `${panels.ICON.play}<span>${action}</span>`;
  }
}

function isReplayMode() {
  return state.mode === "recorded" || state.mode === "replay";
}

function updateConnection(channel, status, connection = null) {
  let errors = updateChannelErrors(state.errors, channel, status);
  if (status === "error" && connection) {
    errors = {
      ...errors,
      [channel]: { ...errors[channel], ...connection },
    };
  }
  state.errors = errors;
  const detailMode = modeForDetail(state.detail);
  const hasStreamError = Boolean(errors.trajectory || errors.worker);
  state.mode = detailMode === "live" && hasStreamError ? "disconnected" : detailMode;
  const viewModel = rebuildViewModel();
  panels.renderModelState(viewModel, panelCallbacks);
  renderReplayControls();
  return viewModel;
}
