import assert from "node:assert/strict";
import test from "node:test";

import {
  createLatestRequestGate,
  mergeEvidenceEvents,
  streamShouldClose,
  updateChannelErrors,
} from "../app-state.js";
import { createReplayController, createReplayState } from "../replay-controller.js";
import { buildCockpitViewModel } from "../run-model.js";

test("stream open partial backlog and disconnect preserve fetched governance evidence", () => {
  const fetched = [
    { index: 0, node: "scan_repo", phase: "complete" },
    { index: 1, node: "run_tests", phase: "complete" },
  ];

  const onOpen = mergeEvidenceEvents(fetched, []);
  const partialBacklog = mergeEvidenceEvents(fetched, [fetched[0]]);
  const afterDisconnect = mergeEvidenceEvents(partialBacklog, []);

  assert.deepEqual(onOpen, fetched);
  assert.deepEqual(partialBacklog, fetched);
  assert.deepEqual(afterDisconnect, fetched);
});

test("worker backlog deduplicates fetched events and appends genuinely new evidence", () => {
  const fetched = [
    { index: 0, type: "ActionEvent", kind: "action", summary: "edit" },
  ];
  const streamed = [
    { ...fetched[0] },
    { index: 1, type: "ObservationEvent", kind: "observation", summary: "saved" },
  ];

  assert.deepEqual(mergeEvidenceEvents(fetched, streamed), [fetched[0], streamed[1]]);
});

test("an empty worker stream cannot downgrade fetched Work evidence", () => {
  const fetched = [
    { index: 0, type: "ActionEvent", kind: "action", summary: "edit" },
  ];
  const detail = {
    summary: {
      duration_seconds: 1,
      permission_tier: "auto",
      worker: "openhands",
      converged: true,
      blocked: false,
      product_verdict: "not_evaluated",
    },
    record: {
      run_id: "run-1",
      task: "Edit",
      repo_path: ".",
      status: "completed",
      attempts: 1,
      plan: { steps: [{ id: 1 }] },
      edit_result: { status: "completed", worker_type: "openhands" },
      test_results: { commands: [] },
      permission_report: { decisions: [] },
      risk_report: { risk_level: "low", risk_score: 0, blocked: false },
      evidence_report: {},
      verification_bundle: { checks: [{ verdict: "pass" }] },
      product_review: {},
      changed_files: [],
      repo_graph: {},
    },
    phases: [{ name: "plan", status: "done" }],
    trajectory: [],
    worker: {
      present: true,
      events: mergeEvidenceEvents(fetched, []),
    },
    artifacts: [{ name: "verification_bundle.json" }],
    verification: { accepted: true, overall_confidence: "low" },
  };

  const viewModel = buildCockpitViewModel({ detail });

  assert.equal(viewModel.telemetry.worker.length, 1);
  assert.equal(viewModel.stages.find(stage => stage.id === "work").status, "pass");
});

test("SSE evidence ingestion does not advance the replay cursor", () => {
  const controller = createReplayController({
    initialState: createReplayState({ length: 3 }),
    onChange() {},
    setIntervalImpl: () => 1,
    clearIntervalImpl() {},
  });
  controller.dispatch({ type: "play" });

  const evidence = mergeEvidenceEvents(
    [{ index: 0, node: "scan_repo", phase: "complete" }],
    [{ index: 1, node: "run_tests", phase: "complete" }],
  );

  assert.equal(evidence.length, 2);
  assert.equal(controller.getState().cursor, -1);
});

test("a channel error persists until that same channel opens", () => {
  let errors = updateChannelErrors({}, "worker", "error");
  errors = updateChannelErrors(errors, "trajectory", "done");
  errors = updateChannelErrors(errors, "trajectory", "open");

  assert.match(errors.worker.message, /worker stream disconnected/);

  errors = updateChannelErrors(errors, "worker", "open");
  assert.deepEqual(errors, {});
});

test("only the latest overlapping run-detail request may install state", () => {
  const gate = createLatestRequestGate();
  const first = gate.begin();
  const second = gate.begin();

  assert.equal(gate.isCurrent(first), false);
  assert.equal(gate.isCurrent(second), true);
});

test("stream errors remain open for same-channel recovery", () => {
  assert.equal(streamShouldClose("error"), false);
  assert.equal(streamShouldClose("open"), false);
  assert.equal(streamShouldClose("done"), true);
});
