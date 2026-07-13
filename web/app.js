"use strict";

import { CockpitDataClient } from "./data-client.js";
import { missionFromLocation } from "./mission-config.js";
import * as panels from "./ui/panels.js";

// AgentOps Cockpit — vanilla ES-module lifecycle coordinator. The data client
// owns API/SSE access, while ui/panels.js projects backend-authored run data.
const client = new CockpitDataClient();
const state = {
  runs: [], selected: null, detail: null, tab: "plan", wfilter: "all",
  mission: missionFromLocation(), selectedStage: "plan", selectedEvent: null,
};

if (state.mission?.initialStage) {
  state.tab = state.mission.initialStage;
  state.selectedStage = state.mission.initialStage;
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
    state.detail = await client.runDetail(runId);
  } catch (error) {
    inspector.innerHTML = `<div class="empty">Failed to load: ${panels.esc(error.message)}</div>`;
    return;
  }
  panels.renderInspector(state.detail, {
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
  const tab = panels.renderTab(TABS, key, state.detail);
  if (tab.key === "diff") loadDiffArtifact();
  if (tab.key === "worker") activateWorkerPanel();
  if (tab.key === "files") panels.bindArtifactRows(onSelectArtifact);
}

async function loadDiffArtifact() {
  const pane = document.getElementById("diffPane");
  if (!pane) return;
  try {
    const text = await client.text(
      `/cockpit/api/runs/${encodeURIComponent(state.detail.summary.run_id)}/artifacts/diff.patch`,
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
  host.streamSource = client.openStream(
    `/cockpit/api/runs/${encodeURIComponent(runId)}/stream`,
    {
      open() {},
      event: event => panels.appendEvent(host, JSON.parse(event.data)),
      done: () => finishTrajectory(host),
      error: () => finishTrajectory(host),
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
  streamWorker(state.detail.summary.run_id);
}

function streamWorker(runId) {
  const host = document.getElementById("wtraj");
  if (!host) return;
  host.innerHTML = "";
  const stop = () => {
    closeHostStream(host);
    document.getElementById("wDot")?.classList.remove("pulse");
  };
  host.streamSource = client.openStream(
    `/cockpit/api/runs/${encodeURIComponent(runId)}/worker/stream`,
    {
      open() {},
      event: event => {
        host.insertAdjacentHTML("beforeend", panels.ievRow(JSON.parse(event.data)));
        panels.applyFilterToRow(host.lastElementChild, state.wfilter);
        host.scrollTop = host.scrollHeight;
      },
      done: stop,
      error: stop,
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
      `/cockpit/api/runs/${encodeURIComponent(state.detail.summary.run_id)}/artifacts/${encodeURIComponent(name)}`,
    );
    pane.innerHTML = name.endsWith(".patch")
      ? panels.colorizeDiff(text)
      : panels.esc(text);
  } catch {
    pane.textContent = "Could not load file.";
  }
}
