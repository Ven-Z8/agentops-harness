import assert from "node:assert/strict";
import test from "node:test";

import { MISSIONS } from "../mission-config.js";
import { buildCockpitViewModel, mergeTimeline } from "../run-model.js";

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
  };
}

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
  assert.deepEqual(first.map(event => event.source), ["governance", "governance", "worker"]);
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
