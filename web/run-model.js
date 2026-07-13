"use strict";

export const STAGE_IDS = Object.freeze(["plan", "equip", "work", "guard", "prove"]);

const GOVERNANCE_STAGES = Object.freeze({
  scan_repo: "plan",
  repo_graph: "plan",
  goal_model: "plan",
  create_plan: "plan",
  run_external_worker: "work",
  collect_diff: "work",
  enforce_permissions: "guard",
  run_tests: "guard",
  check_convergence: "guard",
  assess_risk: "guard",
});

const hasArtifact = (detail, name) => (
  (detail.artifacts || []).some(item => item.name === name)
);

const stageForGovernance = event => GOVERNANCE_STAGES[event.node] || "prove";

export function mergeTimeline(governanceEvents = [], workerEvents = []) {
  const governance = governanceEvents.map((event, sourceOrder) => ({
    ...event,
    source: "governance",
    sourceOrder,
    stage: stageForGovernance(event),
  }));
  const worker = workerEvents.map((event, sourceOrder) => ({
    ...event,
    source: "worker",
    sourceOrder,
    stage: "work",
  }));

  return [...governance, ...worker].map((event, order) => ({ ...event, order }));
}

export function buildCockpitViewModel({
  detail,
  mission = null,
  mode = "replay",
  selection = { stage: "plan", event: null },
  errors = {},
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
    pulse: mode === "live",
    mission,
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
      tests: { available: tests.length > 0, commands: tests },
      scope: { available: true, changedFiles: record.changed_files || [] },
      risk: { available: true, ...risk },
      permissions: { available: true, ...permissions },
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
      available: (detail.artifacts || []).map(item => item.name),
      files: detail.artifacts || [],
      bundleUrl: `/cockpit/api/runs/${encodeURIComponent(record.run_id)}/bundle.zip`,
    },
    selection: {
      stage: STAGE_IDS.includes(selection?.stage) ? selection.stage : "plan",
      event: selection?.event ?? null,
    },
    errors: {
      ...errors,
      ...(verificationError ? { verification: verificationError } : {}),
    },
  };
}
