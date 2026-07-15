import assert from "node:assert/strict";
import test from "node:test";

import { MISSIONS } from "../mission-config.js";
import {
  buildCockpitViewModel,
  mergeTimeline,
  STAGE_EVIDENCE,
} from "../run-model.js";

function governedMigrationDetail() {
  return {
    summary: {
      run_id: "showcase-governed-migration",
      task: "Migrate the service to Pydantic v2",
      repo_path: "examples/sample_fastapi_app",
      status: "completed",
      worker: "openhands",
      blocked: false,
      permission_tier: "auto",
      product_verdict: "aligned",
      attempts: 1,
      converged: true,
      duration_seconds: 12.5,
      tests_passed: 1,
      tests_total: 1,
      changed_files: 1,
    },
    record: {
      run_id: "showcase-governed-migration",
      task: "Migrate the service to Pydantic v2",
      repo_path: "examples/sample_fastapi_app",
      status: "completed",
      attempts: 1,
      plan: {
        summary: "Update models and callers together.",
        steps: [{ id: 1, title: "Update models", description: "Use v2 APIs." }],
      },
      capability_pack: {
        name: "pydantic-v2",
        version: "1.0.0",
        resolved_tools: ["terminal"],
      },
      edit_result: { status: "completed", worker_type: "openhands" },
      changed_files: ["app/models.py"],
      test_results: {
        commands: [{ command: "pytest -q", exit_code: 0, duration_seconds: 1.2 }],
      },
      permission_report: {
        decisions: [{ action: "edit app/models.py", tier: "auto", reason: "in scope" }],
        enforced_reverts: [],
      },
      risk_report: { risk_score: 18, risk_level: "low", blocked: false, factors: [] },
      evidence_report: { grounded: true, unsupported_claim_count: 0, findings: [] },
      verification_bundle: {
        checks: [{ name: "tests", verdict: "pass", confidence: "high" }],
      },
      product_review: { overall_verdict: "aligned", per_lens: {}, findings: [] },
      repo_graph: { nodes: [{ id: "app/models.py" }] },
    },
    phases: [{ name: "plan", status: "done" }],
    trajectory: [
      { index: 0, node: "scan_repo", phase: "complete" },
      { index: 1, node: "run_tests", phase: "complete" },
    ],
    worker: {
      present: true,
      count: 1,
      summary: { status: "completed" },
      scorecard: {},
      events: [{ index: 0, type: "ActionEvent", kind: "action", summary: "edit" }],
    },
    artifacts: [
      { name: "evidence_report.json", size: 120 },
      { name: "verification_bundle.json", size: 180 },
    ],
    verification: { accepted: true, overall_confidence: "high" },
    capture: {
      source_run_id: "source-capture-123",
      source_commit: "1".repeat(40),
      captured_at: "2026-07-13T12:00:00Z",
    },
  };
}

const CANONICAL_NODES_BY_STAGE = Object.freeze({
  plan: ["scan_repo", "repo_graph", "goal_model", "recall_experience", "create_plan"],
  equip: ["prepare_workspace", "pre_dispatch"],
  work: ["run_external_worker", "collect_diff"],
  guard: [
    "enforce_permissions", "run_tests", "check_convergence", "build_changed_subgraph",
    "review_diff", "assess_risk", "classify_permissions",
  ],
  prove: [
    "write_report", "check_report_quality", "check_evidence", "build_product_review",
    "assemble_verification", "audit_conflicts",
  ],
});

function canonicalGovernanceEvents() {
  let index = 0;
  return Object.values(CANONICAL_NODES_BY_STAGE).flatMap(nodes => (
    nodes.flatMap(node => {
      const phases = node === "run_external_worker" ? ["start", "complete"] : ["complete"];
      return phases.map(phase => ({ index: index++, node, phase }));
    })
  ));
}

test("recorded mode never becomes a pulsing live state", () => {
  const vm = buildCockpitViewModel({
    detail: governedMigrationDetail(),
    mission: MISSIONS["governed-migration"],
    mode: "recorded",
  });

  assert.equal(vm.mode, "recorded");
  assert.equal(vm.modeLabel, "Recorded");
  assert.equal(vm.pulse, false);
});

test("reduced motion removes live pulses without changing live mode", () => {
  const vm = buildCockpitViewModel({
    detail: governedMigrationDetail(),
    mode: "live",
    reducedMotion: true,
  });

  assert.equal(vm.mode, "live");
  assert.equal(vm.modeLabel, "Live");
  assert.equal(vm.pulse, false);
});

test("stage evidence is exact and separates available from missing artifacts", () => {
  const detail = governedMigrationDetail();
  detail.artifacts.push(
    { name: "capability_pack.json", size: 100 },
    { name: "worker_loop_summary.json", size: 80 },
  );

  const vm = buildCockpitViewModel({
    detail,
    selection: { stage: "equip", event: null },
  });

  assert.deepEqual(STAGE_EVIDENCE, {
    plan: ["task_plan.yaml", "repo_graph.json"],
    equip: ["capability_pack.json", "worker_loop_summary.json"],
    work: ["openhands_events.jsonl", "diff.patch", "worker_result.json"],
    guard: ["test_results.json", "risk_report.json", "permission_report.json"],
    prove: ["evidence_report.json", "product_review.json", "verification_bundle.json"],
  });
  assert.deepEqual(vm.selection.evidence.available, [
    "capability_pack.json", "worker_loop_summary.json",
  ]);
  assert.deepEqual(vm.selection.evidence.missing, []);
});

test("one missing stage artifact preserves available evidence and the Python verdict", () => {
  const detail = governedMigrationDetail();
  detail.artifacts.push({ name: "product_review.json", size: 200 });

  const vm = buildCockpitViewModel({
    detail,
    selection: { stage: "prove", event: null },
    errors: { artifact: { name: "product_review.json", message: "404" } },
  });

  assert.deepEqual(vm.selection.evidence.available, [
    "evidence_report.json", "product_review.json", "verification_bundle.json",
  ]);
  assert.equal(vm.errors.artifact.name, "product_review.json");
  assert.equal(vm.proof.finalVerdict, "Accepted");
});

test("proof projections preserve recorded capture metadata and honest missing values", () => {
  const detail = governedMigrationDetail();
  delete detail.summary.tests_passed;
  delete detail.summary.tests_total;
  delete detail.record.test_results;
  delete detail.record.risk_report;
  delete detail.record.permission_report;

  const vm = buildCockpitViewModel({ detail, mode: "recorded" });

  assert.equal(vm.proof.tests.available, false);
  assert.equal(vm.proof.tests.passed, null);
  assert.equal(vm.proof.tests.total, null);
  assert.equal(vm.proof.risk.available, false);
  assert.equal(vm.proof.permissions.available, false);
  assert.deepEqual(vm.capture, {
    sourceRunId: "source-capture-123",
    sourceCommit: "1".repeat(40),
    capturedAt: "2026-07-13T12:00:00Z",
  });
});

test("maps a recorded governed migration into five evidence-backed stages", () => {
  const vm = buildCockpitViewModel({
    detail: governedMigrationDetail(),
    mission: MISSIONS["governed-migration"],
    mode: "recorded",
    selection: { stage: "equip", event: null },
    errors: {},
  });

  assert.equal(vm.mode, "recorded");
  assert.deepEqual(Object.keys(vm.layers), ["intent", "control", "worker", "repo"]);
  assert.deepEqual(vm.stages.map(stage => stage.id), [
    "plan", "equip", "work", "guard", "prove",
  ]);
  assert.equal(vm.stages.find(stage => stage.id === "equip").status, "pass");
  assert.equal(vm.pack.name, "pydantic-v2");
  assert.equal(vm.selection.stage, "equip");
});

test("old runs mark Equip unavailable without failing the run", () => {
  const detail = governedMigrationDetail();
  detail.record.capability_pack = null;

  const vm = buildCockpitViewModel({ detail, mission: null, mode: "replay" });

  assert.equal(vm.stages.find(stage => stage.id === "equip").status, "unavailable");
  assert.equal(vm.pack.available, false);
  assert.equal(vm.run.status, "completed");
});

test("missing verification suppresses Accepted but preserves other proof", () => {
  const detail = governedMigrationDetail();
  detail.record.verification_bundle.checks = [];
  detail.artifacts = detail.artifacts.filter(
    artifact => artifact.name !== "verification_bundle.json",
  );

  const vm = buildCockpitViewModel({ detail, mission: null, mode: "replay" });

  assert.equal(vm.proof.verification.available, false);
  assert.equal(vm.proof.finalVerdict, "Unavailable");
  assert.equal(vm.proof.tests.available, true);
  assert.match(vm.errors.verification.message, /verification_bundle\.json/);
});

test("timeline ordering is stable when source timestamps are absent", () => {
  const detail = governedMigrationDetail();
  const first = mergeTimeline(detail.trajectory, detail.worker.events);
  const second = mergeTimeline(detail.trajectory, detail.worker.events);

  assert.deepEqual(first, second);
  assert.deepEqual(first.map(event => event.order), first.map((_, index) => index));
  assert.deepEqual(first.map(event => event.source), ["governance", "worker", "governance"]);
});

test("canonical governance and worker events tell one causal five-stage story", () => {
  const governance = canonicalGovernanceEvents();
  const worker = [
    { index: 0, type: "ActionEvent", summary: "inspect" },
    { index: 1, type: "ObservationEvent", summary: "edited" },
  ];

  const timeline = mergeTimeline(governance, worker);
  const governanceTimeline = timeline.filter(event => event.source === "governance");
  const stagesByNode = new Map(
    governanceTimeline.map(event => [event.node, event.stage]),
  );
  const transitions = timeline
    .map(event => event.stage)
    .filter((stage, index, stages) => index === 0 || stage !== stages[index - 1]);

  for (const [stage, nodes] of Object.entries(CANONICAL_NODES_BY_STAGE)) {
    assert.deepEqual(nodes.map(node => stagesByNode.get(node)), nodes.map(() => stage));
  }
  assert.deepEqual(transitions, ["plan", "equip", "work", "guard", "prove"]);
  assert.equal(timeline.at(-1).stage, "prove");

  const workerStart = timeline.find(
    event => event.node === "run_external_worker" && event.phase === "start",
  );
  const workerComplete = timeline.find(
    event => event.node === "run_external_worker" && event.phase === "complete",
  );
  const workerOrders = timeline
    .filter(event => event.source === "worker")
    .map(event => event.order);
  assert.ok(workerOrders.every(order => workerStart.order < order));
  assert.ok(workerOrders.every(order => order < workerComplete.order));
});

test("worker events use a deterministic causal fallback when their bracket is absent", () => {
  const governance = [
    { index: 0, node: "scan_repo", phase: "complete" },
    { index: 1, node: "prepare_workspace", phase: "complete" },
    { index: 2, node: "collect_diff", phase: "complete" },
    { index: 3, node: "enforce_permissions", phase: "complete" },
    { index: 4, node: "write_report", phase: "complete" },
  ];
  const worker = [
    { index: 0, type: "ActionEvent", summary: "inspect" },
    { index: 1, type: "ObservationEvent", summary: "edited" },
  ];

  const timeline = mergeTimeline(governance, worker);

  assert.deepEqual(timeline.map(event => event.source === "worker" ? "worker" : event.node), [
    "scan_repo", "prepare_workspace", "worker", "worker", "collect_diff",
    "enforce_permissions", "write_report",
  ]);
  assert.deepEqual(
    timeline.map(event => event.stage).filter(
      (stage, index, stages) => index === 0 || stage !== stages[index - 1],
    ),
    ["plan", "equip", "work", "guard", "prove"],
  );
});

test("unknown governance nodes remain explicitly unclassified", () => {
  const [event] = mergeTimeline([
    { index: 7, node: "future_governance_node", phase: "complete" },
  ]);

  assert.equal(event.stage, null);
  assert.equal(event.id, "governance:index:7");
  assert.equal(event.sourceOrder, 0);
});

test("timeline merge adds presentation metadata without mutating recorded artifacts", () => {
  const detail = governedMigrationDetail();
  const before = structuredClone({
    governance: detail.trajectory,
    worker: detail.worker.events,
  });

  const timeline = mergeTimeline(detail.trajectory, detail.worker.events);

  assert.deepEqual(detail.trajectory, before.governance);
  assert.deepEqual(detail.worker.events, before.worker);
  assert.equal(timeline.some(event => Object.hasOwn(event, "timestamp")), false);
});

test("timeline events keep stable source identities and source order as channels grow", () => {
  const governance = [
    { index: 0, node: "scan_repo", phase: "complete" },
    { index: 1, node: "run_external_worker", phase: "start" },
    { index: 2, node: "run_external_worker", phase: "complete" },
    { index: 3, node: "write_report", phase: "complete" },
  ];
  const worker = [{ index: 0, type: "ActionEvent", summary: "edit" }];
  const before = mergeTimeline(governance, worker);
  const afterGovernanceGrowth = mergeTimeline([
    ...governance,
    { index: 4, node: "audit_conflicts", phase: "complete" },
  ], worker);
  const afterWorkerGrowth = mergeTimeline(governance, [
    ...worker,
    { index: 1, type: "ObservationEvent", summary: "done" },
  ]);
  const workerBefore = before.find(event => event.source === "worker");
  const workerAfter = afterGovernanceGrowth.find(event => event.id === workerBefore.id);

  assert.equal(workerBefore.id, "worker:index:0");
  assert.equal(workerAfter.order, workerBefore.order);
  assert.deepEqual(
    afterGovernanceGrowth.slice(0, before.length).map(event => event.id),
    before.map(event => event.id),
  );
  assert.deepEqual(
    afterWorkerGrowth.filter(event => event.source === "governance")
      .map(({ id, sourceOrder }) => ({ id, sourceOrder })),
    before.filter(event => event.source === "governance")
      .map(({ id, sourceOrder }) => ({ id, sourceOrder })),
  );
});

test("plan requires both recorded steps and a plan phase", () => {
  const detail = governedMigrationDetail();
  detail.phases = [];

  const vm = buildCockpitViewModel({ detail });

  assert.equal(vm.stages.find(stage => stage.id === "plan").status, "unavailable");
});

test("guard and prove copy stored warning and failure states", () => {
  const detail = governedMigrationDetail();
  detail.record.test_results.commands[0].exit_code = 1;
  detail.record.verification_bundle.checks[0].verdict = "fail";
  detail.verification.accepted = false;

  const vm = buildCockpitViewModel({ detail });

  assert.equal(vm.stages.find(stage => stage.id === "guard").status, "warn");
  assert.equal(vm.stages.find(stage => stage.id === "prove").status, "blocked");
  assert.equal(vm.proof.finalVerdict, "Blocked");
});

test("an ask-tier permission decision warns even without a matching summary projection", () => {
  const detail = governedMigrationDetail();
  detail.record.permission_report.decisions[0].tier = "ask";

  const vm = buildCockpitViewModel({ detail });

  assert.equal(vm.stages.find(stage => stage.id === "guard").status, "warn");
});

test("a declared incomplete worker without observable events warns", () => {
  const detail = governedMigrationDetail();
  detail.record.edit_result.status = "failed";
  detail.worker.events = [];

  const vm = buildCockpitViewModel({ detail });

  assert.equal(vm.stages.find(stage => stage.id === "work").status, "warn");
});

test("a summary-only declared worker without observable events warns", () => {
  const detail = governedMigrationDetail();
  detail.record.edit_result = null;
  detail.worker.events = [];
  detail.worker.present = true;

  const vm = buildCockpitViewModel({ detail });

  assert.equal(vm.stages.find(stage => stage.id === "work").status, "warn");
});

test("stored verifier warnings require review without suppressing verification proof", () => {
  const detail = governedMigrationDetail();
  detail.record.verification_bundle.checks[0].verdict = "warn";

  const vm = buildCockpitViewModel({ detail });

  assert.equal(vm.stages.find(stage => stage.id === "prove").status, "warn");
  assert.equal(vm.proof.verification.available, true);
  assert.equal(vm.proof.finalVerdict, "Needs review");
});

test("worker prose and mission metadata cannot override stored verdicts", () => {
  const detail = governedMigrationDetail();
  detail.worker.events[0].summary = "Everything failed and is unsafe";
  detail.record.final_report = { markdown: "# Rejected" };
  const mission = { title: "Definitely accepted" };

  const vm = buildCockpitViewModel({ detail, mission });

  assert.equal(vm.stages.find(stage => stage.id === "prove").status, "pass");
  assert.equal(vm.proof.finalVerdict, "Accepted");
});
