"use strict";

import { CockpitDataClient } from "./data-client.js";
import { missionFromLocation } from "./mission-config.js";
import { createReplayState, reduceReplay } from "./replay-controller.js";
import { buildCockpitViewModel, STAGE_IDS } from "./run-model.js";
import * as panels from "./ui/panels.js";

// AgentOps Cockpit — vanilla ES-module lifecycle coordinator. The data client
// owns API/SSE access, while ui/panels.js projects backend-authored run data.
const client = new CockpitDataClient();
const state = {
  runs: [], selected: null, detail: null, viewModel: null, tab: "plan", wfilter: "all",
  mission: missionFromLocation(), mode: "replay", errors: {}, selectedEvent: null,
  replay: createReplayState({ length: 0 }),
  trajectoryEvents: null, trajectoryIndex: 0, workerEvents: null,
};

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

window.addEventListener("beforeunload", () => client.closeStreams(), { once: true });
init();

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
  state.selected = runId;
  panels.markSelected(state.selected);
  client.closeStreams();
  const inspector = document.getElementById("inspector");
  inspector.innerHTML = '<div class="empty">Loading run…</div>';
  try {
    setDetail(await client.runDetail(runId));
  } catch (error) {
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
  state.trajectoryIndex = 0;
  if (isReplayMode()) {
    state.trajectoryEvents = null;
    transitionReplay({ type: "restart" });
    transitionReplay({ type: "play" });
  } else {
    state.trajectoryEvents = [];
  }
  host.streamSource = client.openStream(
    `/cockpit/api/runs/${encodeURIComponent(runId)}/stream`,
    {
      open: () => updateConnection("trajectory", "open"),
      event: event => {
        const streamedEvent = JSON.parse(event.data);
        if (isReplayMode()) {
          const viewModel = tickReplay();
          const recordedEvent = viewModel.telemetry.governance[state.trajectoryIndex];
          state.trajectoryIndex += 1;
          panels.appendEvent(host, recordedEvent || streamedEvent);
        } else {
          state.trajectoryEvents.push(streamedEvent);
          const viewModel = rebuildViewModel();
          panels.appendEvent(host, viewModel.telemetry.governance.at(-1));
        }
      },
      done: () => {
        if (isReplayMode()) transitionReplay({ type: "pause" });
        updateConnection("trajectory", "done");
        finishTrajectory(host);
      },
      error: () => {
        if (isReplayMode()) transitionReplay({ type: "pause" });
        updateConnection("trajectory", "error");
        finishTrajectory(host);
      },
    },
  );
}

function finishTrajectory(host = document.getElementById("traj")) {
  closeHostStream(host);
  document.getElementById("trajDot")?.classList.remove("pulse");
  const button = document.getElementById("pauseBtn");
  if (button) button.style.display = "none";
}

function togglePause() {
  const host = document.getElementById("traj");
  const button = document.getElementById("pauseBtn");
  if (host?.streamSource) {
    closeHostStream(host);
    if (isReplayMode()) transitionReplay({ type: "pause" });
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
  state.workerEvents = [];
  const stop = () => {
    closeHostStream(host);
    document.getElementById("wDot")?.classList.remove("pulse");
  };
  host.streamSource = client.openStream(
    `/cockpit/api/runs/${encodeURIComponent(runId)}/worker/stream`,
    {
      open: () => updateConnection("worker", "open"),
      event: event => {
        state.workerEvents.push(JSON.parse(event.data));
        const viewModel = rebuildViewModel();
        host.insertAdjacentHTML("beforeend", panels.ievRow(viewModel.telemetry.worker.at(-1)));
        panels.applyFilterToRow(host.lastElementChild, state.wfilter);
        host.scrollTop = host.scrollHeight;
      },
      done: () => {
        updateConnection("worker", "done");
        stop();
      },
      error: () => {
        updateConnection("worker", "error");
        stop();
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
  const worker = state.workerEvents === null
    ? state.detail.worker
    : {
        ...state.detail.worker,
        events: state.workerEvents,
        count: state.workerEvents.length,
      };
  return {
    ...state.detail,
    trajectory: state.trajectoryEvents ?? state.detail.trajectory,
    worker,
  };
}

function setDetail(detail) {
  state.detail = detail;
  state.mode = modeForDetail(detail);
  state.errors = {};
  state.selectedEvent = null;
  state.trajectoryEvents = null;
  state.trajectoryIndex = 0;
  state.workerEvents = null;
  const length = (detail.trajectory?.length || 0) + (detail.worker?.events?.length || 0);
  state.replay = {
    ...createReplayState({
      length,
      reducedMotion: window.matchMedia?.("(prefers-reduced-motion: reduce)").matches || false,
    }),
    selectedStage: state.mission?.initialStage || "plan",
  };
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
  state.replay = {
    ...state.replay,
    length: state.viewModel.telemetry.timeline.length,
  };
  return state.viewModel;
}

function transitionReplay(action) {
  state.replay = reduceReplay(state.replay, action);
  state.selectedEvent = state.replay.cursor >= 0
    ? state.viewModel.telemetry.timeline[state.replay.cursor] ?? null
    : null;
  const viewModel = rebuildViewModel();
  panels.renderModelState(viewModel);
  return viewModel;
}

function selectStage(stage) {
  if (!STAGE_IDS.includes(stage)) return state.viewModel;
  const cursor = state.viewModel.telemetry.timeline.findIndex(event => event.stage === stage);
  return transitionReplay({ type: "select-stage", stage, cursor });
}

function tickReplay() {
  return transitionReplay({ type: "tick" });
}

function isReplayMode() {
  return state.mode === "recorded" || state.mode === "replay";
}

function updateConnection(channel, status) {
  const errors = { ...state.errors };
  if (status === "error") {
    errors[channel] = { message: `${channel} stream disconnected` };
  } else {
    delete errors[channel];
  }
  state.errors = errors;
  const detailMode = modeForDetail(state.detail);
  const hasStreamError = Boolean(errors.trajectory || errors.worker);
  state.mode = detailMode === "live" && hasStreamError ? "disconnected" : detailMode;
  const viewModel = rebuildViewModel();
  panels.renderModelState(viewModel);
  return viewModel;
}
