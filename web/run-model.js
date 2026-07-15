"use strict";

export const STAGE_IDS = Object.freeze(["plan", "equip", "work", "guard", "prove"]);
export const STAGE_EVIDENCE = Object.freeze({
  plan: Object.freeze(["task_plan.yaml", "repo_graph.json"]),
  equip: Object.freeze(["capability_pack.json", "worker_loop_summary.json"]),
  work: Object.freeze(["openhands_events.jsonl", "diff.patch", "worker_result.json"]),
  guard: Object.freeze(["test_results.json", "risk_report.json", "permission_report.json"]),
  prove: Object.freeze([
    "evidence_report.json", "product_review.json", "verification_bundle.json",
  ]),
});

const GOVERNANCE_STAGES = Object.freeze({
  scan_repo: "plan",
  repo_graph: "plan",
  goal_model: "plan",
  recall_experience: "plan",
  create_plan: "plan",
  prepare_workspace: "equip",
  pre_dispatch: "equip",
  run_external_worker: "work",
  collect_diff: "work",
  enforce_permissions: "guard",
  run_tests: "guard",
  check_convergence: "guard",
  build_changed_subgraph: "guard",
  review_diff: "guard",
  assess_risk: "guard",
  classify_permissions: "guard",
  write_report: "prove",
  check_report_quality: "prove",
  check_evidence: "prove",
  build_product_review: "prove",
  assemble_verification: "prove",
  audit_conflicts: "prove",
});

const hasArtifact = (detail, name) => (
  (detail.artifacts || []).some(item => item.name === name)
);

const stageForGovernance = event => GOVERNANCE_STAGES[event.node] ?? null;
const eventId = (source, event, sourceOrder) => (
  `${source}:${event.index != null ? `index:${event.index}` : `order:${sourceOrder}`}`
);

const workerInsertionIndex = governance => {
  const workerStart = governance.findIndex(
    event => event.node === "run_external_worker" && event.phase === "start",
  );
  const workerComplete = governance.findIndex(
    (event, index) => index > workerStart &&
      event.node === "run_external_worker" && event.phase === "complete",
  );
  if (workerStart >= 0 && workerComplete >= 0) return workerComplete;
  if (workerStart >= 0) return workerStart + 1;

  const unmatchedComplete = governance.findIndex(
    event => event.node === "run_external_worker" && event.phase === "complete",
  );
  if (unmatchedComplete >= 0) return unmatchedComplete;

  const firstWork = governance.findIndex(event => event.stage === "work");
  if (firstWork >= 0) return firstWork;

  const firstPostWork = governance.findIndex(
    event => event.stage === "guard" || event.stage === "prove",
  );
  return firstPostWork >= 0 ? firstPostWork : governance.length;
};

export function mergeTimeline(governanceEvents = [], workerEvents = []) {
  const governance = governanceEvents.map((event, sourceOrder) => ({
    ...event,
    source: "governance",
    sourceOrder,
    id: eventId("governance", event, sourceOrder),
    stage: stageForGovernance(event),
  }));
  const worker = workerEvents.map((event, sourceOrder) => ({
    ...event,
    source: "worker",
    sourceOrder,
    id: eventId("worker", event, sourceOrder),
    stage: "work",
  }));

  const insertionIndex = workerInsertionIndex(governance);
  return [
    ...governance.slice(0, insertionIndex),
    ...worker,
    ...governance.slice(insertionIndex),
  ].map((event, order) => ({ ...event, order }));
}

export function buildCockpitViewModel({
  detail,
  mission = null,
  mode = "replay",
  selection = { stage: "plan", event: null },
  errors = {},
  reducedMotion = false,
}) {
  const record = detail.record;
  const summary = detail.summary;
  const plan = record.plan;
  const pack = record.capability_pack;
  const tests = record.test_results?.commands || [];
  const permissions = record.permission_report || { decisions: [] };
  const permissionDecisions = permissions.decisions || [];
  const risk = record.risk_report || {};
  const evidence = record.evidence_report || {};
  const product = record.product_review || {};
  const verificationChecks = record.verification_bundle?.checks || [];
  const governanceEvents = detail.trajectory || [];
  const workerEvents = detail.worker?.events || [];
  const workerDeclared = Boolean(record.edit_result || detail.worker?.present);
  const selectedStage = STAGE_IDS.includes(selection?.stage) ? selection.stage : "plan";
  const availableArtifactNames = (detail.artifacts || []).map(item => item.name);
  const availableArtifactSet = new Set(availableArtifactNames);
  const expectedStageEvidence = STAGE_EVIDENCE[selectedStage];
  const testsAvailable = tests.length > 0 || (summary.tests_total ?? 0) > 0;
  const testsPassed = testsAvailable
    ? (summary.tests_passed ?? tests.filter(item => item.exit_code === 0).length)
    : null;
  const testsTotal = testsAvailable ? (summary.tests_total ?? tests.length) : null;
  const planSteps = Array.isArray(plan?.steps) ? plan.steps.length : null;
  const changedFileCount = Array.isArray(record.changed_files)
    ? record.changed_files.length
    : null;
  const riskAvailable = record.risk_report != null &&
    (risk.risk_score != null || risk.risk_level != null);
  const permissionsAvailable = record.permission_report != null;
  const captureSource = detail.capture || detail.showcase || detail.manifest ||
    record.capture || record.showcase || null;
  const capture = captureSource ? {
    sourceRunId: captureSource.sourceRunId ?? captureSource.source_run_id ?? null,
    sourceCommit: captureSource.sourceCommit ?? captureSource.source_commit ?? null,
    capturedAt: captureSource.capturedAt ?? captureSource.captured_at ?? null,
  } : null;

  const planStatus = plan?.steps?.length > 0 &&
      (detail.phases || []).some(phase => phase.name === "plan")
    ? "pass"
    : "unavailable";
  const equipStatus = pack ? "pass" : "unavailable";
  const workStatus = record.edit_result?.status === "blocked"
    ? "blocked"
    : workerEvents.length > 0 || record.edit_result?.status === "completed"
      ? "pass"
      : workerDeclared
        ? "warn"
        : "unavailable";

  const permissionBlocked = permissions.blocked === true ||
    permissionDecisions.some(item => item.tier === "deny");
  const permissionNeedsReview = summary.permission_tier === "ask" ||
    permissionDecisions.some(item => item.tier === "ask");
  const testsFailed = tests.some(item => item.exit_code !== 0);
  const guardStatus = permissionBlocked || risk.blocked === true
    ? "blocked"
    : testsFailed || permissionNeedsReview ||
        ["medium", "high", "critical"].includes(risk.risk_level)
      ? "warn"
      : "pass";

  const verificationAvailable = hasArtifact(detail, "verification_bundle.json") &&
    verificationChecks.length > 0;
  const failedVerification = verificationChecks.some(check => check.verdict === "fail");
  const warningVerification = verificationChecks.some(
    check => check.verdict === "warn" || check.verdict === "not_run",
  );
  const proveStatus = !verificationAvailable
    ? "unavailable"
    : failedVerification || detail.verification?.accepted === false
      ? "blocked"
      : warningVerification
        ? "warn"
        : "pass";

  const stages = [
    { id: "plan", label: "Plan", status: planStatus, layer: "intent" },
    { id: "equip", label: "Equip", status: equipStatus, layer: "worker" },
    { id: "work", label: "Work", status: workStatus, layer: "repo" },
    { id: "guard", label: "Guard", status: guardStatus, layer: "control" },
    { id: "prove", label: "Prove", status: proveStatus, layer: "control" },
  ];
  const verificationError = verificationAvailable
    ? null
    : { message: "verification_bundle.json is missing or contains no checks" };

  return {
    mode,
    modeLabel: mode === "recorded"
      ? "Recorded"
      : mode === "live"
        ? "Live"
        : mode === "disconnected"
          ? "Disconnected"
          : "Replay",
    pulse: mode === "live" && !reducedMotion,
    mission,
    capture,
    run: {
      id: record.run_id,
      task: record.task,
      repository: record.repo_path,
      status: record.status,
      duration: summary.duration_seconds,
      attempts: record.attempts,
      worker: summary.worker,
      converged: summary.converged,
      blocked: summary.blocked,
    },
    layers: {
      intent: { label: "Intent Graph", status: planStatus },
      control: { label: "AgentOps Control", status: guardStatus },
      worker: { label: "Worker Loop", status: workStatus },
      repo: { label: "Repo Graph", status: record.repo_graph ? "pass" : "unavailable" },
    },
    stages,
    proof: {
      tests: {
        available: testsAvailable,
        commands: tests,
        passed: testsPassed,
        total: testsTotal,
      },
      scope: {
        available: planSteps != null || changedFileCount != null,
        planSteps,
        changedFiles: changedFileCount,
        files: record.changed_files || [],
      },
      risk: { available: riskAvailable, ...risk },
      permissions: {
        available: permissionsAvailable,
        tier: permissionsAvailable ? (summary.permission_tier ?? null) : null,
        ...permissions,
      },
      evidence: {
        available: hasArtifact(detail, "evidence_report.json"),
        ...evidence,
      },
      verification: {
        available: verificationAvailable,
        accepted: verificationAvailable ? (detail.verification?.accepted ?? null) : null,
        confidence: verificationAvailable
          ? (detail.verification?.overall_confidence ?? null)
          : null,
      },
      product: {
        available: Object.keys(product).length > 0,
        verdict: summary.product_verdict,
        ...product,
      },
      finalVerdict: proveStatus === "pass"
        ? "Accepted"
        : proveStatus === "warn"
          ? "Needs review"
          : proveStatus === "blocked"
            ? "Blocked"
            : "Unavailable",
    },
    pack: pack ? { available: true, ...pack } : { available: false },
    telemetry: {
      governance: governanceEvents,
      worker: workerEvents,
      timeline: mergeTimeline(governanceEvents, workerEvents),
    },
    artifacts: {
      available: availableArtifactNames,
      files: detail.artifacts || [],
      bundleUrl: `/cockpit/api/runs/${encodeURIComponent(record.run_id)}/bundle.zip`,
    },
    selection: {
      stage: selectedStage,
      event: selection?.event ?? null,
      evidence: {
        expected: [...expectedStageEvidence],
        available: expectedStageEvidence.filter(name => availableArtifactSet.has(name)),
        missing: expectedStageEvidence.filter(name => !availableArtifactSet.has(name)),
      },
    },
    errors: {
      ...errors,
      ...(verificationError ? { verification: verificationError } : {}),
    },
  };
}
